"""Run the CorpMind evaluation.

    python -m evaluation.run                         # full: retrieval + answers (needs LLM key)
    python -m evaluation.run --retrieval-only        # retrieval metrics only, no LLM needed
    python -m evaluation.run --judge llm             # LLM-as-judge for faithfulness & relevance
    python -m evaluation.run --sweep                 # find the best relevance threshold for your corpus

Prerequisites: sample data seeded (python -m app.scripts.seed_sample_data), which creates the
demo HR and Employee users that questions are asked as. Reports go to evaluation/reports/.

Each question runs through the real pipeline (answer_question) as a user of the role given in the
dataset, so access control is evaluated exactly as in production.
"""
import argparse
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import Role, User
from app.services.rag.pipeline import answer_question
from app.services.rag.prompt import FALLBACK_MESSAGE
from app.services.rag.retrieval import retrieve
from evaluation import metrics as M

HERE = Path(__file__).resolve().parent
REJECT_TYPES = {"unanswerable", "access_control"}
DEMO_EMAILS = {Role.HR: "hr.demo@northwind.local", Role.EMPLOYEE: "employee.demo@northwind.local"}


def load_dataset(path: Path) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))["items"]


def resolve_users(db: Session, overrides: dict[str, str] | None = None) -> dict[str, User]:
    users = {}
    for role in Role:
        email = (overrides or {}).get(role.value) or DEMO_EMAILS.get(role)
        u = db.scalar(select(User).where(User.email == email, User.is_active.is_(True))) if email else None
        if u is None:
            u = db.scalar(select(User).where(User.role == role, User.is_active.is_(True)).order_by(User.created_at))
        if u is not None and u.role == role:
            users[role.value] = u
    return users


# ------------------------------------------------------------------ per item

def evaluate_item(db: Session, item: dict, user: User, k: int, retrieval_only: bool, judge: str) -> dict:
    t0 = time.perf_counter()
    res = answer_question(db, user, item["question"], generate_answer=not retrieval_only)
    latency = (time.perf_counter() - t0) * 1000

    retrieved = [(c.title, c.page) for c in res.context]
    relevant = item.get("relevant", [])
    forbidden = set(item.get("forbidden_documents", []))
    should_reject = item["type"] in REJECT_TYPES
    out = {
        "id": item["id"], "type": item["type"], "role": item["role"], "question": item["question"],
        "mode": res.mode, "latency_ms": round(latency), "latency_breakdown": res.latency_ms,
        "retrieved": [{"title": t, "page": p, "section": c.section, "relevance": round(c.relevance, 3)}
                      for (t, p), c in zip(retrieved, res.context)],
        "leaked_forbidden": sorted({t for t, _ in retrieved} & forbidden),
        "confidence": res.confidence,
    }

    if should_reject:
        rejected = (not res.context) if retrieval_only else (res.answer == FALLBACK_MESSAGE)
        out.update(correctly_rejected=rejected, passed=rejected and not out["leaked_forbidden"])
        if not retrieval_only:
            out["answer"] = res.answer
        return out

    out.update(
        precision_at_k=round(M.precision_at_k(retrieved, relevant, k), 3),
        recall_at_k=round(M.recall_at_k(retrieved, relevant, k), 3),
        reciprocal_rank=round(M.reciprocal_rank(retrieved, relevant), 3),
    )
    if retrieval_only:
        out["passed"] = out["recall_at_k"] > 0 and not out["leaked_forbidden"]
        return out

    ctx = [c.text for c in res.context]
    cites = [(c.title, c.page) for c in res.citations]
    out.update(
        answer=res.answer, grounded=res.grounded, false_fallback=res.answer == FALLBACK_MESSAGE,
        key_fact_recall=M.key_fact_recall(res.answer, item.get("key_facts")),
        citation_precision=M.citation_precision(cites, relevant),
        citations=[{"title": t, "page": p} for t, p in cites],
        must_not_contain_violations=[s for s in item.get("must_not_contain", [])
                                     if M.normalize(s) in M.normalize(res.answer)],
    )
    if judge == "llm" and res.grounded:
        from evaluation.judge import judge_faithfulness, judge_relevance
        out["faithfulness"] = judge_faithfulness(res.answer, ctx)
        out["answer_relevance"] = judge_relevance(item["question"], res.answer)
        out["judge"] = "llm"
    else:
        out["faithfulness"] = M.heuristic_faithfulness(res.answer, ctx) if res.grounded else None
        out["answer_relevance"] = _embedding_relevance(item["question"], res.answer) if res.grounded else None
        out["judge"] = "heuristic"
    out["passed"] = bool(res.grounded and out["key_fact_recall"] == 1.0
                         and (out["citation_precision"] or 0) > 0
                         and not out["must_not_contain_violations"] and not out["leaked_forbidden"])
    return out


