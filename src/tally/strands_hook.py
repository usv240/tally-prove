"""prove_answer as a Strands hook: one line, and every answer your agent gives is proved.

    from tally.strands_hook import ProveAnswers
    agent = Agent(tools=[...], hooks=[ProveAnswers()])

No prompt changes, no tool call for the model to remember to make. After each invocation the hook
takes the question the user asked and the answer the agent produced, proves the answer against the
guardrail, and records the verdict in the invocation state and in `hook.proofs`. Your code decides
what to do with INVALID: show the rule, ask again, refuse to send. The hook never alters the answer
itself, because a hook that silently rewrote what the model said would be the thing this project
exists to prevent.

The Day agent in Tally uses the tool form instead, so the model can act on the verdict mid-turn
(rewrite, ask for the missing fact). The hook form is for agents you do not control the prompt of.
"""

from __future__ import annotations

from collections.abc import Callable

from strands.hooks import AfterInvocationEvent, HookProvider, HookRegistry

from tally import prove


class ProveAnswers(HookProvider):
    def __init__(self, on_invalid: Callable[[str, str, prove.Checked], None] | None = None,
                 facts: str = "", cfg: dict | None = None) -> None:
        self.on_invalid = on_invalid
        self.facts = facts
        self.cfg = cfg
        self.proofs: list[dict] = []

    def register_hooks(self, registry: HookRegistry, **kwargs) -> None:
        registry.add_callback(AfterInvocationEvent, self.after_invocation)

    def after_invocation(self, event: AfterInvocationEvent) -> None:
        question = _last_user_text(event.agent)
        answer = str(event.result).strip() if event.result is not None else ""
        if not question or not answer:
            return
        checked = prove.prove(question, answer, self.facts, cfg=self.cfg)
        record = {"question": question, "answer": answer, "verdict": checked.verdict,
                  "rules": checked.rules, "missing_facts": checked.missing_facts,
                  "latency_ms": checked.latency_ms}
        self.proofs.append(record)
        event.invocation_state["proof"] = record
        if checked.verdict in ("INVALID", "IMPOSSIBLE") and self.on_invalid:
            self.on_invalid(question, answer, checked)


def _last_user_text(agent) -> str:
    for m in reversed(getattr(agent, "messages", []) or []):
        if m.get("role") == "user":
            return " ".join(b.get("text", "") for b in m.get("content", []) if isinstance(b, dict)).strip()
    return ""
