"""Find the numbers written in a piece of text, so validators can compare them with the source.

Handles the ways the model and our own sentences write numbers: `$14.82`, `-$217,153`, `$217k`,
`1.0%`, `10,000 kWh`, `0.0733`. Numbers glued to letters are identifiers, not quantities, and are
skipped: `P10`, `cs-144167`, `G-2`, `M4`. Ordinals (`6th`) count as numbers.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# A number not preceded by a letter, digit, dot, hyphen-joined word or underscore. The optional
# sign and dollar sign may come in either order (-$5 or $-5). An optional k/M suffix and %.
_NUMBER = re.compile(
    r"(?<![A-Za-z0-9_.])(?<![A-Za-z0-9]-)"
    r"(?P<sign>[-\u2212])?\$?(?P<sign2>[-\u2212])?"  # \u2212: Unicode minus
    r"(?P<digits>\d{1,3}(?:,\d{3})+|\d+)(?P<frac>\.\d+)?"
    r"(?:\s?(?P<suffix>k|K|M|million|thousand)\b)?"
    r"(?P<pct>\s?%)?"
    r"(?:st|nd|rd|th)?"  # ordinals: 1st, 6th
    r"(?![A-Za-z0-9])"
)
_SCALE = {"k": 1e3, "K": 1e3, "thousand": 1e3, "M": 1e6, "million": 1e6}


@dataclass(frozen=True)
class Quantity:
    """A number as written: its value, and the rounding step its last digit implies."""

    text: str
    value: float
    step: float  # 1 for "217", 0.01 for "14.82", 1000 for "$217k"
    percent: bool

    def matches(self, exact: float) -> bool:
        """True if `exact` rounds to this written number (sign ignored; percent or fraction)."""
        candidates = [abs(exact)]
        if self.percent:
            candidates.append(abs(exact) * 100)  # 0.544 written as 54.4%
        tol = self.step / 2 + 1e-9 * max(1.0, abs(self.value))
        return any(abs(c - abs(self.value)) <= tol for c in candidates)


def quantities(text: str) -> list[Quantity]:
    """Every standalone number in `text`, in order."""
    found = []
    for m in _NUMBER.finditer(text):
        whole = m.group("digits").replace(",", "")
        frac = m.group("frac") or ""
        scale = _SCALE.get(m.group("suffix") or "", 1.0)
        value = float(whole + frac) * scale
        decimals = len(frac) - 1 if frac else 0
        step = 10.0**-decimals * scale
        found.append(Quantity(m.group(0).strip(), value, step, bool(m.group("pct"))))
    return found


def normalize_space(text: str) -> str:
    """Collapse runs of whitespace (including \\r\\n) to one space, for verbatim-quote checks."""
    return " ".join(text.split())


_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
    "nine": 9, "ten": 10, "twelve": 12, "fifteen": 15, "twenty": 20, "thirty": 30, "sixty": 60,
}  # fmt: skip
_WORD = re.compile(r"\b(" + "|".join(_WORDS) + r")\b", re.IGNORECASE)


def word_numbers(text: str) -> list[int]:
    """Numbers spelled out in tariff prose: "the greatest fifteen minute peak" -> [15]."""
    return [_WORDS[m.group(1).lower()] for m in _WORD.finditer(text)]