def _embedding_relevance(question: str, answer: str) -> float | None:
    """Cosine similarity between question and answer embeddings (normalised vectors)."""
    from app.services.embeddings import get_embedder
    try:
        e = get_embedder()
        q, a = e.embed_query(question), e.embed_documents([answer])[0]
    except Exception:
        return None
    return round(max(0.0, sum(x * y for x, y in zip(q, a))), 3)


# ------------------------------------------------------------------ threshold sweep

def threshold_sweep(db: Session, items: list[dict], users: dict[str, User]) -> dict:
    """For each threshold t: share of answerable questions that keep a relevant chunk (≥ t), and share
    of must-reject questions where every accessible chunk falls below t. Recommends the t with the best
    balance (mean of the two). Summarize/compare questions are skipped (they use their own retrieval)."""
    best_relevant, best_any = [], []
    for item in items:
        user = users.get(item["role"])
        if user is None or item["type"] in {"summarize", "compare"}:
            continue
        r = retrieve(db, user, item["question"], top_k=settings.RETRIEVAL_CANDIDATES, threshold_scale=0.0,
                     max_per_document=settings.RETRIEVAL_CANDIDATES)
        if item["type"] in REJECT_TYPES:
            best_any.append(max((c.relevance for c in r.chunks), default=0.0))
        else:
            rel = [c.relevance for c in r.chunks if M.is_relevant(c.title, c.page, item.get("relevant", []))]
            best_relevant.append(max(rel, default=0.0))
    rows = []
    for i in range(1, 20):
        t = round(i * 0.05, 2)
        recall = sum(v >= t for v in best_relevant) / len(best_relevant) if best_relevant else 0.0
        reject = sum(v < t for v in best_any) / len(best_any) if best_any else 0.0
        rows.append({"threshold": t, "answerable_kept": round(recall, 3), "unanswerable_rejected": round(reject, 3),
                     "balanced": round((recall + reject) / 2, 3)})
    best = max(rows, key=lambda r: (r["balanced"], r["answerable_kept"]))
    reranked = settings.ENABLE_RERANKER
    return {"scorer": "reranker" if reranked else "cosine/keyword",
            "setting": "RERANK_THRESHOLD" if reranked else "RELEVANCE_THRESHOLD",
            "current": settings.RERANK_THRESHOLD if reranked else settings.RELEVANCE_THRESHOLD,
            "recommended": best["threshold"], "table": rows,
            "answerable_best_scores": [round(v, 3) for v in best_relevant],
            "unanswerable_top_scores": [round(v, 3) for v in best_any]}


# ------------------------------------------------------------------ aggregate & report

def summarize(results: list[dict], retrieval_only: bool) -> dict:
    ans = [r for r in results if r["type"] not in REJECT_TYPES]
    rej = [r for r in results if r["type"] in REJECT_TYPES]
    s = {
        "questions": len(results),
        "pass_rate": M.mean(float(r["passed"]) for r in results),
        "retrieval": {
            "precision_at_k": M.mean(r.get("precision_at_k") for r in ans),
            "recall_at_k": M.mean(r.get("recall_at_k") for r in ans),
            "mrr": M.mean(r.get("reciprocal_rank") for r in ans),
            "hit_rate": M.mean(float(r.get("recall_at_k", 0) > 0) for r in ans),
        },
        "safety": {
            "correct_rejection_rate": M.mean(float(r["correctly_rejected"]) for r in rej),
            "forbidden_document_leaks": sum(bool(r["leaked_forbidden"]) for r in results),
        },
        "latency_ms": {"p50": M.percentile([r["latency_ms"] for r in results], 0.5),
                       "p95": M.percentile([r["latency_ms"] for r in results], 0.95),
                       "mean": M.mean(r["latency_ms"] for r in results)},
    }
    if not retrieval_only:
        s["answers"] = {
            "key_fact_recall": M.mean(r.get("key_fact_recall") for r in ans),
            "citation_precision": M.mean(r.get("citation_precision") for r in ans),
            "faithfulness": M.mean(r.get("faithfulness") for r in ans),
            "answer_relevance": M.mean(r.get("answer_relevance") for r in ans),
            "false_fallback_rate": M.mean(float(r.get("false_fallback", False)) for r in ans),
            "injection_violations": sum(len(r.get("must_not_contain_violations", [])) for r in results),
        }
    by_type: dict[str, list] = {}
    for r in results:
        by_type.setdefault(r["type"], []).append(r)
    s["by_type"] = {t: {"n": len(rs), "pass_rate": M.mean(float(r["passed"]) for r in rs),
                        "recall_at_k": M.mean(r.get("recall_at_k") for r in rs)} for t, rs in sorted(by_type.items())}
    return s


