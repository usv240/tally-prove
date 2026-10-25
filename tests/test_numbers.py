"""Numbers from nowhere: the check that an answer's numbers are hers or the regulation's."""

from tally import numbers

RULEBOOK = {"12", "6", "3", "5", "1", "8", "0.5"}


def test_a_limit_from_memory_is_named():
    out = numbers.unsourced("17 g is under the 23 g limit, so yes.", ["The label says 17 grams of sugar."], RULEBOOK)
    assert out == ["23"]


def test_her_numbers_and_the_regulations_are_not():
    out = numbers.unsourced("At 9 grams of added sugars per 6 oz it is under the 12 gram limit.",
                            ["The label says 9 grams of added sugars per 6 ounces."], RULEBOOK)
    assert out == []


def test_numbers_said_earlier_in_the_conversation_count_as_hers():
    out = numbers.unsourced("So 17 grams is over the 12 gram limit.",
                            ["Can I serve the yogurt? The label says 17 grams.", "It is for the 3 to 5s."], RULEBOOK)
    assert out == []


def test_dates_ids_and_decimals_are_read_sensibly():
    assert numbers.numbers_in("Filed until 2029-09-07, policy 99kmtaqh3ntb:7, 12.0 grams, $0.98") == ["12", "0.98"]


def test_the_rulebook_set_comes_from_the_policy_definition():
    rb = numbers.rulebook_numbers()
    assert "12" in rb and "6" in rb
    assert "23" not in rb, "the expired total-sugars limit must not be in the regulation's numbers"
