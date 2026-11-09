from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any

import pytest

from ridgeline.agent.client import (
    AgentError,
    AgentSettings,
    AnthropicClient,
    LLMRequest,
    MockClient,
    resolve_model,
)
from ridgeline.agent.tariff_extract import TariffExtraction


class FakeMessages:
    def __init__(self, response: Any) -> None:
        self.response = response
        self.kwargs: dict[str, Any] = {}

    def create(self, **kwargs: Any) -> Any:
        self.kwargs = kwargs
        return self.response


def _client(monkeypatch: Any, model: str, response: Any) -> tuple[AnthropicClient, FakeMessages]:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "dummy-not-a-real-key")
    client = AnthropicClient(AgentSettings(model=model, max_tokens=1000, effort="medium"))
    fake = FakeMessages(response)
    client._client = SimpleNamespace(beta=SimpleNamespace(messages=fake))  # type: ignore[assignment]
    return client, fake


def _response(text: str, stop_reason: str = "end_turn") -> SimpleNamespace:
    return SimpleNamespace(
        stop_reason=stop_reason, content=[SimpleNamespace(type="text", text=text)]
    )


def test_mock_client_returns_canned_text_and_fails_loudly_on_unknown_requests():
    mock = MockClient({"hello": "world"})
    assert mock.complete(LLMRequest(system="s", user="hello")) == "world"
    with pytest.raises(KeyError, match="no canned response"):
        mock.complete(LLMRequest(system="s", user="something else"))
    assert len(mock.calls) == 2


def test_model_comes_from_env_then_config(monkeypatch):
    monkeypatch.delenv("RIDGELINE_LLM_MODEL", raising=False)
    assert resolve_model("claude-opus-5-5") == "claude-opus-5-5"
    monkeypatch.setenv("RIDGELINE_LLM_MODEL", "claude-sonnet-5-5")
    assert resolve_model("claude-opus-5-5") == "claude-sonnet-5-5"


def test_structured_request_sends_schema_and_fallback(monkeypatch):
    client, fake = _client(monkeypatch, "claude-opus-5-5", _response("{}"))
    schema = TariffExtraction.model_json_schema()
    assert client.complete(LLMRequest(system="s", user="u", json_schema=schema)) == "{}"
    sent = fake.kwargs
    assert sent["model"] == "claude-opus-5-5"
    assert sent["output_config"] == {
        "effort": "medium",
        "format": {"type": "json_schema", "schema": schema},
    }
    assert sent["fallbacks"] == "default"
    assert sent["betas"] == ["server-side-fallback-2026-07-01"]
    assert sent["messages"] == [{"role": "user", "content": "u"}]


def test_no_fallback_parameter_for_other_models(monkeypatch):
    client, fake = _client(monkeypatch, "claude-haiku-5-5", _response("text"))
    client.complete(LLMRequest(system="s", user="u"))
    assert "fallbacks" not in fake.kwargs
    assert "format" not in fake.kwargs["output_config"]


@pytest.mark.parametrize(("stop_reason", "match"), [("refusal", "declined"), ("max_tokens", "cut")])
def test_unusable_responses_raise(monkeypatch, stop_reason, match):
    client, _ = _client(monkeypatch, "claude-opus-5-5", _response("partial", stop_reason))
    with pytest.raises(AgentError, match=match):
        client.complete(LLMRequest(system="s", user="u"))


def _walk(node: Any) -> Iterator[dict[str, Any]]:
    if isinstance(node, dict):
        yield node
        for v in node.values():
            yield from _walk(v)
    elif isinstance(node, list):
        for v in node:
            yield from _walk(v)


def test_extraction_schema_is_strict():
    """Structured outputs need every object closed and every property required."""
    objects = [n for n in _walk(TariffExtraction.model_json_schema()) if n.get("type") == "object"]
    assert len(objects) >= 3
    for obj in objects:
        assert obj["additionalProperties"] is False
        assert set(obj["required"]) == set(obj["properties"])