def config_snapshot(k: int, retrieval_only: bool, judge: str) -> dict:
    from app.services.embeddings import get_embedder
    try:
        emb = get_embedder().model_name
    except Exception:
        emb = settings.EMBEDDING_MODEL
    return {"embedding_model": emb, "reranker": settings.RERANKER_MODEL if settings.ENABLE_RERANKER else None,
            "llm": None if retrieval_only else f"{settings.LLM_PROVIDER}:{settings.LLM_MODEL}",
            "k": k, "relevance_threshold": settings.RELEVANCE_THRESHOLD, "rerank_threshold": settings.RERANK_THRESHOLD,
            "chunk_size": settings.CHUNK_SIZE, "chunk_overlap": settings.CHUNK_OVERLAP,
            "retrieval_only": retrieval_only,
            "judge": None if retrieval_only else ("llm" if judge == "llm" else "heuristic")}


def run_evaluation(db: Session, items: list[dict], users: dict[str, User], k: int | None = None,
                   retrieval_only: bool = False, judge: str = "none", sweep: bool = False) -> dict:
    k = k or settings.RETRIEVAL_TOP_K
    results = []
    for item in items:
        user = users.get(item["role"])
        if user is None:
            results.append({"id": item["id"], "type": item["type"], "role": item["role"], "skipped": True})
            continue
        results.append(evaluate_item(db, item, user, k, retrieval_only, judge))
    done = [r for r in results if not r.get("skipped")]
    report = {"generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
              "config": config_snapshot(k, retrieval_only, judge),
              "summary": summarize(done, retrieval_only), "results": results,
              "skipped": [r["id"] for r in results if r.get("skipped")]}
    if sweep:
        report["threshold_sweep"] = threshold_sweep(db, items, users)
    return report


def _fmt(v) -> str:
    if v is None:
        return "–"
    if isinstance(v, float):
        return f"{v:.2f}"
    return str(v)


