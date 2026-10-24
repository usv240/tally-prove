"""prove_answer as a tool: it records, it caps, it switches off, and the API reaches it."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from tally import prove, runtime
from tally.service import setup
from tally.tools.prove import MAX_ATTEMPTS, prove_answer

Q = "Can I serve yogurt with 17 g of added sugars per 6 oz as the meat alternate at snack?"


@pytest.fixture
def rt():
    rt, _ = setup()
    runtime.configure(rt)
    return rt


def fake(verdict, **kw):
    def _prove(question, answer, facts="", client=None, cfg=None):
        return prove.Checked(verdict=verdict, latency_ms=12, text_units=3, **kw)
    return _prove


def test_invalid_is_recorded_and_tells_the_agent_to_rewrite(rt, monkeypatch):
    monkeypatch.setenv("TALLY_PROVE", "on")
    monkeypatch.setattr(prove, "prove", fake("INVALID", rules=["Yogurt must contain no more than 12 g"]))
    out = prove_answer(Q, "Yes, 17 g is under the 23 g limit.")
    assert out["verdict"] == "INVALID" and out["attempt"] == 1 and out["attempts_left"] == 2
    assert "Rewrite" in out["next_step"] and "12 g" in out["next_step"]
    proofs = rt.store.list_proofs()
    assert len(proofs) == 1 and proofs[0].verdict == "INVALID" and proofs[0].latency_ms == 12
    kinds = [e["kind"] for e in rt.trace]
    assert kinds[-2:] == ["answer_drafted", "answer_proved"]


def test_satisfiable_asks_for_the_missing_fact(rt, monkeypatch):
    monkeypatch.setenv("TALLY_PROVE", "on")
    monkeypatch.setattr(prove, "prove", fake("SATISFIABLE", missing_facts=["added sugars exceed 12 g"]))
    out = prove_answer("Can I serve yogurt as the meat alternate?", "Yes.")
    assert out["verdict"] == "SATISFIABLE"
    assert "Ask her" in out["next_step"] and "added sugars exceed 12 g" in out["next_step"]


def test_impossible_tells_her_the_rule_and_stops(rt, monkeypatch):
    """Flavored milk for a 4 year old: the situation breaks the rule, so there is nothing to rewrite."""
    monkeypatch.setenv("TALLY_PROVE", "on")
    monkeypatch.setattr(prove, "prove", fake("IMPOSSIBLE", rules=["Flavored milk is not allowed for 1 to 5"]))
    out = prove_answer("Can the 4 year olds have chocolate milk?", "Yes, that is fine.")
    assert out["verdict"] == "IMPOSSIBLE"
    assert "not allowed" in out["next_step"] and "Do not call prove_answer again" in out["next_step"]


def test_the_loop_is_capped(rt, monkeypatch):
    monkeypatch.setenv("TALLY_PROVE", "on")
    calls = []

    def counting(question, answer, facts="", client=None, cfg=None):
        calls.append(answer)
        return prove.Checked(verdict="INVALID", rules=["r"])
    monkeypatch.setattr(prove, "prove", counting)
    for i in range(MAX_ATTEMPTS):
        out = prove_answer(Q, f"draft {i}")
    assert out["attempts_left"] == 0 and "could not verify" in out["next_step"]
    out = prove_answer(Q, "draft again")
    assert out["verdict"] == "UNVERIFIED" and len(calls) == MAX_ATTEMPTS
    assert rt.trace[-1]["kind"] == "proof_limit"


def test_switched_off_is_skipped_and_never_calls_aws(rt, monkeypatch):
    monkeypatch.setenv("TALLY_PROVE", "off")

    def boom(*a, **k):
        raise AssertionError("must not be called")
    monkeypatch.setattr(prove, "prove", boom)
    out = prove_answer(Q, "Yes.")
    assert out["verdict"] == "SKIPPED" and "switched off" in out["next_step"]
    assert rt.store.list_proofs()[0].verdict == "SKIPPED"


def test_a_service_error_degrades_to_skipped(rt, monkeypatch):
    monkeypatch.setenv("TALLY_PROVE", "on")

    def boom(*a, **k):
        raise RuntimeError("throttled")
    monkeypatch.setattr(prove, "prove", boom)
    out = prove_answer(Q, "Yes.")
    assert out["verdict"] == "SKIPPED"
    assert any(e["kind"] == "proof_error" for e in rt.trace)


def test_receipt_attaches_to_a_meal(rt, monkeypatch):
    monkeypatch.setenv("TALLY_PROVE", "on")
    monkeypatch.setattr(prove, "prove", fake("VALID", rules=["ok"]))
    prove_answer(Q, "Yes.", meal_id="seed-001")
    assert rt.store.list_proofs(meal_id="seed-001")[0].verdict == "VALID"


def test_a_contradicted_answer_carries_what_it_would_cost(rt, monkeypatch):
    monkeypatch.setenv("TALLY_PROVE", "on")
    monkeypatch.setattr(prove, "prove", fake("INVALID", rules=["r"]))
    from tally.service import stakes_for

    prove_answer(Q, "Yes, 17 g is under the 23 g limit.", "The meal is a snack.")
    s = stakes_for(rt, rt.store.list_proofs()[0])
    assert s["meal"] == "snack" and s["children"] == 9
    assert s["month"] == 194.04 and s["rate"] == 0.98
    monkeypatch.setattr(prove, "prove", fake("VALID", rules=["r"]))
    prove_answer("Q2?", "Yes.", "The meal is lunch.")
    assert stakes_for(rt, rt.store.list_proofs()[1]) is None


def test_api_prove_endpoint(monkeypatch):
    monkeypatch.setenv("TALLY_PROVE", "on")
    monkeypatch.setattr(prove, "prove", fake("INVALID", rules=["Yogurt must contain no more than 12 g"]))
    from tally.api import app

    c = TestClient(app)
    r = c.post("/api/prove", json={"question": Q, "answer": "Yes, 17 g is fine."})
    assert r.status_code == 200
    body = r.json()
    assert body["verdict"] == "INVALID" and body["proof"]["rules"][0].startswith("Yogurt")
    assert c.post("/api/prove", json={"question": Q}).status_code == 400
    assert c.post("/api/prove", json={"question": Q, "answer": "x"},
                  headers={"x-api-key": "not-a-key"}).status_code == 401
    state = c.get("/api/state").json()
    assert any(p["verdict"] == "INVALID" for p in state["proofs"])
