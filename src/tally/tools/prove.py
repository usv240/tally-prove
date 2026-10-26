"""The one tool added for the Give your Agent a Tool challenge: prove_answer.

Before this, when a provider asked Tally what the rules say, the model answered from memory, and
memory is where last year's rule lives. Now the draft answer goes to Amazon Bedrock Automated
Reasoning checks, which hold the regulation as formal logic, and comes back proved, contradicted,
or undecided with the fact that would decide it. Every check is kept as a Proof the sponsor can read.

Wiring: the Day agent drafts, calls this, and acts on the verdict; see agents/graph.py DAY. The loop
is the agent's, in the open. This tool only caps it.
"""

from __future__ import annotations

import re
import uuid

from strands import tool

from tally import ledger, prove, runtime
from tally.models import Proof
from tally.numbers import numbers_in

MAX_ATTEMPTS = 3
"""Three proofs per question. After that the honest answer is "I could not verify this"."""


def rt():
    return runtime.get()


def _record(question: str, answer: str, facts: str, checked: prove.Checked, attempt: int,
            meal_id: str | None) -> Proof:
    r = rt()
    p = Proof(
        id=f"proof-{uuid.uuid4().hex[:8]}", provider_id=r.store.get_provider().id, at=r.now(),
        question=question, answer=answer, facts=facts, verdict=checked.verdict,  # type: ignore[arg-type]
        rules=checked.rules, premises=checked.premises, claims=checked.claims,
        untranslated=checked.untranslated, missing_facts=checked.missing_facts,
        policy_version=checked.policy_version, guardrail_version=checked.guardrail_version,
        latency_ms=checked.latency_ms, text_units=checked.text_units, request_id=checked.request_id,
        attempt=attempt, meal_id=meal_id,
    )
    # Filed before it is stored, so a receipt a reviewer is shown is one the ledger already holds.
    if ledger.enabled() and checked.verdict != "SKIPPED":
        p.ledger = ledger.file(p, p.provider_id)
        r.emit("proof_filed", proof_id=p.id, **p.ledger)
    r.store.put_proof(p)
    return p


_STATEMENT = re.compile(r"^\s*([a-z]\w*) is (?:not )?(?:equal to|at least|no more than|greater than|less than"
                        r"|more than|true|false)\s*(.*?)\s*$", re.IGNORECASE)


def turns_on(missing_facts: list[str], given: str = "") -> list[str]:
    """The facts an undecided answer turns on, as names to ask about, never as the solver's values.

    The solver explains SATISFIABLE with a sample case, "yogurtAddedSugarsPer6Ounces is equal to
    12.375". Handed that sentence, the model quoted 12.5 grams as the limit on a proved answer. The
    name is the question to ask her; the number was only one point on the far side of the rule. A
    fact she already gave, by value, is not asked again, and a claim about the answer itself
    ("isYogurtCreditable is false") is not a fact about her plate.
    """
    have = set(numbers_in(given))
    words = given.lower()
    out: list[str] = []
    for statement in missing_facts:
        for part in re.split(r";|\band\b", statement):
            m = _STATEMENT.match(part)
            if not m or (m.group(1)[:2] == "is" and m.group(1)[2:3].isupper()):
                continue
            name, value = m.group(1), m.group(2)
            if value and (set(numbers_in(value)) & have or value.split("_")[-1].lower() in words):
                continue
            human = re.sub(r"(?<=[a-z])(?=[A-Z0-9])|(?<=[0-9])(?=[A-Za-z])", " ", name).lower()
            if " " in human and human not in out:
                out.append(human)
    return out[:2]


