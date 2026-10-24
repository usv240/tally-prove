"""The demo service: one provider, one day, driven step by step.

The web app talks to this. Judge mode drives it with no login.
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from tally import runtime
from tally.agentcore.memory import status as memory_status
from tally.models import Child, ComplianceItem, MealType, Provider
from tally.runtime import Runtime
from tally.store import Clock, MemoryStore

SCENARIO = "data/demo_day.json"


def load_scenario(path: str = SCENARIO) -> tuple[MemoryStore, dict]:
    blob = json.loads(Path(path).read_text(encoding="utf-8"))
    store = MemoryStore()
    store.put_provider(Provider.model_validate(blob["provider"]))
    for c in blob["children"]:
        store.put_child(Child.model_validate(c))
    for c in blob.get("compliance", []):
        store.put_compliance(ComplianceItem.model_validate(c))
    for phrase, product in blob.get("vocabulary", {}).items():
        store.learn_food(phrase, product)
    return store, blob


def setup(path: str = SCENARIO) -> tuple[Runtime, dict]:
    store, blob = load_scenario(path)
    rt = Runtime(store=store, clock=Clock(datetime.fromisoformat(blob["clock_start"])))
    return runtime.configure(rt), blob


class DemoService:
    def __init__(self, scenario: str = SCENARIO) -> None:
        self.scenario = scenario
        self.lock = threading.RLock()
        self.reset()

    # lifecycle ---------------------------------------------------------------
    def reset(self) -> dict:
        with self.lock:
            from tally.agents.graph import reset_conversations

            reset_conversations()
            self.rt, self.sc = setup(self.scenario)
            self.done: list[str] = []
            self.meal_ids: dict[str, str] = {}
            self._seed_prior_days()
            return self.state()

    def _seed_prior_days(self) -> None:
        """Six earlier days of the month, so the month view and the claim mean something.

        These are recorded directly rather than run through the agent, because replaying a week of
        vision calls to fill a calendar would cost money and prove nothing. The demo day itself is
        entirely real.
        """
        from tally.engine.rules import load_rules
        from tally.models import Item, Meal, Verdict

        version = load_rules()["version"]
        start = self.rt.now().date() - timedelta(days=self.sc.get("prior_days", 6))
        kids = [c.id for c in self.rt.store.list_children() if c.usual_arrival < "12:00"]
        pattern = [
            (MealType.BREAKFAST, 8, [("milk", "milk"), ("banana", "fruit"), ("oatmeal", "grain")], True),
            (MealType.LUNCH, 12, [("milk", "milk"), ("chicken", "meat_alt"), ("rice", "grain"),
                                  ("green beans", "vegetable"), ("pear", "fruit")], True),
            (MealType.SNACK, 15, [("whole grain crackers", "grain"), ("apple slices", "fruit")], True),
        ]
        n = 0
        for offset in range(self.sc.get("prior_days", 6)):
            day = start + timedelta(days=offset)
            if day.weekday() > 4:
                continue
            for meal_type, hour, foods, ok in pattern:
                # One snack in the earlier week did not qualify, so the month view is honest about
                # what this costs rather than showing a perfect record.
                qualifies = ok and not (offset == 2 and meal_type == MealType.SNACK)
                items = [Item(name=f, component=c, confidence=0.97) for f, c in foods]
                if not qualifies:
                    items = items[:1]
                n += 1
                self.rt.store.put_meal(Meal(
                    id=f"seed-{n:03d}", provider_id="rosa",
                    at=datetime.combine(day, datetime.min.time()).replace(hour=hour),
                    meal_type=meal_type, items=items, children_served=kids,
                    verdict=Verdict(reimbursable=qualifies, rule_version=version,
                                    explanation="recorded on an earlier day"),
                ))

    # driving -----------------------------------------------------------------
    def step(self, step_id: str | None = None) -> dict:
        with self.lock:
            steps = self.sc["steps"]
            remaining = [s for s in steps if s["id"] not in self.done]
            if step_id:
                target = next((s for s in steps if s["id"] == step_id), None)
            else:
                target = remaining[0] if remaining else None
            if target is None:
                return {"ran": None, **self.state()}

            self.rt.clock.set(datetime.fromisoformat(target["at"]))
            runtime.configure(self.rt)
            self._run(target)
            if target["id"] not in self.done:
                self.done.append(target["id"])
            return {"ran": target["id"], **self.state()}

    def _run(self, step: dict[str, Any]) -> None:
        from tally.agents.graph import run_evening
        from tally.tools.day import log_plate, take_roll

        kind = step["kind"]
        if kind == "roll":
            take_roll(step["text"])
        elif kind == "plate":
            replaces = self.meal_ids.get(step.get("replaces", ""), "")
            out = log_plate(step["photo"], step.get("meal_type", ""), replaces)
            self.meal_ids[step["id"]] = out["meal_id"]
        elif kind == "evening":
            run_evening()

    def answer(self, question_id: str, answer: str) -> dict:
        with self.lock:
            runtime.configure(self.rt)
            from tally.tools.day import answer_open_question

            answer_open_question(question_id, answer)
            return self.state()

    def ask(self, text: str, prove: bool | None = None) -> dict:
        """One question to the Day agent. `prove=False` is the agent as it was before the tool."""
        with self.lock:
            runtime.configure(self.rt)
            from tally.agents.graph import ask

            out = ask(text, with_prove=prove)
            return {"ask": out, **self.state()}

    def prove(self, question: str, answer: str, facts: str = "", meal_id: str = "") -> dict:
        """Prove one answer directly, for the public API and the MCP server. Same tool, no agent."""
        with self.lock:
            runtime.configure(self.rt)
            from tally.tools.prove import prove_answer

            out = prove_answer(question, answer, facts, meal_id)
            p = next((x for x in self.rt.store.list_proofs() if x.id == out.get("proof_id")), None)
            return {**out, "proof": self.proof_json(p) if p else None}

    def substitute(self, meal_id: str, child_id: str, food: str, component: str) -> dict:
        with self.lock:
            runtime.configure(self.rt)
            from tally.tools.day import record_substitution

            record_substitution(meal_id, child_id, food, component)
            return self.state()

    # reads -------------------------------------------------------------------
    def state(self) -> dict:
        r = self.rt
        now = r.now()
        on = now.date()
        p = r.store.get_provider()
        superseded = r.store.superseded_ids()
        meals = [m for m in r.store.list_meals(on) if m.id not in superseded]
        questions = r.store.list_questions()
        safety = [q for q in questions if q.priority == "safety"]

        ok = sum(1 for m in meals if m.verdict and m.verdict.reimbursable)
        bad = [m for m in meals if m.verdict and not m.verdict.reimbursable]
        present = sorted(r.store.present_ids(on))

        # An unanswered allergy alert takes the line while it is fresh. It must not sit there for
        # the rest of the day, or the provider stops reading the line at all.
        fresh = [q for q in safety if not q.answered and (now - q.at) <= timedelta(minutes=30)]
        latest_bad = bad[-1] if bad else None
        if fresh:
            headline, tone = fresh[0].text, "alert"
        elif latest_bad is not None and meals and meals[-1].id == latest_bad.id:
            headline = latest_bad.verdict.smallest_fix or latest_bad.verdict.explanation
            tone = "fix"
        elif meals and not bad:
            headline = (f"Today: {len(meals)} meal" + ("s" if len(meals) != 1 else "")
                        + f" logged, all qualify. {len(present)} here.")
            tone = "ok"
        elif meals:
            headline = (f"Today: {len(meals)} logged, {len(bad)} will not be paid. "
                        f"{len(present)} here.")
            tone = "fix"
        else:
            headline = f"{len(present)} here. Nothing logged yet."
            tone = "ok"

        return {
            "now": now.isoformat(),
            "provider": {"id": p.id, "name": p.name, "state": p.state,
                         "license_type": p.license_type, "tier": p.tier,
                         "sponsor": p.sponsor_name, "question_budget": p.question_budget},
            "headline": headline,
            "tone": tone,
            "spoken": r.spoken[-6:],
            "steps": [{"id": s["id"], "title": s["title"], "detail": s["detail"],
                       "done": s["id"] in self.done} for s in self.sc["steps"]],
            "children": [{"id": c.id, "name": c.first_name, "age_group": c.age_group(on).value,
                          "allergies": c.allergies, "subsidized": c.subsidized,
                          "language": c.family_language,
                          "present": c.id in r.store.present_ids(on),
                          "absent": c.id in r.store.absent_ids(on)}
                         for c in r.store.list_children()],
            "ratio": self.ratio(),
            "meals": [self.meal_json(m) for m in meals],
            "proofs": [self.proof_json(p) for p in r.store.list_proofs(on)],
            "questions": [{"id": q.id, "text": q.text, "options": q.options,
                           "priority": q.priority, "answered": q.answered} for q in questions],
            "asked_today": r.store.questions_asked_today(on),
            # Questions the gate did not spend, because she settled the same thing before. Read off
            # the trace rather than recomputed, so the page cannot claim a recall that never ran.
            "not_repeated": [{"child": r.store.get_child(e["child_id"]).first_name,
                              "answer": e.get("answer", ""), "days_ago": e.get("days_ago", 0),
                              "source": e.get("source", "")}
                             for e in r.trace if e["kind"] == "question_not_repeated"],
            "memory": memory_status(r.store.get_provider().id),
            "notes": [{"child_id": n.child_id,
                       "name": r.store.get_child(n.child_id).first_name,
                       "text": n.text, "language": n.language}
                      for n in r.store.list_notes(on)],
            "compliance": [{"id": c.id, "label": c.label, "due": c.due.isoformat(),
                            "status": c.status} for c in r.store.list_compliance()],
            "month": self.month(),
            "counts": {"logged": len(meals), "qualifying": ok, "not_reimbursable": len(bad)},
        }

    def ratio(self) -> dict:
        r = self.rt
        now = r.now()
        p = r.store.get_provider()
        from tally.engine.ratio import check_ratio

        try:
            return check_ratio(r.store.present_ids(now.date()), r.store.list_children(),
                               p.state, p.license_type, now,
                               absent_ids=r.store.absent_ids(now.date())).model_dump(mode="json")
        except KeyError as exc:
            return {"error": str(exc)}

    def meal_json(self, m) -> dict:
        v = m.verdict
        return {
            "id": m.id, "at": m.at.isoformat(), "type": m.meal_type.value,
            "photo": m.photo_key, "replaces": m.replaces,
            "items": [{"name": i.name, "component": i.component.value, "confidence": i.confidence}
                      for i in m.items],
            "children_served": m.children_served,
            "substitutions": {cid: [{"name": i.name, "component": i.component.value} for i in items]
                              for cid, items in m.substitutions.items()},
            "reimbursable": bool(v and v.reimbursable),
            "explanation": v.explanation if v else "",
            "smallest_fix": v.smallest_fix if v else "",
            "missing": [x.value for x in v.missing] if v else [],
            "flags": v.flags if v else [],
            "label_checks": v.label_checks if v else [],
            "rule_version": v.rule_version if v else "",
            "proofs": [self.proof_json(p) for p in self.rt.store.list_proofs(meal_id=m.id)],
        }

    def proof_json(self, p) -> dict:
        """A proof as the page and the sponsor see it: the verdict, the rule, the facts, the version."""
        return {
            "id": p.id, "at": p.at.isoformat(), "question": p.question, "answer": p.answer,
            "facts": p.facts, "verdict": p.verdict, "rules": p.rules, "premises": p.premises,
            "claims": p.claims, "missing_facts": p.missing_facts, "untranslated": p.untranslated,
            "policy_version": p.policy_version, "guardrail_version": p.guardrail_version,
            "latency_ms": p.latency_ms, "text_units": p.text_units, "attempt": p.attempt,
            "meal_id": p.meal_id, "ledger": p.ledger, "stakes": self.stakes(p),
        }

    def stakes(self, p) -> dict | None:
        return stakes_for(self.rt, p)


    def month(self) -> dict:
        r = self.rt
        month = r.now().strftime("%Y-%m")
        claim = r.store.get_claim(month)
        if claim is None:
            runtime.configure(r)
            from tally.tools.nightly import build_month_claim

            return build_month_claim(month)
        return claim.model_dump(mode="json")

    def sponsor_month(self, month: str | None = None) -> dict:
        """A month as a sponsor sees it: every meal, its photograph, its verdict, its rule version."""
        r = self.rt
        month = month or r.now().strftime("%Y-%m")
        p = r.store.get_provider()
        superseded = r.store.superseded_ids()
        meals = [m for m in r.store.list_meals()
                 if m.at.strftime("%Y-%m") == month and m.id not in superseded]
        by_day: dict[str, list] = {}
        for m in sorted(meals, key=lambda x: x.at):
            by_day.setdefault(m.at.date().isoformat(), []).append(self.meal_json(m))
        questions = list(r.store.list_questions(unanswered_only=False))
        return {
            "month": month,
            "provider": {"name": p.name, "state": p.state, "license_type": p.license_type,
                         "tier": p.tier, "sponsor": p.sponsor_name},
            "claim": self.month(),
            "days": [{"date": d, "meals": ms} for d, ms in sorted(by_day.items())],
            "totals": {
                "meals": len(meals),
                "reimbursable": sum(1 for m in meals if m.verdict and m.verdict.reimbursable),
                "not_reimbursable": sum(1 for m in meals
                                        if m.verdict and not m.verdict.reimbursable),
                "photographed": sum(1 for m in meals if m.photo_key),
                "questions_asked": len(questions),
            },
            "rule_versions": sorted({m.verdict.rule_version for m in meals
                                     if m.verdict and m.verdict.rule_version}),
        }

    def trace(self, since: int = 0) -> dict:
        return {"events": self.rt.trace[since:], "next": len(self.rt.trace)}


def stakes_for(rt, p) -> dict | None:
    """What following a contradicted answer would cost this home in a month, from the claim engine.

    A disallowed meal is the whole meal, not the one food: the snack with the wrong yogurt is not
    paid at all. So the figure is the meal's rate, for every child on the roster, for a month of
    serving days, at this provider's tier. Same arithmetic and same rates as the claim.
    """
    if p.verdict not in ("INVALID", "IMPOSSIBLE"):
        return None
    from tally.engine.claim import lost_value, rate_for

    text = f"{p.question} {p.facts}".lower()
    meal = next((m for m in (MealType.BREAKFAST, MealType.LUNCH, MealType.SUPPER, MealType.SNACK)
                 if m.value in text), None)
    if meal is None:
        return None
    prov = rt.store.get_provider()
    children = len(rt.store.list_children())
    days = 22
    return {"meal": meal.value, "children": children, "serving_days": days, "tier": prov.tier,
            "rate": rate_for(meal, prov.tier), "month": lost_value([(meal, children * days)], prov.tier)}


class _Lazy:
    """Built on first use, so importing the API does not load a scenario."""

    _instance: DemoService | None = None

    def _get(self) -> DemoService:
        if _Lazy._instance is None:
            _Lazy._instance = DemoService()
        return _Lazy._instance

    def __getattr__(self, name: str) -> Any:
        return getattr(self._get(), name)


service = _Lazy()
