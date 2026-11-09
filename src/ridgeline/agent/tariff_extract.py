"""Extract demand-tariff parameters from a tariff's text, with per-field confidence and evidence.

Each field comes back as `{value, confidence, evidence}`. `evidence` must be an exact quote from the
source, and a field the text does not state must be null: the model is told not to guess, and
`validate_extraction` rejects any value it cannot find in the quoted text.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, ValidationError

from ridgeline.agent.client import LLMClient, LLMRequest
from ridgeline.agent.validators import Checked, check_extraction


class _Wire(BaseModel):
    # extra="forbid" -> additionalProperties: false, which structured outputs require.
    model_config = ConfigDict(extra="forbid", frozen=True)


class NumberField(_Wire):
    value: float | None
    confidence: float
    evidence: str | None


class TextField(_Wire):
    value: str | None
    confidence: float
    evidence: str | None


class TariffExtraction(_Wire):
    utility: TextField
    rate_name: TextField
    demand_charge_usd_per_kw: NumberField
    energy_rate_usd_per_kwh: NumberField
    fixed_charge_usd_per_month: NumberField
    max_demand_kw: NumberField
    min_avg_monthly_usage_kwh: NumberField
    demand_interval_minutes: NumberField
    kva_demand_fraction: NumberField
    minimum_billing_demand_kw: NumberField
    notes: list[str]

    def fields(self) -> dict[str, NumberField | TextField]:
        return {name: getattr(self, name) for name in FIELD_HELP}


# What each field means, shown to the model. Kept next to the schema so they cannot drift apart.
FIELD_HELP: dict[str, str] = {
    "utility": "the utility company's name",
    "rate_name": "the rate or tariff name, e.g. 'G-2'",
    "demand_charge_usd_per_kw": "the monthly demand charge in dollars per kW",
    "energy_rate_usd_per_kwh": "the energy (per-kWh) charge in dollars per kWh",
    "fixed_charge_usd_per_month": "the fixed customer charge in dollars per month",
    "max_demand_kw": "the largest demand (kW) a customer may have and stay on this rate",
    "min_avg_monthly_usage_kwh": "the minimum average monthly use (kWh) to qualify for this rate",
    "demand_interval_minutes": "the length in minutes of the demand measurement interval",
    "kva_demand_fraction": "the fraction of kVA demand used as billing demand, e.g. 0.9 for 90%",
    "minimum_billing_demand_kw": "the minimum billing demand in kW",
}

SYSTEM_PROMPT = f"""\
You extract parameters of a commercial electricity tariff from its text, for an illustrative
battery-economics model. Return JSON matching the schema.

For each field return value, confidence (0 to 1) and evidence:
- evidence is an exact, contiguous quote from the tariff text that states the value. Copy it
  character for character; do not paraphrase, fix typos or join separate passages.
- If the text does not state the value, return value null, evidence null and confidence 0. Do not
  infer, estimate or fill in a typical value: a missing number must stay missing.
- If the text gives two different values for the same field and does not say which applies,
  return value null and explain the conflict in notes.
- Give dollar amounts in dollars (convert cents to dollars) and percentages as fractions
  (90% -> 0.9). Write numbers in your evidence exactly as the text does.
- Confidence is how sure you are that the value is the one this field asks for, not how sure you
  are that the quote exists.

Fields:
{chr(10).join(f"- {name}: {help_}" for name, help_ in FIELD_HELP.items())}

Use notes for anything a modeler should know that has no field (conditions, discounts, credits).
"""


def build_request(tariff_text: str) -> LLMRequest:
    user = f"<tariff_text>\n{tariff_text}\n</tariff_text>"
    return LLMRequest(
        system=SYSTEM_PROMPT, user=user, json_schema=TariffExtraction.model_json_schema()
    )


def extract_tariff(
    client: LLMClient, tariff_text: str, min_confidence: float
) -> Checked[TariffExtraction]:
    """Ask the model for the tariff's parameters, then check every value against the text."""
    raw = client.complete(build_request(tariff_text))
    return parse_and_check(raw, tariff_text, min_confidence)


def parse_and_check(raw: str, tariff_text: str, min_confidence: float) -> Checked[TariffExtraction]:
    try:
        extraction = TariffExtraction.model_validate_json(raw)
    except ValidationError as e:
        return Checked(output=None, errors=[f"output does not match the schema: {e}"], warnings=[])
    return check_extraction(extraction, tariff_text, min_confidence)
