import json

import pandas as pd
from typer.testing import CliRunner

from ridgeline.agent.client import MockClient
from ridgeline.agent.evals import load_cases, mock_client, run_evals
from ridgeline.agent.explain import SiteFacts, build_request, facts_from_ranking
from ridgeline.agent.tariff_extract import FIELD_HELP
from ridgeline.agent.tariff_extract import build_request as extraction_request
from ridgeline.cli import app
from ridgeline.config import REPO_ROOT

CASES = load_cases()


def test_eval_set_size_and_shape():
    assert len(CASES["extraction"]) >= 5
    assert len(CASES["explanation"]) >= 5
    ids = [c["id"] for kind in CASES.values() for c in kind]
    assert len(ids) == len(set(ids))
    for case in CASES["extraction"]:
        assert set(case["expected"]) <= set(FIELD_HELP)
        assert any(v is None for v in case["expected"].values()) or case["id"] == "rates_stated"


def test_all_cases_pass_against_the_mock():
    results = run_evals(mock_client(CASES), 0.6, CASES)
    assert [r.problems for r in results if not r.passed] == []


def test_evals_catch_a_model_that_guesses():
    """Non-vacuity: replace one good canned answer with a guess and the case must fail."""
    client = mock_client(CASES)
    case = next(c for c in CASES["extraction"] if c["id"] == "conflicting_demand_charge")
    user = extraction_request(case["text"]).user
    guessed = json.loads(client.responses[user])
    guessed["demand_charge_usd_per_kw"] = {
        "value": 14.82,
        "confidence": 0.9,
        "evidence": "Demand Charge: $14.82 per kW per month.",
    }
    responses = dict(client.responses, **{user: json.dumps(guessed)})
    results = {r.case_id: r for r in run_evals(MockClient(responses), 0.6, CASES)}
    failed = results["conflicting_demand_charge"]
    assert not failed.passed
    assert failed.problems == ["demand_charge_usd_per_kw: got 14.82, expected None"]


def test_evals_catch_an_explanation_with_an_invented_number():
    client = mock_client(CASES)
    case = CASES["explanation"][0]
    user = build_request(SiteFacts.model_validate(case["facts"])).user
    responses = dict(client.responses, **{user: client.responses[user] + " Payback: 11 years."})
    results = {r.case_id: r for r in run_evals(MockClient(responses), 0.6, CASES)}
    assert not results[case["id"]].passed


def test_explanation_facts_match_the_committed_ranking():
    """Eval facts are real rows of docs/m4/ranking.csv, not made-up numbers."""
    ranking = pd.read_csv(REPO_ROOT / "docs" / "m4" / "ranking.csv")
    for case in CASES["explanation"]:
        facts = SiteFacts.model_validate(case["facts"])
        rebuilt = facts_from_ranking(
            ranking,
            facts.site_id,
            n_draws=facts.n_draws,
            life_years=facts.life_years,
            capex_usd_per_kw=facts.capex_usd_per_kw,
        )
        assert rebuilt == facts, case["id"]


def test_cli_evals_offline():
    result = CliRunner().invoke(app, ["evals"])
    assert result.exit_code == 0, result.output
    assert "11/11 cases passed" in result.output


def test_cli_live_commands_need_a_key(monkeypatch, tmp_path):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    text = tmp_path / "tariff.txt"
    text.write_text("Rate G-2. Demand Charge: $14.82 per kW.")
    for args in (["extract-tariff", str(text)], ["evals", "--live"]):
        result = CliRunner().invoke(app, args)
        assert result.exit_code == 2, result.output
        assert "ANTHROPIC_API_KEY is not set" in result.output
