"""Numbers from nowhere.

A rules answer carries numbers: a sugar limit, an age band, an ounce. Each one came from somewhere.
Either the provider said it, or the regulation says it, or the model remembered it, and the third
kind is where last year's rule lives. "17 g is under the 23 g limit" has one number from her and one
from memory, and the one from memory expired in October 2025.

This module names the numbers in an answer that are in neither her words nor the regulation. It is
not a proof, and it is not a model: it is arithmetic over three sets. The agent is told to use only
numbers from a proved rule or from her; this is the check that says whether it did, in code, so
the page can show the number instead of trusting the prompt.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable

from tally.prove import DEFINITION

_NUM = re.compile(r"(?<![\w.:-])(\d+(?:\.\d+)?)(?![\w.:]|-\d)")
"""An integer or decimal standing on its own: not part of a word, an id like policy:7, or a date like
2029-09-07."""


def numbers_in(text: str) -> list[str]:
    """The numbers in a sentence, as written, in order, without repeats. "12.0" and "12" are one."""
    out: list[str] = []
    for m in _NUM.finditer(text or ""):
        n = m.group(1)
        if "." in n:
            n = n.rstrip("0").rstrip(".")
        if len(n) == 4 and n.isdigit() and 1900 <= int(n) <= 2100:
            continue  # a year is a date, not a quantity
        if n not in out:
            out.append(n)
    return out


_RULEBOOK: set[str] | None = None


def rulebook_numbers() -> set[str]:
    """Every number the regulation states, in the rulebook's words and in the formal rules."""
    global _RULEBOOK
    if _RULEBOOK is None:
        found: set[str] = set()
        if DEFINITION.exists():
            d = json.loads(DEFINITION.read_text(encoding="utf-8"))
            for r in d.get("rules", []):
                for text in (r.get("alternateExpression") or "", r.get("expression") or ""):
                    found.update(numbers_in(text))
        _RULEBOOK = found
    return _RULEBOOK


def unsourced(answer: str, her_words: Iterable[str], rulebook: set[str] | None = None) -> list[str]:
    """The numbers in `answer` that appear in neither `her_words` nor the regulation, in order.

    `her_words` is everything the provider said in this conversation. A number from a proved rule is
    in the regulation by construction, so the rulebook set covers it.
    """
    allowed = set(rulebook if rulebook is not None else rulebook_numbers())
    for said in her_words:
        allowed.update(numbers_in(said))
    return [n for n in numbers_in(answer) if n not in allowed]
