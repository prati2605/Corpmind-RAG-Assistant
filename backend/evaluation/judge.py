"""Optional LLM-as-judge for faithfulness and answer relevance (`--judge llm`).

Uses the same configured LLM. Judges are asked for strict JSON; if parsing fails the score is
None (reported as missing), never guessed. The context passed to the judge is the exact set of
chunks the pipeline retrieved, so faithfulness means "supported by what the model was shown".
"""
import json
import re

from langchain_core.messages import HumanMessage, SystemMessage

from app.services.llm import LLMUnavailable, invoke_text

_FAITH_SYS = """You are a strict evaluator. Break the ANSWER into its individual factual claims (ignore citation
markers like [1] and generic phrasing). For each claim decide whether it is fully supported by the CONTEXT.
A claim with any number, date or name not present in the CONTEXT is unsupported.
Return ONLY JSON: {"claims": <int>, "supported": <int>}"""

_REL_SYS = """You are a strict evaluator. Rate how directly and completely the ANSWER addresses the QUESTION,
regardless of whether it is correct. 5 = fully answers it, 3 = partially, 1 = does not address it.
Return ONLY JSON: {"score": <1-5>}"""


def _json(text: str) -> dict | None:
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


def judge_faithfulness(answer: str, context_texts: list[str]) -> float | None:
    ctx = "\n\n---\n\n".join(context_texts)[:20000]
    try:
        out = invoke_text([SystemMessage(_FAITH_SYS), HumanMessage(f"CONTEXT:\n{ctx}\n\nANSWER:\n{answer}")])
    except LLMUnavailable:
        return None
    d = _json(out)
    try:
        claims, supported = int(d["claims"]), int(d["supported"])
    except (TypeError, KeyError, ValueError):
        return None
    if claims <= 0:
        return None
    return max(0.0, min(1.0, supported / claims))


def judge_relevance(question: str, answer: str) -> float | None:
    try:
        out = invoke_text([SystemMessage(_REL_SYS), HumanMessage(f"QUESTION:\n{question}\n\nANSWER:\n{answer}")])
    except LLMUnavailable:
        return None
    d = _json(out)
    try:
        score = float(d["score"])
    except (TypeError, KeyError, ValueError):
        return None
    return round((max(1.0, min(5.0, score)) - 1) / 4, 3)  # map 1..5 -> 0..1
