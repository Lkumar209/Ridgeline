"""Deterministic checks that reject model outputs inconsistent with their source.

These are the point of the agent layer: the model drafts, the validator decides. Errors reject an
output; warnings keep it but flag it for a person to review.

Extraction: every non-null value must be backed by an exact quote from the tariff text, and the
quoted text must contain that value. Explanation: every number must come from the facts given,
every site ID must be one of the facts' sites, and required caveats must be present.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Generic, TypeVar

from ridgeline.agent.numbers import Quantity, normalize_space, quantities, word_numbers

if TYPE_CHECKING:
    from ridgeline.agent.tariff_extract import NumberField, TariffExtraction, TextField

T = TypeVar("T")


@dataclass(frozen=True)
class Checked(Generic[T]):
    output: T | None
    errors: list[str]
    warnings: list[str]

    @property
    def accepted(self) -> bool:
        return self.output is not None and not self.errors


# ---- extraction -------------------------------------------------------------------------------

_CENTS = re.compile(r"cents?\b|¢")
# "There is no demand charge", "without a customer charge": an explicit zero, not a missing value.
_NO_CHARGE = re.compile(r"\b(no|without)\s+(\w+\s+){0,3}charges?\b", re.IGNORECASE)


def _quote_in_source(evidence: str, source: str) -> bool:
    return normalize_space(evidence).casefold() in normalize_space(source).casefold()


def _number_in_evidence(value: float, evidence: str) -> bool:
    if value == 0 and _NO_CHARGE.search(evidence):
        return True
    found = quantities(evidence)
    if _CENTS.search(evidence):
        # "1.5 cents per kWh" must come back as 0.015 dollars, not 1.5.
        return any(q.matches(value * 100) for q in found)
    return any(q.matches(value) for q in found) or value in word_numbers(evidence)


def check_extraction(
    extraction: TariffExtraction, source: str, min_confidence: float
) -> Checked[TariffExtraction]:
    errors: list[str] = []
    warnings: list[str] = []
    for name, field in extraction.fields().items():
        errors.extend(_check_field(name, field, source))
        if (
            field.value is not None
            and 0 <= field.confidence < min_confidence
            and not any(e.startswith(name) for e in errors)
        ):
            warnings.append(f"{name}: confidence {field.confidence:.2f} is below {min_confidence}")
    return Checked(output=extraction, errors=errors, warnings=warnings)


def _check_field(name: str, field: NumberField | TextField, source: str) -> list[str]:
    if not 0 <= field.confidence <= 1:
        return [f"{name}: confidence {field.confidence} is outside 0..1"]
    if field.value is None:
        if field.evidence:
            return [f"{name}: evidence given but value is null"]
        return []
    if not field.evidence:
        return [f"{name}: value {field.value!r} has no evidence quote"]
    if not _quote_in_source(field.evidence, source):
        return [f"{name}: evidence {field.evidence!r} is not an exact quote from the text"]
    if isinstance(field.value, str):
        if (
            normalize_space(field.value).casefold()
            not in normalize_space(field.evidence).casefold()
        ):
            return [f"{name}: value {field.value!r} does not appear in its evidence"]
        return []
    if not _number_in_evidence(field.value, field.evidence):
        return [f"{name}: value {field.value} does not appear in its evidence {field.evidence!r}"]
    return []


# ---- explanation ------------------------------------------------------------------------------

SITE_ID = re.compile(r"\bcs-\d+\b")
_SUPERLATIVE = re.compile(r"\b(best|worst|top|strongest|weakest)\b", re.IGNORECASE)
_MEASURE = re.compile(
    r"P10|P50|P90|median|bad-case|good-case|robust|breakeven|break even|rank", re.IGNORECASE
)
_NEVER_PAYS = re.compile(
    r"never pays? back|(does not|doesn't|not) pay back|never breaks? even|"
    r"(does not|doesn't|not) break even",
    re.IGNORECASE,
)
_PROXY = re.compile(r"proxy|stand-in", re.IGNORECASE)
_SENTENCE = re.compile(r"(?<=[.!?])\s+")


@dataclass(frozen=True)
class ExplanationRules:
    facts_text: str
    site_id: str
    never_pays_back: bool
    tariff_is_proxy: bool


def check_explanation(text: str, rules: ExplanationRules) -> Checked[str]:
    errors: list[str] = []
    known: list[Quantity] = quantities(rules.facts_text)
    for q in quantities(text):
        if not any(q.matches(k.value) or k.matches(q.value) for k in known):
            errors.append(f"number {q.text!r} is not in the facts provided")
    known_ids = set(SITE_ID.findall(rules.facts_text))
    errors += [
        f"site {s!r} is not in the facts" for s in SITE_ID.findall(text) if s not in known_ids
    ]
    if rules.site_id not in text:
        errors.append(f"does not name the site ({rules.site_id})")
    for sentence in _SENTENCE.split(text):
        if _SUPERLATIVE.search(sentence) and not _MEASURE.search(sentence):
            errors.append(f"superlative without a measure: {sentence.strip()!r}")
    if rules.never_pays_back and not _NEVER_PAYS.search(text):
        errors.append("omits that the site never pays back on bill savings alone")
    if rules.tariff_is_proxy and not _PROXY.search(text):
        errors.append("omits that the site's tariff is a proxy")
    return Checked(output=text, errors=errors, warnings=[])