def _next_step(p: Proof) -> str:
    """What the agent should do now, in words it can follow. The verdict decides, not the model."""
    if p.verdict == "VALID":
        return "Proved. Say the answer. Mention the rule in a few words if it helps her."
    if p.verdict == "IMPOSSIBLE":
        # The situation she described already breaks a rule (flavored milk for a 4 year old, yogurt
        # in place of milk): the facts cannot all hold under the rulebook, whatever the draft said.
        # The news for her is the rule, and there is nothing to rewrite or re-prove.
        rule = p.rules[0] if p.rules else "the rule quoted"
        return (f"What she described is not allowed. This rule rules it out: {rule}. Tell her so, in "
                f"her words, and stop. Do not call prove_answer again for this question.")
    if p.verdict == "INVALID":
        rule = p.rules[0] if p.rules else "the rule quoted"
        if p.attempt >= MAX_ATTEMPTS:
            return (f"Contradicts the rules and no attempts are left. Tell her you could not verify "
                    f"this and quote the rule: {rule}")
        return (f"Contradicts the rules. Rewrite the answer so it agrees with this rule, then call "
                f"prove_answer again with the rewritten answer: {rule}")
    if p.verdict in ("SATISFIABLE", "AMBIGUOUS"):
        names = turns_on(p.missing_facts, f"{p.question} {p.facts}")
        fact = " and ".join(names) if names else (p.missing_facts[0] if p.missing_facts else "the missing fact")
        if p.attempt >= MAX_ATTEMPTS:
            return f"Still undecided and no attempts are left. Tell her it depends on {fact}."
        return (f"Cannot be decided yet. It turns on {fact}. Ask her one short question about that. "
                f"Any number the checker used to explain this is an example, not a limit: never quote "
                f"it. Then call prove_answer again with her answer in `facts`.")
    if p.verdict == "SKIPPED":
        return "Proving is switched off. Answer as you would have, and say it is unchecked."
    if p.missing_facts and p.attempt < MAX_ATTEMPTS:
        # The checker read one fact two ways, usually because the draft put the rule's number next
        # to her number. Not her problem to settle; the agent restates and proves again.
        return ("Could not be checked: the checker read one fact two ways ("
                + " versus ".join(p.missing_facts[:2]) + "). Keep the limit out of the facts; put what "
                "she said in facts and your decision in the answer, and call prove_answer again.")
    if p.attempt < MAX_ATTEMPTS:
        return ("Could not be checked: the draft did not state a decision the rules speak to. Rewrite "
                "it as one plain statement, whether the food is creditable or the meal is reimbursable, "
                "with the numbers, and call prove_answer again. If it is still unverified, tell her this "
                "is outside the meal pattern rules.")
    return ("Outside the rulebook, so it cannot be proved. Say plainly that this is not in the meal "
            "pattern rules, and answer only if you are sure, labelled as unverified.")


@tool
def prove_answer(question: str, answer: str, facts: str = "", meal_id: str = "") -> dict:
    """Check a draft answer about the food program against the regulation, mathematically.

    Call this before telling her what the rules say about a meal, a food, milk, juice, sugar limits,
    whole grains, snacks, or infants. It does not guess: the answer is proved or contradicted against
    7 CFR 226.20, or it comes back with the one fact that would decide it.

    Args:
        question: her question, word for word.
        answer: your draft answer, as one plain decision with the numbers in it: whether the food is
            creditable or the meal is reimbursable, and why.
        facts: what she has told you, one short sentence each: "The meal is a snack. The children are
            3 to 5. The label says 17 grams of sugar, not stated whether added or total." Keep her
            numbers as she said them. Add to this when she answers your question.
        meal_id: the meal this is about, if there is one, so the receipt attaches to the record.

    Returns the verdict, the rules it rests on, and what to do next.
    """
    r = rt()
    previous = r.store.proofs_for_question(question)
    attempt = len(previous) + 1
    if attempt > MAX_ATTEMPTS:
        r.emit("proof_limit", question=question, attempts=len(previous))
        return {"verdict": "UNVERIFIED", "attempt": attempt,
                "next_step": "No attempts left for this question. Tell her you could not verify it."}

    r.emit("answer_drafted", question=question, answer=answer, facts=facts, attempt=attempt)
    error = ""
    if not prove.enabled():
        checked = prove.Checked(verdict="SKIPPED")
    else:
        try:
            checked = prove.prove(question, answer, facts)
        except Exception as exc:  # the service having a bad minute must not take the agent down
            error = f"{type(exc).__name__}: {str(exc)[:600]}"
            r.emit("proof_error", question=question, error=error)
            checked = prove.Checked(verdict="SKIPPED")
    p = _record(question, answer, facts, checked, attempt, meal_id or None)
    if error:
        # "Switched off" and "could not reach the service" are different news, for her and for
        # whoever reads the trace. The first live deploy reported the second as the first.
        r.emit("answer_proved", proof_id=p.id, verdict=p.verdict, attempt=attempt, error=error)
        return {"proof_id": p.id, "verdict": "SKIPPED", "attempt": attempt, "error": error,
                "attempts_left": MAX_ATTEMPTS - attempt,
                "next_step": "The proof service did not answer, so this could not be checked. Answer "
                             "as you would have, and say it is unchecked."}
    r.emit("answer_proved", proof_id=p.id, verdict=p.verdict, attempt=attempt, rules=p.rules[:2],
           missing_facts=p.missing_facts[:2], latency_ms=p.latency_ms, text_units=p.text_units)
    return {
        "proof_id": p.id,
        "verdict": p.verdict,
        "attempt": attempt,
        "attempts_left": MAX_ATTEMPTS - attempt,
        "rules": p.rules,
        "premises": p.premises,
        "claims": p.claims,
        # Names, not the solver's sample values: the receipt keeps the raw scenario, the model gets
        # what to ask. See turns_on.
        "turns_on": turns_on(p.missing_facts, f"{question} {facts}"),
        "untranslated": p.untranslated,
        "latency_ms": p.latency_ms,
        "next_step": _next_step(p),
    }