def to_markdown(report: dict) -> str:
    c, s = report["config"], report["summary"]
    lines = [f"# CorpMind evaluation report", "", f"Generated {report['generated_at']}", "",
             "## Configuration", "", "| Setting | Value |", "|---|---|"]
    lines += [f"| {k} | {_fmt(v)} |" for k, v in c.items()]
    lines += ["", "## Summary", "", "| Metric | Value |", "|---|---|",
              f"| Questions | {s['questions']} |", f"| Pass rate | {_fmt(s['pass_rate'])} |",
              f"| Precision@{c['k']} | {_fmt(s['retrieval']['precision_at_k'])} |",
              f"| Recall@{c['k']} | {_fmt(s['retrieval']['recall_at_k'])} |",
              f"| MRR | {_fmt(s['retrieval']['mrr'])} |",
              f"| Hit rate | {_fmt(s['retrieval']['hit_rate'])} |",
              f"| Correct rejection rate (unanswerable + access control) | {_fmt(s['safety']['correct_rejection_rate'])} |",
              f"| Forbidden-document leaks | {s['safety']['forbidden_document_leaks']} |"]
    if "answers" in s:
        a = s["answers"]
        lines += [f"| Key-fact recall (answer correctness) | {_fmt(a['key_fact_recall'])} |",
                  f"| Citation precision | {_fmt(a['citation_precision'])} |",
                  f"| Faithfulness ({c['judge']}) | {_fmt(a['faithfulness'])} |",
                  f"| Answer relevance ({c['judge']}) | {_fmt(a['answer_relevance'])} |",
                  f"| False 'not found' rate | {_fmt(a['false_fallback_rate'])} |",
                  f"| Prompt-injection violations | {a['injection_violations']} |"]
    lines += [f"| Latency p50 / p95 (ms) | {_fmt(s['latency_ms']['p50'])} / {_fmt(s['latency_ms']['p95'])} |",
              "", "## By question type", "", "| Type | n | Pass rate | Recall@k |", "|---|---|---|---|"]
    lines += [f"| {t} | {v['n']} | {_fmt(v['pass_rate'])} | {_fmt(v['recall_at_k'])} |" for t, v in s["by_type"].items()]
    lines += ["", "## Per question", "", "| Id | Type | P@k | R@k | Key facts | Cit. prec. | Faithful | ms | Pass |",
              "|---|---|---|---|---|---|---|---|---|"]
    for r in report["results"]:
        if r.get("skipped"):
            lines.append(f"| {r['id']} | {r['type']} | skipped (no {r['role']} user) | | | | | | |")
            continue
        lines.append(f"| {r['id']} | {r['type']} | {_fmt(r.get('precision_at_k'))} | {_fmt(r.get('recall_at_k'))} | "
                     f"{_fmt(r.get('key_fact_recall'))} | {_fmt(r.get('citation_precision'))} | "
                     f"{_fmt(r.get('faithfulness'))} | {r['latency_ms']} | {'✅' if r['passed'] else '❌'} |")
    failed = [r for r in report["results"] if not r.get("skipped") and not r["passed"]]
    if failed:
        lines += ["", "## Failures", ""]
        for r in failed:
            got = ", ".join(f"{x['title']} ({'p' + str(x['page']) if x['page'] else x.get('section') or 'n/a'})"
                            for x in r["retrieved"][:4]) or "nothing"
            lines.append(f"- **{r['id']}**: retrieved {got}"
                         + (f"; leaked {r['leaked_forbidden']}" if r["leaked_forbidden"] else "")
                         + (f"; answer: {r['answer'][:160]!r}" if r.get("answer") else ""))
    if "threshold_sweep" in report:
        sw = report["threshold_sweep"]
        lines += ["", "## Threshold sweep", "",
                  f"Scorer: {sw['scorer']}. Current `{sw['setting']}` = {sw['current']}; "
                  f"**recommended {sw['recommended']}** (best balance of keeping answerable questions and "
                  "rejecting unanswerable ones).", "",
                  "| Threshold | Answerable kept | Unanswerable rejected | Balanced |", "|---|---|---|---|"]
        lines += [f"| {r['threshold']} | {r['answerable_kept']:.2f} | {r['unanswerable_rejected']:.2f} | {r['balanced']:.2f} |"
                  for r in sw["table"]]
    return "\n".join(lines) + "\n"


def write_reports(report: dict, out_dir: Path) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    j, m = out_dir / f"eval-{stamp}.json", out_dir / f"eval-{stamp}.md"
    j.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    m.write_text(to_markdown(report), encoding="utf-8")
    return j, m


def main() -> None:
    from app.db.session import SessionLocal

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dataset", type=Path, default=HERE / "dataset.json")
    ap.add_argument("--k", type=int, default=None, help="k for Precision/Recall@k (default RETRIEVAL_TOP_K)")
    ap.add_argument("--retrieval-only", action="store_true", help="skip answer generation (no LLM needed)")
    ap.add_argument("--judge", choices=["none", "llm"], default="none")
    ap.add_argument("--sweep", action="store_true", help="also run the relevance-threshold sweep")
    ap.add_argument("--employee-email")
    ap.add_argument("--hr-email")
    ap.add_argument("--out", type=Path, default=HERE / "reports")
    args = ap.parse_args()

    items = load_dataset(args.dataset)
    with SessionLocal() as db:
        users = resolve_users(db, {"employee": args.employee_email, "hr": args.hr_email})
        if not users:
            sys.exit("No users found. Run: python -m app.scripts.seed_sample_data")
        report = run_evaluation(db, items, users, args.k, args.retrieval_only, args.judge, args.sweep)
    j, m = write_reports(report, args.out)
    print(to_markdown(report).split("## By question type")[0])
    print(f"Full report: {m}\nRaw results: {j}")


if __name__ == "__main__":
    main()
