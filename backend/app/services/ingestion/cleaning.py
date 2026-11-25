"""Text cleaning applied after parsing, before chunking.

Steps (all conservative; we never rewrite meaning):
1. Unicode NFKC normalisation (ligatures like "ﬁ" -> "fi", full-width chars -> normal).
2. Remove control and zero-width/invisible characters. These are a common way to hide
   prompt-injection text inside documents, so stripping them is also a security measure.
3. Re-join words hyphenated across line breaks ("reimburse-\\nment" -> "reimbursement").
4. Remove PDF running headers/footers: short lines repeated on most pages, and bare page numbers.
5. Collapse runs of spaces and excess blank lines.
"""
import re
import unicodedata
from collections import Counter

from app.services.ingestion.parsers import Segment

# Zero-width and bidi-control characters (U+200B..U+200F, U+202A..U+202E, U+2060..U+2064, U+FEFF)
_INVISIBLE = re.compile("[​-‏‪-‮⁠-⁤﻿­]")
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_HYPHEN_BREAK = re.compile(r"(\w)-\n(\w)")
_PAGE_NUMBER_LINE = re.compile(r"^\s*(page\s*)?\d{1,4}(\s*(of|/)\s*\d{1,4})?\s*$", re.IGNORECASE)
_MULTI_SPACE = re.compile(r"[ \t]+")
_MULTI_NEWLINE = re.compile(r"\n{3,}")


def clean_text(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _INVISIBLE.sub("", text)
    text = _CONTROL.sub(" ", text)
    text = _HYPHEN_BREAK.sub(r"\1\2", text)
    lines = [_MULTI_SPACE.sub(" ", ln).strip() for ln in text.split("\n")]
    text = "\n".join(lines)
    return _MULTI_NEWLINE.sub("\n\n", text).strip()


def _normalise_line(line: str) -> str:
    return re.sub(r"\d+", "#", line.strip().lower())


def remove_repeated_headers_footers(segments: list[Segment], min_pages: int = 3, ratio: float = 0.6) -> list[Segment]:
    """Drop short lines that appear on >= `ratio` of pages (e.g. "Acme Corp — Confidential", "Page 3 of 12")."""
    paged = [s for s in segments if s.page is not None]
    if len(paged) < min_pages:
        return segments
    counts: Counter[str] = Counter()
    for s in paged:
        lines = {_normalise_line(ln) for ln in s.text.split("\n") if 0 < len(ln.strip()) <= 80}
        counts.update(lines)
    threshold = max(2, int(len(paged) * ratio))
    repeated = {ln for ln, c in counts.items() if c >= threshold}
    out = []
    for s in segments:
        kept = [ln for ln in s.text.split("\n")
                if _normalise_line(ln) not in repeated and not _PAGE_NUMBER_LINE.match(ln)]
        out.append(Segment(text="\n".join(kept), page=s.page, section=s.section))
    return out


def clean_segments(segments: list[Segment]) -> list[Segment]:
    cleaned = [Segment(text=clean_text(s.text), page=s.page, section=s.section) for s in segments]
    cleaned = remove_repeated_headers_footers(cleaned)
    return [s for s in cleaned if s.text.strip()]
