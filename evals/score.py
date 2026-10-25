"""Recount every published prove_answer number from the saved results, with no AWS and no model.

A number nobody can rerun is an assertion. The three eval scripts save every verdict and every
agent answer as JSON next to this file; this reads those files and prints the figures that appear
in docs/EVAL.md and on the project page, in a second. If a figure here and a figure on the page
disagree, the page is wrong.

    python -m evals.score
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def load(name: str) -> dict:
    p = Path("evals") / name
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def main() -> int:
    r = load("prove_results.json")
    s = r.get("solver") or {}
    if s:
        rows = s["rows"]
        caught = sum(1 for x in rows if x["wrong"]["verdict"] in ("INVALID", "IMPOSSIBLE"))
        blocked = sum(1 for x in rows if x["correct"]["verdict"] == "INVALID")
        proved = sum(1 for x in rows if x["correct"]["verdict"] == "VALID")
        off = sum(1 for x in s["off_topic"] if x["verdict"] == "VALID")
        lat = sorted(x[k]["latency_ms"] for x in rows for k in ("correct", "wrong"))
        print(f"The tool alone, {len(rows)} questions:")
        print(f"  wrong answers contradicted      {caught} of {len(rows)}")
        print(f"  correct answers wrongly blocked {blocked} of {len(rows)}")
        print(f"  correct answers proved outright {proved} of {len(rows)}")
        print(f"  off-topic answers wrongly proved {off} of {len(s['off_topic'])}")
        print(f"  median check                    {lat[len(lat) // 2] / 1000:.1f} s")
    a = r.get("agents") or {}
    if a:
        print("\nThe same agent three ways (wrong answers served / proved / asked):")
        for cond, name in (("no_tool", "no tool"), ("debate", "two-agent debate"), ("tool", "with prove_answer")):
            vs = [x[cond]["verdict"] for x in a["rows"]]
            wrong = sum(1 for v in vs if v in ("INVALID", "IMPOSSIBLE"))
            proved = sum(1 for v in vs if v == "VALID")
            asked = sum(1 for v in vs if v == "ASKED")
            print(f"  {name:<20} {wrong} / {proved} / {asked}  of {len(vs)}")
        # A number in the answer that is in neither the question nor the regulation came from the
        # model's memory. Counted the same way for every condition, with no model.
        try:
            from tally.numbers import rulebook_numbers, unsourced
        except ModuleNotFoundError:  # a fresh clone, no install: the package is in src/
            sys.path.insert(0, str(Path("src").resolve()))
            from tally.numbers import rulebook_numbers, unsourced

        rb = rulebook_numbers()
        cases = {c["id"]: c for c in
                 json.loads(Path("evals/cases/prove_cases.json").read_text(encoding="utf-8"))["cases"]}
        print("\nAnswers with a number from nowhere (in neither her question nor the regulation):")
        for cond, name in (("plain", "general assistant"), ("no_tool", "no tool"), ("debate", "two-agent debate"),
                           ("tool", "with prove_answer")):
            if cond not in a["rows"][0]:
                continue
            n = sum(1 for x in a["rows"] if unsourced(x[cond]["answer"], [cases[x["id"]]["question"]], rb))
            print(f"  {name:<20} {n} of {len(a['rows'])}")
    adv = load("adversarial_results.json")
    if adv:
        print(f"\nAnswers that try to talk the prover into a proof: {adv['attacks_proved']} of "
              f"{adv['n_attacks']} proved; the control answer came back {adv['control_verdict']}")
    for name, label in (("audit_before_results.json", "Tally's rulebook before the fix"),
                        ("audit_results.json", "Tally's rulebook after the fix")):
        au = load(name)
        if au:
            stale = sum(1 for x in au["rows"] if x["verdict"] in ("INVALID", "IMPOSSIBLE"))
            where = ", ".join(x["where"] for x in au["rows"] if x["verdict"] in ("INVALID", "IMPOSSIBLE"))
            print(f"\n{label}: {stale} of {len(au['rows'])} statements contradicted" + (": " + where if stale else ""))
    h = load("holdout_results.json")
    if h.get("solver"):
        rows = h["solver"]["rows"]
        print(f"\nHeld out, {len(rows)} questions written after the last change:")
        caught = sum(1 for x in rows if x["wrong"] in ("INVALID", "IMPOSSIBLE"))
        print(f"  wrong answers contradicted      {caught} of {len(rows)}")
        print(f"  correct answers wrongly blocked {sum(1 for x in rows if x['correct'] == 'INVALID')} of {len(rows)}")
    if h.get("agent"):
        rows = h["agent"]["rows"]
        rule = [x for x in rows if x["kind"] == "rule"]
        other = [x for x in rows if x["kind"] == "other"]
        print("\nDoes the agent reach for the tool:")
        print(f"  on rule questions     {sum(1 for x in rule if x['called'])} of {len(rule)}")
        print(f"  on everything else    {sum(1 for x in other if x['called'])} of {len(other)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
