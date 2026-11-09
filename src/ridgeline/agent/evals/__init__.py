"""Run the M6 eval set (`cases.yaml`) against the mock client or a live model.

A case passes when the validator accepts the output and the output is correct: extracted values
equal `expected` (null where the text states nothing), and explanations contain every
`expected_mentions` phrase.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from ridgeline.agent.client import LLMClient, MockClient
from ridgeline.agent.explain import SiteFacts, explain_site
from ridgeline.agent.explain import build_request as explanation_request
from ridgeline.agent.tariff_extract import FIELD_HELP, extract_tariff
from ridgeline.agent.tariff_extract import build_request as extraction_request
from ridgeline.config import REPO_ROOT

CASES_FILE = Path(__file__).with_name("cases.yaml")
_NOT_STATED = {"value": None, "confidence": 0.0, "evidence": None}


@dataclass(frozen=True)
class CaseResult:
    kind: str
    case_id: str
    passed: bool
    problems: list[str]
    output: str = ""  # the model's text, shown for failed cases


def load_cases(path: Path = CASES_FILE) -> dict[str, list[dict[str, Any]]]:
    with path.open() as f:
        cases: dict[str, list[dict[str, Any]]] = yaml.safe_load(f)
    return cases


def tariff_text(case: dict[str, Any]) -> str:
    if "urdb_description" in case:
        record = json.loads((REPO_ROOT / case["urdb_description"]).read_text())
        return str(record["items"][0]["description"])
    return str(case["text"])


def _mock_extraction_json(case: dict[str, Any]) -> str:
    given = case["mock_response"]
    full = {name: given.get(name, _NOT_STATED) for name in FIELD_HELP}
    full["notes"] = given.get("notes", [])
    return json.dumps(full)


def mock_client(cases: dict[str, list[dict[str, Any]]]) -> MockClient:
    """A MockClient that answers every case's request with its hand-written mock_response."""
    responses: dict[str, str] = {}
    for case in cases["extraction"]:
        responses[extraction_request(tariff_text(case)).user] = _mock_extraction_json(case)
    for case in cases["explanation"]:
        request = explanation_request(SiteFacts.model_validate(case["facts"]))
        responses[request.user] = str(case["mock_response"])
    return MockClient(responses)


def _same(got: float | str | None, want: float | str | None) -> bool:
    if got is None or want is None:
        return got is None and want is None
    if isinstance(want, str) or isinstance(got, str):
        return str(got).casefold() == str(want).casefold()
    return math.isclose(got, want, rel_tol=1e-6, abs_tol=1e-9)


def run_extraction_case(
    client: LLMClient, case: dict[str, Any], min_confidence: float
) -> CaseResult:
    checked = extract_tariff(client, tariff_text(case), min_confidence)
    problems = [f"rejected: {e}" for e in checked.errors]
    if checked.output is not None:
        fields = checked.output.fields()
        for name, want in case["expected"].items():
            got = fields[name].value
            if not _same(got, want):
                problems.append(f"{name}: got {got!r}, expected {want!r}")
    output = checked.output.model_dump_json(indent=1) if checked.output is not None else ""
    return CaseResult("extraction", case["id"], not problems, problems, output)


def run_explanation_case(client: LLMClient, case: dict[str, Any]) -> CaseResult:
    checked = explain_site(client, SiteFacts.model_validate(case["facts"]))
    problems = [f"rejected: {e}" for e in checked.errors]
    text = checked.output or ""
    problems += [
        f"does not mention {phrase!r}"
        for phrase in case.get("expected_mentions", [])
        if phrase.casefold() not in text.casefold()
    ]
    return CaseResult("explanation", case["id"], not problems, problems, text)


def run_evals(
    client: LLMClient, min_confidence: float, cases: dict[str, list[dict[str, Any]]] | None = None
) -> list[CaseResult]:
    cases = cases if cases is not None else load_cases()
    results = [run_extraction_case(client, c, min_confidence) for c in cases["extraction"]]
    results += [run_explanation_case(client, c) for c in cases["explanation"]]
    return results


def report(results: list[CaseResult]) -> str:
    lines = []
    for r in results:
        lines.append(f"{'PASS' if r.passed else 'FAIL'}  {r.kind:<11} {r.case_id}")
        lines += [f"      - {p}" for p in r.problems]
        if not r.passed and r.kind == "explanation" and r.output:
            lines.append(f"      output: {r.output}")
    passed = sum(r.passed for r in results)
    lines.append(f"{passed}/{len(results)} cases passed")
    return "\n".join(lines)
