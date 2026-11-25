"""Steps 8-9: call the LLM, then validate and clean its output.

Post-processing enforces what the prompt asks for, instead of trusting the model:
- The fallback token (or the fallback sentence) -> the exact required "couldn't find" message.
- Citations like [2] or [1, 3] are parsed. Indexes that don't exist are removed from the text.
- An answer with NO valid citation is treated as ungrounded and replaced by the fallback message.
  This is how "never fabricate company information" is enforced in code.
- Images, links and raw HTML are stripped (a classic injection trick is making the model emit an
  image URL that leaks data when the browser loads it).
"""
import re
from dataclasses import dataclass

from app.services.llm import invoke_text
from app.services.rag.prompt import FALLBACK_MESSAGE, FALLBACK_TOKEN, build_messages
from app.services.rag.retrieval import RetrievedChunk

_CITATION = re.compile(r"\[(\d+(?:\s*,\s*\d+)*)\]")

# Models cite in different styles. These are rewritten to the canonical [n] before validation:
#   【1】 【1†L3-L5】 (gpt-oss)   [1†source]   [^1] (footnote)   [Document 1] / [Doc 1] / [Source 1]
#   [1][2] and [1, 2] are already canonical.
_ALT_CITATIONS = [
    re.compile(r"【\s*(\d+)[^】]*】"),
    re.compile(r"\[\s*(\d+)\s*†[^\]]*\]"),
    re.compile(r"\[\^(\d+)\]"),
    re.compile(r"\[\s*(?:document|doc|source|ref)\.?\s*#?\s*(\d+)\s*\]", re.I),
    re.compile(r"\(\s*(?:document|doc|source)\.?\s*#?\s*(\d+)\s*\)", re.I),
]


def normalize_citations(text: str) -> str:
    for pattern in _ALT_CITATIONS:
        text = pattern.sub(lambda m: f"[{m.group(1)}]", text)
    # [Documents 1 and 2] / [Sources 1, 3] -> [1, 2] / [1, 3]
    text = re.sub(r"\[\s*(?:documents|docs|sources)\s+(\d+(?:\s*(?:,|and)\s*\d+)*)\s*\]",
                  lambda m: "[" + re.sub(r"\s*(?:,|and)\s*", ", ", m.group(1)) + "]", text, flags=re.I)
    return text
_IMAGE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_LINK = re.compile(r"\[([^\]]+)\]\((?:https?|ftp|mailto|javascript|data):[^)]*\)", re.I)
_BARE_URL_AUTOLINK = re.compile(r"<(?:https?|ftp|mailto):[^>]+>", re.I)
_HTML_TAG = re.compile(r"</?[a-zA-Z][a-zA-Z0-9-]*(\s[^<>]*)?/?>")


@dataclass
class Citation:
    index: int
    chunk_id: str
    document_id: str
    title: str
    page: int | None
    section: str | None
    snippet: str
    relevance: float


@dataclass
class GeneratedAnswer:
    text: str
    citations: list[Citation]
    grounded: bool          # False -> fallback message was returned


def sanitize_output(text: str) -> str:
    text = _IMAGE.sub("", text)
    text = _LINK.sub(r"\1", text)
    text = _BARE_URL_AUTOLINK.sub("", text)
    text = _HTML_TAG.sub("", text)
    return text.strip()


def _snippet(text: str, limit: int = 280) -> str:
    t = " ".join(text.split())
    return t if len(t) <= limit else t[:limit].rsplit(" ", 1)[0] + "…"


def is_fallback(text: str) -> bool:
    t = text.strip().strip(".").strip()
    return (t == FALLBACK_TOKEN or t.startswith(FALLBACK_TOKEN)
            or FALLBACK_MESSAGE.lower().rstrip(".") in text.lower())


def postprocess(raw: str, chunks: list[RetrievedChunk]) -> GeneratedAnswer:
    if not raw or is_fallback(raw):
        return GeneratedAnswer(FALLBACK_MESSAGE, [], False)
    text = sanitize_output(normalize_citations(raw))
    n = len(chunks)
    used: list[int] = []

    def fix(m: re.Match) -> str:
        valid = []
        for part in m.group(1).split(","):
            i = int(part.strip())
            if 1 <= i <= n:
                valid.append(i)
                if i not in used:
                    used.append(i)
        return "".join(f"[{i}]" for i in dict.fromkeys(valid))

    text = _CITATION.sub(fix, text)
    text = re.sub(r"[ \t]+([.,;:])", r"\1", text).strip()
    if not used or not text:
        return GeneratedAnswer(FALLBACK_MESSAGE, [], False)
    citations = [Citation(index=i, chunk_id=chunks[i - 1].chunk_id, document_id=str(chunks[i - 1].document_id),
                          title=chunks[i - 1].title, page=chunks[i - 1].page, section=chunks[i - 1].section,
                          snippet=_snippet(chunks[i - 1].text), relevance=round(chunks[i - 1].relevance, 3))
                 for i in sorted(used)]
    return GeneratedAnswer(text, citations, True)


def generate(question: str, chunks: list[RetrievedChunk], mode: str, truncated: bool = False) -> GeneratedAnswer:
    raw = invoke_text(build_messages(question, chunks, mode, truncated))
    return postprocess(raw, chunks)
