"""Conversations, history-aware follow-ups, feedback, suggestions, dashboard and analytics."""
from sqlalchemy import func, select

from app.db.session import SessionLocal
from app.models import Conversation, Message
from app.services.llm import set_llm
from app.services.rag.prompt import FALLBACK_MESSAGE
from tests.conftest import auth_headers, make_user
from tests.fixtures import ScriptedLLM, grounded_echo
from tests.test_rag import corpus  # noqa: F401  (fixture)

API = "/api/v1"
SICK_Q = "How many days of paid sick leave do employees receive?"


def ask(client, headers, question, conversation_id=None, **extra):
    body = {"question": question, **extra}
    if conversation_id:
        body["conversation_id"] = str(conversation_id)
    r = client.post(f"{API}/chat/ask", headers=headers, json=body)
    assert r.status_code == 200, r.text
    return r.json()


def test_ask_creates_conversation_and_persists_both_messages(client, employee_headers, corpus):
    res = ask(client, employee_headers, SICK_Q)
    assert res["conversation_title"] == SICK_Q
    am = res["assistant_message"]
    assert am["role"] == "assistant" and am["grounded"] and am["citations"][0]["page"] == 3
    assert am["citations"][0]["available"] and am["confidence_label"] in {"high", "medium", "low"}

    detail = client.get(f"{API}/chat/conversations/{res['conversation_id']}", headers=employee_headers).json()
    assert [m["role"] for m in detail["messages"]] == ["user", "assistant"]
    assert detail["messages"][1]["citations"][0]["title"] == "Leave Policy"


def test_follow_up_uses_stored_history(client, employee_headers, corpus):
    seen = {}

    def responder(messages):
        if "standalone question" in messages[0].content.lower():
            seen["history"] = messages[-1].content
            return "Is a medical certificate required for sick leave?"
        return grounded_echo(messages)

    first = ask(client, employee_headers, SICK_Q)
    set_llm(ScriptedLLM(responder=responder))
    follow = ask(client, employee_headers, "Do I need a certificate for that?", first["conversation_id"])
    assert "sick leave" in seen["history"].lower()          # history came from the database
    assert follow["conversation_id"] == first["conversation_id"]
    assert "medical certificate" in follow["assistant_message"]["content"].lower()
    convs = client.get(f"{API}/chat/conversations", headers=employee_headers).json()
    assert len(convs) == 1 and convs[0]["message_count"] == 4


def test_conversations_are_private(client, employee_headers, corpus):
    res = ask(client, employee_headers, SICK_Q)
    make_user("other@corp.test")
    other = auth_headers(client, "other@corp.test")
    cid, mid = res["conversation_id"], res["assistant_message"]["id"]
    assert client.get(f"{API}/chat/conversations/{cid}", headers=other).status_code == 404
    assert client.post(f"{API}/chat/ask", headers=other, json={"question": SICK_Q, "conversation_id": cid}).status_code == 404
    assert client.delete(f"{API}/chat/conversations/{cid}", headers=other).status_code == 404
    assert client.put(f"{API}/chat/messages/{mid}/feedback", headers=other, json={"rating": -1}).status_code == 404
    assert client.get(f"{API}/chat/conversations", headers=other).json() == []


def test_llm_failure_saves_nothing(client, employee_headers, corpus):
    def boom(messages):
        raise RuntimeError("provider down")
    set_llm(ScriptedLLM(responder=boom))
    r = client.post(f"{API}/chat/ask", headers=employee_headers, json={"question": SICK_Q})
    assert r.status_code == 503
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(Conversation)) == 0
        assert db.scalar(select(func.count()).select_from(Message)) == 0


def test_fallback_answers_are_stored_and_marked(client, employee_headers, corpus):
    res = ask(client, employee_headers, "What is the dress code for the quarterly gala dinner?")
    am = res["assistant_message"]
    assert am["content"] == FALLBACK_MESSAGE and am["grounded"] is False and am["citations"] == []


def test_rename_search_clear_delete(client, employee_headers, corpus):
    a = ask(client, employee_headers, SICK_Q)
    ask(client, employee_headers, "Which class is required for flights under 6 hours?")
    cid = a["conversation_id"]
    r = client.patch(f"{API}/chat/conversations/{cid}", headers=employee_headers, json={"title": "Sick leave"})
    assert r.json()["title"] == "Sick leave"
    found = client.get(f"{API}/chat/conversations", headers=employee_headers, params={"q": "economy"}).json()
    assert len(found) == 1 and found[0]["id"] != cid  # matched by message content
    assert client.post(f"{API}/chat/conversations/{cid}/clear", headers=employee_headers).status_code == 204
    assert client.get(f"{API}/chat/conversations/{cid}", headers=employee_headers).json()["messages"] == []
    assert client.delete(f"{API}/chat/conversations/{cid}", headers=employee_headers).status_code == 204
    assert len(client.get(f"{API}/chat/conversations", headers=employee_headers).json()) == 1


