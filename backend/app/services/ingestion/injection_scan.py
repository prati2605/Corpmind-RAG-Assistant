"""Heuristic detection of prompt-injection text hidden inside uploaded documents.

Layer 1 of the defense (ingestion time). Matches are recorded on the chunk and the version,
and admins see a warning badge so they can review the file. Flagged chunks are NOT silently
dropped: a security policy that *discusses* prompt injection is legitimate content.

The decisive protection is at query time (Phase 3): document text is always wrapped as
untrusted data in the prompt, and flagged chunks get an extra warning. Heuristics like these
can be evaded, which is why they are one layer, not the only one.
"""
import re
from dataclasses import dataclass

_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("override_instructions", re.compile(
        r"\b(ignore|disregard|forget|override|bypass)\b.{0,40}\b(previous|prior|above|earlier|all|system|your)\b.{0,30}"
        r"\b(instructions?|prompts?|rules?|directives?|guidelines?)", re.I | re.S)),
    ("new_instructions", re.compile(r"\b(new|updated|real|actual)\s+(system\s+)?instructions?\s*[:\-]", re.I)),
    ("role_hijack", re.compile(r"\b(you are now|from now on,? you|act as|pretend to be|roleplay as)\b", re.I)),
    ("fake_role_tag", re.compile(r"(<\|?\s*(system|assistant|im_start|im_end)\s*\|?>|^\s*(system|assistant)\s*:)", re.I | re.M)),
    ("prompt_exfiltration", re.compile(
        r"\b(reveal|print|output|show|repeat|leak)\b.{0,30}\b(system prompt|hidden prompt|instructions|api key|secret)", re.I | re.S)),
    ("ai_directed", re.compile(r"\b(attention|note to|message to|instructions? for)\s+(the\s+)?(ai|assistant|llm|chatbot|language model)\b", re.I)),
    ("answer_manipulation", re.compile(
        r"\b(always|must)\s+(answer|respond|reply|say|tell)\b.{0,60}\b(regardless|no matter|even if)\b", re.I | re.S)),
    ("exfil_link", re.compile(r"!\[[^\]]*\]\(https?://[^)]*\{", re.I)),  # markdown image with templated URL
]


@dataclass
class Finding:
    rule: str
    excerpt: str


def _excerpt(text: str, start: int, end: int, pad: int = 30, limit: int = 160) -> str:
    """The match plus a little context, widened to whole words, with ellipses where text was cut."""
    a, b = max(0, start - pad), min(len(text), end + pad)
    while a > 0 and not text[a - 1].isspace():
        a -= 1
    while b < len(text) and not text[b].isspace():
        b += 1
    snippet = " ".join(text[a:b].split())
    if len(snippet) > limit:
        snippet = snippet[:limit].rsplit(" ", 1)[0]
        b = len(text)  # force trailing ellipsis
    return ("…" if a > 0 else "") + snippet + ("…" if b < len(text) else "")


def scan_text(text: str) -> list[Finding]:
    findings = []
    for rule, pattern in _PATTERNS:
        m = pattern.search(text)
        if m:
            findings.append(Finding(rule=rule, excerpt=_excerpt(text, m.start(), m.end())))
    return findings
