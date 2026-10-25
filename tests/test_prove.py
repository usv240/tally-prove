"""prove.interpret() against every finding kind the API can return, with no AWS in the loop."""

from __future__ import annotations

import pytest

from tally import prove

DEFINITION = {"rules": [
    {"id": "R_Y3", "expression": "(=> isYogurtCreditable (<= yogurtAddedSugarsPer6Ounces 12))",
     "alternateExpression": "Yogurt must contain no more than 12 grams of added sugars per 6 ounces."},
    {"id": "R_S3", "expression": "(=> (and snackHasFluidMilk snackHasJuice snackOnlyItemsAreMilkAndJuice) (not isMealReimbursable))",
     "alternateExpression": "A snack of fluid milk and fruit juice is not reimbursable."},
    {"id": "R_M6", "expression": "(=> (>= childAgeYears 6) milkMayBeFlavored)",
     "alternateExpression": "Children who are 6 and older may be served flavored milk."},
]}


def response(*findings, units=1):
    return {"usage": {"automatedReasoningPolicyUnits": units},
            "assessments": [{"automatedReasoningPolicy": {"findings": list(findings)}}]}


def translation(premises=(), claims=(), untranslated=()):
    return {"premises": [{"naturalLanguage": p} for p in premises],
            "claims": [{"naturalLanguage": c} for c in claims],
            "untranslatedClaims": [{"text": u} for u in untranslated]}


def test_valid_quotes_the_supporting_rule_in_words():
    r = response({"valid": {"translation": translation(["added sugars is 9"], ["yogurt is creditable"]),
                            "supportingRules": [{"identifier": "R_Y3", "policyVersionArn": "arn:p:1"}]}})
    c = prove.interpret(r, DEFINITION)
    assert c.verdict == "VALID"
    assert c.rules == ["Yogurt must contain no more than 12 grams of added sugars per 6 ounces."]
    assert c.premises == ["added sugars is 9"] and c.claims == ["yogurt is creditable"]
    assert c.policy_version == "arn:p:1"


def test_invalid_names_the_rule_it_breaks():
    r = response({"invalid": {"translation": translation(["added sugars is 17"], ["yogurt is creditable"]),
                              "contradictingRules": [{"identifier": "R_Y3"}]}})
    c = prove.interpret(r, DEFINITION)
    assert c.verdict == "INVALID"
    assert "12 grams" in c.rules[0]
    assert c.summary().startswith("Contradicts")


def test_satisfiable_returns_the_fact_that_would_decide_it():
    r = response({"satisfiable": {
        "translation": translation(claims=["yogurt is creditable"]),
        "claimsTrueScenario": {"statements": [{"naturalLanguage": "added sugars is at most 12"}]},
        "claimsFalseScenario": {"statements": [{"naturalLanguage": "added sugars is more than 12"}]}}})
    c = prove.interpret(r, DEFINITION)
    assert c.verdict == "SATISFIABLE"
    assert c.missing_facts == ["added sugars is more than 12"]
    assert "turns on" in c.summary()


def test_ambiguous_returns_how_the_readings_differ():
    r = response({"translationAmbiguous": {
        "options": [{"translations": [{"claims": [{"naturalLanguage": "milk is flavored"}]}]},
                    {"translations": [{"claims": [{"naturalLanguage": "milk is unflavored"}]}]}],
        "differenceScenarios": [{"statements": [{"naturalLanguage": "the milk is flavored"}]}]}})
    c = prove.interpret(r, DEFINITION)
    assert c.verdict == "AMBIGUOUS"
    assert c.missing_facts == ["the milk is flavored"]
    assert set(c.claims) == {"milk is flavored", "milk is unflavored"}


@pytest.mark.parametrize("kind,verdict", [("impossible", "IMPOSSIBLE"), ("tooComplex", "UNVERIFIED"),
                                          ("noTranslations", "UNVERIFIED")])
def test_the_other_kinds(kind, verdict):
    c = prove.interpret(response({kind: {}}), DEFINITION)
    assert c.verdict == verdict


def test_worst_finding_wins_and_only_its_rules_are_quoted():
    r = response({"valid": {"translation": translation(claims=["true"]),
                            "supportingRules": [{"identifier": "R_Y3"}, {"identifier": "R_S3"}]}},
                 {"invalid": {"translation": translation(claims=["isYogurtCreditable is true"]),
                              "contradictingRules": [{"identifier": "R_Y3"}]}})
    c = prove.interpret(r, DEFINITION)
    assert c.verdict == "INVALID"
    assert c.rules == ["Yogurt must contain no more than 12 grams of added sugars per 6 ounces."]


def test_a_trivial_valid_finding_does_not_quote_the_whole_policy():
    r = response({"valid": {"translation": translation(claims=["true"]),
                            "supportingRules": [{"identifier": "R_Y3"}, {"identifier": "R_S3"}]}},
                 {"valid": {"translation": translation(claims=["isYogurtCreditable is true"]),
                            "supportingRules": [{"identifier": "R_Y3"}]}})
    c = prove.interpret(r, DEFINITION)
    assert c.verdict == "VALID" and c.rules == ["Yogurt must contain no more than 12 grams of added sugars per 6 ounces."]


