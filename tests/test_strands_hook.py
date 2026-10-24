"""The hook form: an agent with no prompt changes gets every answer proved."""

from __future__ import annotations

from types import SimpleNamespace

from strands.hooks import AfterInvocationEvent, HookRegistry

from tally import prove
from tally.strands_hook import ProveAnswers


class Result:
    def __init__(self, text):
        self.text = text

    def __str__(self):
        return self.text


class FakeAgent:
    def __init__(self, question: str):
        self.messages = [{"role": "user", "content": [{"text": question}]},
                         {"role": "assistant", "content": [{"text": "..."}]}]


def test_the_hook_proves_the_answer_and_records_it(monkeypatch):
    monkeypatch.setattr(prove, "prove", lambda q, a, f="", cfg=None, client=None:
                        prove.Checked(verdict="INVALID", rules=["Yogurt must be under 12 g"], latency_ms=5))
    flagged = []
    hook = ProveAnswers(on_invalid=lambda q, a, c: flagged.append((q, a, c.verdict)))
    reg = HookRegistry()
    hook.register_hooks(reg)
    agent = FakeAgent("Can I serve this yogurt?")
    state: dict = {}
    event = AfterInvocationEvent(agent=agent, invocation_state=state,
                                 result=Result("Yes, 17 g is under 23 g."))
    reg.invoke_callbacks(event)
    assert hook.proofs[0]["verdict"] == "INVALID" and hook.proofs[0]["rules"] == ["Yogurt must be under 12 g"]
    assert state["proof"]["question"] == "Can I serve this yogurt?"
    assert flagged == [("Can I serve this yogurt?", "Yes, 17 g is under 23 g.", "INVALID")]


def test_the_hook_stays_quiet_without_a_question(monkeypatch):
    monkeypatch.setattr(prove, "prove", lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not run")))
    hook = ProveAnswers()
    reg = HookRegistry()
    hook.register_hooks(reg)
    event = AfterInvocationEvent(agent=SimpleNamespace(messages=[]), invocation_state={},
                                 result=Result("hi"))
    reg.invoke_callbacks(event)
    assert hook.proofs == []
