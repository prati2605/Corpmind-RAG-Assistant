"""Evaluation metrics. All pure functions: no DB, no LLM.

Retrieval (is the right evidence found?)
  precision_at_k   share of the top-k retrieved chunks that come from a relevant document/page.
                   Denominator = chunks actually returned (≤ k), because the relevance threshold may
                   legitimately return fewer than k; a stricter "/k" variant would punish that.
  recall_at_k      share of the relevant documents/pages that appear in the top k.
  reciprocal_rank  1 / rank of the first relevant chunk (0 if none). Averaged = MRR.

Answer (is the answer right, grounded and properly cited?)
  key_fact_recall      share of required facts (numbers, dates, names) present in the answer.
  citation_precision   share of citations pointing to a relevant document/page.
  heuristic_faithfulness  share of answer sentences supported by the retrieved context:
                       most content words must appear in the context AND every number must.
                       (An LLM judge variant lives in judge.py.)
"""
import re
import statistics

_STOP = set("""a an the and or of to in on at for by with from as is are was were be been being this that these those it its
you your we our they their i me my he she his her them do does did can could may might must shall should will would
not no yes per each any all if then than so such into about over under up down out also only just more most less
which who whom what when where why how there here have has had""".split())


def normalize(s: str) -> str:
    s = s.lower().replace("–", "-").replace("—", "-").replace("‑", "-")
    s = re.sub(r"(?<=\d),(?=\d{2,3}\b)", "", s)    # 15,000 -> 15000 ; 1,50,000 -> 150000
    s = re.sub(r"\*+|`|_", "", s)                   # markdown emphasis
    return re.sub(r"\s+", " ", s).strip()


def key_fact_recall(answer: str, groups: list[list[str]] | None) -> float | None:
    if not groups:
        return None
    a = normalize(answer)
    hits = sum(1 for alts in groups if any(normalize(alt) in a for alt in alts))
    return hits / len(groups)


def is_relevant(title: str, page: int | None, relevant: list[dict]) -> bool:
    return any(r["title"] == title and (r.get("page") is None or r.get("page") == page) for r in relevant)


def precision_at_k(retrieved: list[tuple[str, int | None]], relevant: list[dict], k: int) -> float:
    top = retrieved[:k]
    if not top:
        return 0.0
    return sum(is_relevant(t, p, relevant) for t, p in top) / len(top)


def recall_at_k(retrieved: list[tuple[str, int | None]], relevant: list[dict], k: int) -> float:
    if not relevant:
        return 0.0
    top = retrieved[:k]
    found = sum(1 for r in relevant if any(is_relevant(t, p, [r]) for t, p in top))
    return found / len(relevant)


def reciprocal_rank(retrieved: list[tuple[str, int | None]], relevant: list[dict]) -> float:
    for rank, (t, p) in enumerate(retrieved, start=1):
        if is_relevant(t, p, relevant):
            return 1.0 / rank
    return 0.0


def citation_precision(citations: list[tuple[str, int | None]], relevant: list[dict]) -> float | None:
    if not citations:
        return None
    return sum(is_relevant(t, p, relevant) for t, p in citations) / len(citations)


def _content_tokens(s: str) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9][a-z0-9\-:/.]*[a-z0-9]|[a-z0-9]", normalize(s)) if t not in _STOP]


def _numbers(s: str) -> set[str]:
    return set(re.findall(r"\d+(?:\.\d+)?", normalize(s)))


def split_sentences(answer: str) -> list[str]:
    text = re.sub(r"\[\d+\]", "", answer)
    text = re.sub(r"^\s*([-*•]|\d+\.)\s+", "", text, flags=re.M)        # list markers
    text = re.sub(r"^\s*#+\s*", "", text, flags=re.M)                   # headings
    text = re.sub(r"\|", " ", text)                                     # table pipes
    parts = re.split(r"(?<=[.!?])\s+|\n+", text)
    return [p.strip() for p in parts if len(_content_tokens(p)) >= 3]


def heuristic_faithfulness(answer: str, context_texts: list[str], word_threshold: float = 0.6) -> float | None:
    sentences = split_sentences(answer)
    if not sentences:
        return None
    ctx = normalize(" ".join(context_texts))
    ctx_tokens = set(_content_tokens(ctx))
    ctx_numbers = _numbers(ctx)
    supported = 0
    for s in sentences:
        toks = _content_tokens(s)
        coverage = sum(t in ctx_tokens for t in toks) / len(toks)
        if coverage >= word_threshold and _numbers(s) <= ctx_numbers:
            supported += 1
    return supported / len(sentences)


def mean(values) -> float | None:
    vals = [v for v in values if v is not None]
    return round(statistics.fmean(vals), 3) if vals else None


def percentile(values, p: float) -> float | None:
    vals = sorted(v for v in values if v is not None)
    if not vals:
        return None
    if len(vals) == 1:
        return float(vals[0])
    idx = (len(vals) - 1) * p
    lo, hi = int(idx), min(int(idx) + 1, len(vals) - 1)
    return round(vals[lo] + (vals[hi] - vals[lo]) * (idx - lo), 1)
