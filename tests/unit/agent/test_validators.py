"""The validators must reject outputs that are not backed by the source text or the facts."""

import json
from typing import Any

import pytest

from ridgeline.agent.evals import load_cases, tariff_text
from ridgeline.agent.explain import SiteFacts, render_facts, rules_for
from ridgeline.agent.tariff_extract import FIELD_HELP, parse_and_check
from ridgeline.agent.validators import check_explanation

NULL = {"value": None, "confidence": 0.0, "evidence": None}
SOURCE = (
    "Massachusetts Electric Company, Rate G-2.\n"
    "Customer Charge: $45.00 per month.\n"
    "Distribution Demand Charge: $14.82 per kW of Demand.\n"
    "Distribution Energy Charge: 7.33 cents per kWh."
)


def _extraction(**fields: Any) -> str:
    out: dict[str, Any] = {name: NULL for name in FIELD_HELP}
    out.update(fields)
    out["notes"] = []
    return json.dumps(out)


def _check(**fields: Any) -> Any:
    return parse_and_check(_extraction(**fields), SOURCE, min_confidence=0.6)


def _f(value: Any, evidence: str | None, confidence: float = 0.9) -> dict[str, Any]:
    return {"value": value, "confidence": confidence, "evidence": evidence}


def test_supported_values_are_accepted():
    checked = _check(
        demand_charge_usd_per_kw=_f(14.82, "Demand Charge: $14.82 per kW"),
        energy_rate_usd_per_kwh=_f(0.0733, "7.33 cents per kWh"),
        fixed_charge_usd_per_month=_f(45, "Customer Charge: $45.00 per month."),
        rate_name=_f("G-2", "Rate G-2."),
    )
    assert checked.accepted, checked.errors
    assert checked.warnings == []


def test_all_null_is_accepted():
    assert _check().accepted


@pytest.mark.parametrize(
    ("field", "value", "why"),
    [
        # A plausible guess with an invented quote.
        ("max_demand_kw", _f(200, "but not exceed 200 kW of Demand"), "not an exact quote"),
        # A paraphrase of a real line.
        ("demand_charge_usd_per_kw", _f(14.82, "demand charge is $14.82/kW"), "not an exact quote"),
        # A real quote that does not contain the value.
        ("demand_charge_usd_per_kw", _f(16.10, "Demand Charge: $14.82 per kW"), "does not appear"),
        # Cents read as dollars.
        ("energy_rate_usd_per_kwh", _f(7.33, "7.33 cents per kWh"), "does not appear"),
        # A value with no evidence at all.
        ("fixed_charge_usd_per_month", _f(45, None), "no evidence"),
        # Evidence for a field the model then left empty.
        ("fixed_charge_usd_per_month", _f(None, "Customer Charge: $45.00"), "value is null"),
        ("rate_name", _f("G-3", "Rate G-2."), "does not appear"),
        ("rate_name", _f("G-2", "Rate G-2.", confidence=1.5), "outside 0..1"),
    ],
)
def test_unsupported_values_are_rejected(field, value, why):
    checked = _check(**{field: value})
    assert not checked.accepted
    assert any(field in e and why in e for e in checked.errors), checked.errors


def test_low_confidence_is_flagged_not_rejected():
    checked = _check(rate_name=_f("G-2", "Rate G-2.", confidence=0.3))
    assert checked.accepted
    assert checked.warnings == ["rate_name: confidence 0.30 is below 0.6"]


def test_output_that_breaks_the_schema_is_rejected():
    checked = parse_and_check('{"utility": "x"}', SOURCE, 0.6)
    assert checked.output is None
    assert not checked.accepted
    assert "schema" in checked.errors[0]


def test_a_guessed_demand_charge_on_the_real_g2_text_is_rejected():
    """The committed G-2 description states no prices; $14.82 from elsewhere is a guess here."""
    g2 = tariff_text(next(c for c in load_cases()["extraction"] if "urdb_description" in c))
    assert "14.82" not in g2  # guard: the test is only meaningful if the price is absent
    raw = _extraction(demand_charge_usd_per_kw=_f(14.82, "$14.82 per kW"))
    checked = parse_and_check(raw, g2, 0.6)
    assert not checked.accepted


# ---- explanations ----------------------------------------------------------------------------

# A real eval case, flagged as a proxy-tariff site so the proxy caveat rule is exercised too.
FACTS = SiteFacts.model_validate(
    next(c for c in load_cases()["explanation"] if c["id"] == "most_robust")["facts"]
).model_copy(update={"tariff_is_proxy": True})
GOOD = (
    "Site cs-70654 ranks 1 of 40 by bad-case (P10) NPV, about -$230k over 15 years. "
    "It never pays back, even at $0 battery cost, and the result rests on a proxy tariff."
)


def test_grounded_explanation_is_accepted():
    checked = check_explanation(GOOD, rules_for(FACTS))
    assert checked.accepted, checked.errors


@pytest.mark.parametrize(
    ("text", "why"),
    [
        (GOOD.replace("-$230k", "-$232k"), "'-$232k' is not in the facts"),
        (GOOD + " That is $46k worse than its median.", "'$46k' is not in the facts"),
        (GOOD + " Payback takes 12 years.", "'12' is not in the facts"),
        (GOOD + " It beats cs-99999.", "site 'cs-99999' is not in the facts"),
        (GOOD + " It is the best site.", "superlative without a measure"),
        (GOOD.replace("Site cs-70654", "This site"), "does not name the site"),
        (GOOD.replace("It never pays back, even at $0 battery cost, and t", "T"), "never pays"),
        (GOOD.replace(", and the result rests on a proxy tariff", ""), "proxy"),
    ],
)
def test_ungrounded_explanations_are_rejected(text, why):
    checked = check_explanation(text, rules_for(FACTS))
    assert not checked.accepted
    assert any(why in e for e in checked.errors), checked.errors


def test_every_number_in_the_facts_is_allowed():
    """The facts text itself must pass its own number check (no self-inconsistent facts)."""
    facts_text = render_facts(FACTS)
    checked = check_explanation(facts_text + " cs-70654 never pays back; proxy.", rules_for(FACTS))
    assert not [e for e in checked.errors if "number" in e]


def test_an_explicit_no_charge_is_a_stated_zero() -> None:
    source = "Rate G-1. There is no demand charge under this rate. Use must not exceed 200 kW."
    zero = _f(0, "There is no demand charge under this rate.")
    raw = _extraction(demand_charge_usd_per_kw=zero)
    assert parse_and_check(raw, source, 0.6).accepted
    # A negation that is not about a charge does not justify a zero.
    raw = _extraction(fixed_charge_usd_per_month=_f(0, "Use must not exceed 200 kW."))
    assert not parse_and_check(raw, source, 0.6).accepted