def test_zero_units_means_the_check_did_not_run():
    """A guardrail call that silently skipped Automated Reasoning must never read as VALID."""
    r = response({"valid": {}}, units=0)
    assert prove.interpret(r, DEFINITION).verdict == "SKIPPED"
    assert prove.interpret({"assessments": []}, DEFINITION).verdict == "SKIPPED"


def test_a_vacuous_valid_is_unverified_not_proved():
    """Off-topic answer: nothing translated, the solver proved `true`. That must not read as VALID."""
    r = response({"valid": {"translation": translation(claims=["true"], untranslated=["the ratio is 1:4"]),
                            "supportingRules": []}})
    c = prove.interpret(r, DEFINITION)
    assert c.verdict == "UNVERIFIED" and c.untranslated == ["the ratio is 1:4"]
    r2 = response({"valid": {"translation": translation(claims=["true", "isYogurtCreditable is true"]),
                             "supportingRules": [{"identifier": "R_Y3"}]}})
    assert prove.interpret(r2, DEFINITION).verdict == "VALID"


def test_an_impossible_from_two_values_for_one_fact_is_unverified_not_a_broken_rule():
    """The translator read the 12 g limit as a second value for a yogurt said to have 17 g."""
    r = response({"impossible": {
        "translation": translation(premises=["yogurtAddedSugarsPer6Ounces is equal to 17.0",
                                             "yogurtAddedSugarsPer6Ounces is equal to 12.0 and sugarFigureType is equal to ADDED"],
                                   claims=["isYogurtCreditable is false"]),
        "contradictingRules": [{"identifier": "R_S3"}]}})
    c = prove.interpret(r, DEFINITION)
    assert c.verdict == "UNVERIFIED" and c.rules == []
    assert c.missing_facts == ["yogurtAddedSugarsPer6Ounces is equal to 17.0", "yogurtAddedSugarsPer6Ounces is equal to 12.0"]
    r2 = response({"impossible": {"translation": translation(premises=["milkIsFlavored is true", "childAgeYears is equal to 4"]),
                                  "contradictingRules": [{"identifier": "R_S3"}]}})
    assert prove.interpret(r2, DEFINITION).verdict == "IMPOSSIBLE"


def test_unknown_rule_id_falls_back_to_the_id():
    assert prove.rule_text("R_NOPE", DEFINITION) == "R_NOPE"


def test_untranslated_parts_are_reported():
    r = response({"valid": {"translation": translation(claims=["a"], untranslated=["and the rate is 3.31"])}})
    assert prove.interpret(r, DEFINITION).untranslated == ["and the rate is 3.31"]


def test_prove_sends_question_facts_and_answer_in_that_order():
    calls = []

    class Fake:
        def apply_guardrail(self, **kw):
            calls.append(kw)
            return response({"valid": {"translation": translation(claims=["isYogurtCreditable is true"]),
                                       "supportingRules": [{"identifier": "R_Y3"}]}})

    c = prove.prove("Q?", "A.", facts="F.", client=Fake(), cfg={"guardrail_id": "g", "guardrail_version": "2"})
    assert c.verdict == "VALID" and c.guardrail_version == "2"
    kw = calls[0]
    assert kw["guardrailIdentifier"] == "g" and kw["guardrailVersion"] == "2" and kw["source"] == "OUTPUT"
    texts = [(b["text"]["text"], b["text"]["qualifiers"]) for b in kw["content"]]
    assert texts == [("Q?", ["query"]), ("F.", ["query"]), ("A.", ["guard_content"])]


def test_prove_without_a_guardrail_is_skipped_not_an_error():
    assert prove.prove("Q?", "A.", client=object(), cfg={}).verdict == "SKIPPED"


def test_enabled_reads_the_switch(monkeypatch):
    monkeypatch.delenv("TALLY_PROVE", raising=False)
    assert prove.enabled()
    monkeypatch.setenv("TALLY_PROVE", "off")
    assert not prove.enabled()
    monkeypatch.setenv("TALLY_PROVE", "1")
    assert prove.enabled()


def test_the_rule_that_speaks_to_the_claim_is_quoted_first():
    """The solver lists every rule it touched; a yogurt proof once led with a milk rule."""
    r = response({"valid": {"translation": translation(claims=["isYogurtCreditable is true",
                                                                "yogurtAddedSugarsPer6Ounces is equal to 9.0"]),
                            "supportingRules": [{"identifier": "R_M6"}, {"identifier": "R_S3"}, {"identifier": "R_Y3"}]}})
    c = prove.interpret(r, DEFINITION)
    assert c.verdict == "VALID"
    assert c.rules[0].startswith("Yogurt must contain")
    assert prove.rule_vars("R_Y3", DEFINITION) == {"isYogurtCreditable", "yogurtAddedSugarsPer6Ounces"}