def test_feedback_upsert_rules_and_visibility(client, employee_headers, corpus):
    res = ask(client, employee_headers, SICK_Q)
    am, um = res["assistant_message"]["id"], res["user_message"]["id"]
    url = f"{API}/chat/messages/{am}/feedback"
    assert client.put(url, headers=employee_headers, json={"rating": 1}).json()["rating"] == 1
    r = client.put(url, headers=employee_headers, json={"rating": -1, "comment": "Missed the certificate rule"})
    assert r.json()["rating"] == -1
    assert client.put(f"{API}/chat/messages/{um}/feedback", headers=employee_headers, json={"rating": 1}).status_code == 400
    assert client.put(url, headers=employee_headers, json={"rating": 5}).status_code == 422
    msgs = client.get(f"{API}/chat/conversations/{res['conversation_id']}", headers=employee_headers).json()["messages"]
    assert msgs[1]["feedback"] == -1
    assert client.delete(url, headers=employee_headers).status_code == 204
    msgs = client.get(f"{API}/chat/conversations/{res['conversation_id']}", headers=employee_headers).json()["messages"]
    assert msgs[1]["feedback"] is None


def test_citations_hidden_after_document_deleted_or_access_lost(client, admin_headers, hr_headers, corpus):
    res = ask(client, hr_headers, "What is the Grade L3 salary band?")
    cid = res["conversation_id"]
    assert res["assistant_message"]["citations"][0]["available"]
    # Admin removes HR's access to HR Confidential
    client.put(f"{API}/admin/categories/{corpus['conf_cat']}/roles", headers=admin_headers, json={"roles": []})
    c = client.get(f"{API}/chat/conversations/{cid}", headers=hr_headers).json()["messages"][1]["citations"][0]
    assert c["available"] is False and c["snippet"] == ""
    # And a document that's deleted
    res2 = ask(client, hr_headers, SICK_Q)
    client.delete(f"{API}/documents/{corpus['Leave Policy']}", headers=admin_headers)
    c2 = client.get(f"{API}/chat/conversations/{res2['conversation_id']}", headers=hr_headers).json()["messages"][1]["citations"][0]
    assert c2["available"] is False


def test_suggestions_only_from_accessible_documents(client, employee_headers, hr_headers, corpus):
    emp = client.get(f"{API}/chat/suggestions", headers=employee_headers).json()
    hr = client.get(f"{API}/chat/suggestions", headers=hr_headers).json()
    assert emp and not any("Salary" in s for s in emp)
    assert any("Salary" in s for s in hr)
    assert any("Leave Policy" in s for s in emp)


def test_user_dashboard_stats(client, employee_headers, corpus):
    ask(client, employee_headers, SICK_Q)
    s = client.get(f"{API}/dashboard/stats", headers=employee_headers).json()
    assert s["accessible_documents"] == 2                      # leave + travel; not salary bands
    assert s["my_questions"] == 1 and s["my_conversations"] == 1
    assert {c["name"] for c in s["categories"]} == {"General", "HR Policies", "IT & Security", "Finance & Expenses"}
    assert len(s["recent_documents"]) == 2


def test_admin_analytics_and_feedback_review(client, admin_headers, employee_headers, corpus):
    good = ask(client, employee_headers, SICK_Q)
    ask(client, employee_headers, "What is the dress code for the quarterly gala dinner?")
    ask(client, employee_headers, "hello")
    client.put(f"{API}/chat/messages/{good['assistant_message']['id']}/feedback", headers=employee_headers,
               json={"rating": -1, "comment": "Too short"})

    a = client.get(f"{API}/admin/analytics", headers=admin_headers).json()
    assert a["questions"]["answered"] == 2                     # small talk excluded
    assert a["questions"]["not_found_rate"] == 0.5
    assert a["feedback"] == {"positive": 0, "negative": 1, "satisfaction": 0.0}
    assert a["top_cited_documents"][0]["title"] == "Leave Policy"
    assert a["documents"]["versions_by_status"]["ready"] == 3
    assert a["latency_ms"]["avg"] is not None
    assert sum(d["count"] for d in a["questions"]["per_day"]) == 3

    fb = client.get(f"{API}/admin/feedback", headers=admin_headers, params={"rating": -1}).json()
    assert fb[0]["question"] == SICK_Q and fb[0]["comment"] == "Too short"
    assert fb[0]["cited_documents"] == ["Leave Policy"]
    assert client.get(f"{API}/admin/analytics", headers=employee_headers).status_code == 403


def test_message_order_is_strict(client, employee_headers, corpus):
    res = ask(client, employee_headers, SICK_Q)
    ask(client, employee_headers, "Which class is required for flights under 6 hours?", res["conversation_id"])
    msgs = client.get(f"{API}/chat/conversations/{res['conversation_id']}", headers=employee_headers).json()["messages"]
    assert [m["role"] for m in msgs] == ["user", "assistant", "user", "assistant"]
    times = [m["created_at"] for m in msgs]
    assert times == sorted(times) and len(set(times)) == 4
