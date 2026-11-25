"""Evaluation module: metric math, LLM-judge parsing, sample-data seeding, and an end-to-end run."""
import pytest
from sqlalchemy import select

from app.db.session import SessionLocal
from app.models import Role, User
from app.services.llm import set_llm
from evaluation import metrics as M
from evaluation.run import HERE, load_dataset, resolve_users, run_evaluation, to_markdown, write_reports
from tests.conftest import make_user
from tests.fixtures import ScriptedLLM

REL = [{"title": "Leave Policy", "page": 2}, {"title": "Remote Work Policy"}]


# ---------------- metric math (hand-computed) ----------------

def test_precision_recall_mrr():
    retrieved = [("Travel", 1), ("Leave Policy", 2), ("Leave Policy", 3), ("Remote Work Policy", 1)]
    assert M.precision_at_k(retrieved, REL, 4) == 0.5            # 2 of 4 relevant (Leave p3 is wrong page)
    assert M.precision_at_k(retrieved, REL, 2) == 0.5
    assert M.recall_at_k(retrieved, REL, 2) == 0.5               # only Leave p2 within top 2
    assert M.recall_at_k(retrieved, REL, 4) == 1.0
    assert M.reciprocal_rank(retrieved, REL) == 0.5              # first relevant at rank 2
    assert M.precision_at_k([], REL, 5) == 0.0 and M.reciprocal_rank([], REL) == 0.0


def test_key_fact_recall_with_alternatives_and_number_formats():
    groups = [["15000", "15,000"], ["31 march", "march 31"]]
    assert M.key_fact_recall("An allowance of INR 15,000 ... expires on March 31.", groups) == 1.0
    assert M.key_fact_recall("An allowance of **INR 15000**.", groups) == 0.5
    assert M.key_fact_recall("nothing", groups) == 0.0
    assert M.key_fact_recall("x", None) is None


def test_citation_precision():
    assert M.citation_precision([("Leave Policy", 2), ("Travel", 1)], REL) == 0.5
    assert M.citation_precision([], REL) is None


def test_heuristic_faithfulness_requires_numbers_in_context():
    ctx = ["Up to 10 unused annual leave days may be carried forward. They expire on 31 March."]
    good = "Up to 10 unused annual leave days may be carried forward [1]."
    bad_number = "Up to 15 unused annual leave days may be carried forward [1]."
    unrelated = "Employees receive a generous relocation bonus package annually."
    assert M.heuristic_faithfulness(good, ctx) == 1.0
    assert M.heuristic_faithfulness(bad_number, ctx) == 0.0
    assert M.heuristic_faithfulness(good + " " + unrelated, ctx) == 0.5


def test_percentile():
    assert M.percentile([100, 200, 300, 400], 0.5) == 250.0
    assert M.percentile([5], 0.95) == 5.0 and M.percentile([], 0.5) is None


def test_llm_judge_parsing():
    from evaluation.judge import judge_faithfulness, judge_relevance
    set_llm(ScriptedLLM(responder=lambda m: 'Sure: {"claims": 4, "supported": 3}'))
    assert judge_faithfulness("a", ["b"]) == 0.75
    set_llm(ScriptedLLM(responder=lambda m: '{"score": 5}'))
    assert judge_relevance("q", "a") == 1.0
    set_llm(ScriptedLLM(responder=lambda m: "not json"))
    assert judge_faithfulness("a", ["b"]) is None   # never guessed


def test_dataset_is_well_formed():
    items = load_dataset(HERE / "dataset.json")
    assert len(items) >= 25 and len({i["id"] for i in items}) == len(items)
    for i in items:
        assert i["role"] in {"employee", "hr"}
        if i["type"] in {"unanswerable", "access_control"}:
            assert i["expected_answer"] == "FALLBACK"
        else:
            assert i["relevant"] and i["key_facts"], i["id"]


# ---------------- seeding + end-to-end ----------------

@pytest.fixture
def seeded(client):
    from app.scripts.seed_sample_data import seed_documents
    admin = make_user("admin@corp.test", Role.ADMIN)
    make_user("hr.demo@northwind.local", Role.HR)
    make_user("employee.demo@northwind.local", Role.EMPLOYEE)
    with SessionLocal() as db:
        admin = db.get(User, admin.id)
        summary = seed_documents(db, admin, verbose=False)
    return summary


def test_seed_loads_all_sample_documents_idempotently(seeded):
    from app.scripts.seed_sample_data import seed_documents
    assert seeded == {"uploaded": 13, "skipped": 0, "failed": 0}
    with SessionLocal() as db:
        admin = db.scalar(select(User).where(User.role == Role.ADMIN))
        assert seed_documents(db, admin, verbose=False) == {"uploaded": 0, "skipped": 13, "failed": 0}
        from app.models import DocumentVersion
        flagged = db.scalars(select(DocumentVersion.original_filename).where(DocumentVersion.injection_flagged)).all()
    assert flagged == ["Vendor Portal Notes.txt"]


def test_end_to_end_evaluation_run(seeded, tmp_path):
    items = load_dataset(HERE / "dataset.json")
    with SessionLocal() as db:
        users = resolve_users(db)
        assert {u.email for u in users.values()} >= {"hr.demo@northwind.local", "employee.demo@northwind.local"}
        report = run_evaluation(db, items, users, k=5, retrieval_only=False, judge="none", sweep=True)
        retrieval_report = run_evaluation(db, items, users, k=5, retrieval_only=True)

    s = report["summary"]
    assert s["questions"] == len(items) and not report["skipped"]
    # Access control holds during evaluation, regardless of retrieval quality:
    assert s["safety"]["forbidden_document_leaks"] == 0
    assert s["answers"]["injection_violations"] == 0
    for key in ("precision_at_k", "recall_at_k", "mrr", "hit_rate"):
        assert 0.0 <= s["retrieval"][key] <= 1.0
    for key in ("key_fact_recall", "citation_precision", "faithfulness", "false_fallback_rate"):
        assert key in s["answers"]
    assert s["latency_ms"]["p95"] >= s["latency_ms"]["p50"] > 0
    # Exact-term questions should be found even by the simple test embedder (hybrid keyword search)
    by_id = {r["id"]: r for r in report["results"]}
    assert by_id["travel-claims"]["recall_at_k"] == 1.0
    assert by_id["summarize-infosec"]["mode"] == "summarize"
    assert by_id["compare-probation"]["mode"] == "compare"
    # Unanswerable world-knowledge question must not be answered from model knowledge
    assert by_id["acl-falcon-employee"]["leaked_forbidden"] == []

    sweep = report["threshold_sweep"]
    assert len(sweep["table"]) == 19 and 0.05 <= sweep["recommended"] <= 0.95
    assert "answers" not in retrieval_report["summary"]

    md = to_markdown(report)
    assert "## Summary" in md and "Precision@5" in md and "## Threshold sweep" in md
    j, m = write_reports(report, tmp_path)
    assert j.exists() and m.exists()
