"""Steps 1-2 of the pipeline: understand and preprocess the user's question.

- clean_query:        normalise whitespace / invisible characters, enforce max length
- is_small_talk:      "hi", "thanks" -> friendly reply without retrieval or LLM call
- condense_question:  turn a follow-up ("what about for contractors?") into a standalone
                      question using recent conversation history, so retrieval works
- detect_mode:        qa | summarize | compare
- match_documents:    find which of the user's *accessible* documents the question names
                      (used to scope summarize / compare requests)
"""
import logging
import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher

from langchain_core.messages import HumanMessage, SystemMessage

from app.services.ingestion.cleaning import clean_text
from app.services.llm import LLMUnavailable, invoke_text

log = logging.getLogger("corpmind.rag")

MAX_QUERY_CHARS = 2000
HISTORY_TURNS = 6

_SMALL_TALK = re.compile(
    r"^\s*(hi|hii+|hello|hey|good (morning|afternoon|evening)|thanks|thank you|thx|ok(ay)?|cool|great|bye|goodbye)"
    r"[\s!.,]*(there|claude|corpmind|a lot|so much)?[\s!.]*$", re.I)

_SUMMARIZE = re.compile(r"\b(summari[sz]e|summary|overview|key points|tl;?dr|gist|outline|main points)\b", re.I)
_COMPARE = re.compile(r"\b(compare|comparison|difference|differences|differ|versus|vs\.?|contrast)\b", re.I)

_STOPWORDS = {
    "the", "a", "an", "of", "and", "or", "for", "to", "in", "on", "at", "by", "with", "policy", "policies",
    "document", "doc", "guide", "guidelines", "v", "version", "final", "draft", "company", "our",
}


@dataclass
class PreparedQuery:
    original: str
    standalone: str
    mode: str                       # "qa" | "summarize" | "compare"
    rewritten: bool = False
    target_document_ids: list = field(default_factory=list)


def clean_query(q: str) -> str:
    q = clean_text(q or "")
    q = re.sub(r"\s+", " ", q).strip()
    if not q:
        raise ValueError("Question is empty")
    if len(q) > MAX_QUERY_CHARS:
        raise ValueError(f"Question is too long (max {MAX_QUERY_CHARS} characters)")
    return q


def is_small_talk(q: str) -> bool:
    return bool(_SMALL_TALK.match(q))


SMALL_TALK_REPLY = ("Hello! I'm CorpMind, your company knowledge assistant. Ask me about company policies, "
                    "procedures, dates or documents, and I'll answer with citations from the documents you can access.")

_CONDENSE_SYSTEM = (
    "You rewrite a user's follow-up question into a single standalone question that can be understood "
    "without the conversation. Resolve pronouns and references (\"it\", \"that policy\", \"what about X\") "
    "using the conversation. Keep names, dates and numbers exactly. If the question is already standalone, "
    "return it unchanged. Output ONLY the rewritten question, with no preamble and no answer."
)


def condense_question(question: str, history: list[dict]) -> tuple[str, bool]:
    """history: [{"role": "user"|"assistant", "content": str}, ...] oldest first."""
    recent = [h for h in history if h.get("content")][-HISTORY_TURNS:]
    if not recent:
        return question, False
    convo = "\n".join(
        f"{'User' if h['role'] == 'user' else 'Assistant'}: {h['content'][:600]}" for h in recent)
    try:
        out = invoke_text([
            SystemMessage(_CONDENSE_SYSTEM),
            HumanMessage(f"Conversation:\n{convo}\n\nFollow-up question: {question}\n\nStandalone question:"),
        ])
    except LLMUnavailable:
        raise
    out = out.strip().strip('"').splitlines()[0].strip() if out.strip() else ""
    if not out or len(out) > MAX_QUERY_CHARS:
        return question, False
    return out, out.lower() != question.lower()


def detect_mode(q: str, matched_docs: int) -> str:
    if _COMPARE.search(q) or (matched_docs >= 2 and re.search(r"\b(between|and)\b", q, re.I)
                              and re.search(r"\b(both|each|two)\b", q, re.I)):
        return "compare"
    if _SUMMARIZE.search(q):
        return "summarize"
    return "qa"


def _tokens(text: str) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9]+", text.lower()) if t not in _STOPWORDS and len(t) > 1]


def match_documents(q: str, documents: list[tuple]) -> list:
    """documents: [(id, title), ...] the user can access. Returns ids named in the question, best first.

    A document matches when most of its distinctive title words appear in the question
    (allowing small typos), e.g. "summarise the travel policy" matches "Travel & Expense Policy".
    """
    q_tokens = _tokens(q)
    if not q_tokens:
        return []
    scored = []
    for doc_id, title in documents:
        t_tokens = _tokens(title)
        if not t_tokens:
            continue
        hits = sum(1 for t in t_tokens if any(
            qt == t or (len(t) > 4 and SequenceMatcher(None, qt, t).ratio() >= 0.85) for qt in q_tokens))
        coverage = hits / len(t_tokens)
        if hits and (coverage >= 0.6 or (hits >= 2 and coverage >= 0.5)):
            scored.append((coverage, hits, doc_id))
    scored.sort(reverse=True)
    return [d for _, _, d in scored]
