import pytest

from ridgeline.agent.numbers import quantities, word_numbers


def _values(text: str) -> list[float]:
    return [q.value for q in quantities(text)]


@pytest.mark.parametrize(
    ("text", "values"),
    [
        ("P10 NPV of -$217,153 at cs-144167", [217153.0]),
        ("about $217k", [217000.0]),
        ("$14.82 per kW and 10,000 kWh/month", [14.82, 10000.0]),
        ("ranked 6th by P10 and 1st by P50, rate G-2, milestone M4", [6.0, 1.0]),
        ("a 1.0% discount and 90% of kVA", [1.0, 90.0]),
        ("a 15-year horizon in 2025 dollars", [15.0, 2025.0]),
    ],
)
def test_quantities_finds_numbers_and_skips_identifiers(text, values):
    assert _values(text) == values


def test_rounded_numbers_match_the_exact_value_they_round_from():
    (k,) = quantities("-$217k")
    assert k.matches(-217152.72)
    assert not k.matches(-218000.1)
    (exact,) = quantities("$14.82")
    assert exact.matches(14.82)
    assert not exact.matches(14.83)


def test_percent_matches_a_fraction():
    (pct,) = quantities("90%")
    assert pct.matches(0.9)
    assert pct.matches(90)


def test_word_numbers():
    assert word_numbers("The greatest fifteen minute peak, or Thirty") == [15, 30]
