"""The one seam between Ridgeline and a language model.

`LLMClient` is a Protocol with a single method, so the extraction and explanation code never
imports the Anthropic SDK. Tests and the offline evals use `MockClient`; live runs use
`AnthropicClient`, which reads the key from `ANTHROPIC_API_KEY` (via the SDK) and the model from
`RIDGELINE_LLM_MODEL` or `config/default.yaml`. The key is never read, logged or printed here.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol

MODEL_ENV_VAR = "RIDGELINE_LLM_MODEL"
KEY_ENV_VAR = "ANTHROPIC_API_KEY"

# Models that accept the server-side refusal fallback (`fallbacks: "default"`). For any other
# model the parameter is left out rather than risk a 400.
_FALLBACK_MODELS = frozenset({"claude-opus-5-5", "claude-opus-5", "claude-fable-5-1"})
_FALLBACK_BETA = "server-side-fallback-2026-07-01"


class AgentError(RuntimeError):
    """The model could not produce a usable answer (refusal, truncation, invalid JSON)."""


@dataclass(frozen=True)
class LLMRequest:
    system: str
    user: str
    # JSON schema for structured output; None for free text.
    json_schema: dict[str, Any] | None = None

    def key(self) -> str:
        """Stable hash of the request, used by MockClient to look up canned responses."""
        payload = json.dumps(
            {"system": self.system, "user": self.user, "schema": self.json_schema},
            sort_keys=True,
        )
        return hashlib.sha256(payload.encode()).hexdigest()[:16]


class LLMClient(Protocol):
    def complete(self, request: LLMRequest) -> str:
        """Return the model's text (JSON text when `request.json_schema` is set)."""
        ...


@dataclass
class MockClient:
    """Deterministic offline client: returns canned responses keyed by the request's user text.

    Keyed by user text (not the full request) so a wording change in a system prompt does not
    silently orphan every fixture; a changed user prompt fails loudly with KeyError.
    """

    responses: Mapping[str, str]
    calls: list[LLMRequest] = field(default_factory=list)

    def complete(self, request: LLMRequest) -> str:
        self.calls.append(request)
        try:
            return self.responses[request.user]
        except KeyError:
            raise KeyError(
                f"MockClient has no canned response for request {request.key()}; "
                "add one to the eval case or test"
            ) from None


@dataclass(frozen=True)
class AgentSettings:
    model: str
    max_tokens: int
    effort: str


def resolve_model(configured: str) -> str:
    """The model comes from $RIDGELINE_LLM_MODEL if set, else from config."""
    return os.environ.get(MODEL_ENV_VAR) or configured


def has_api_key() -> bool:
    """Whether a live run is possible. Only checks presence; the value is never read here."""
    return bool(os.environ.get(KEY_ENV_VAR))


class AnthropicClient:
    """Live client over the Anthropic Messages API (structured outputs for JSON requests)."""

    def __init__(self, settings: AgentSettings) -> None:
        import anthropic  # imported here so offline code paths never need the SDK

        self._anthropic = anthropic
        self._client = anthropic.Anthropic()  # credentials resolved by the SDK, never logged
        self.settings = settings

    def complete(self, request: LLMRequest) -> str:
        output_config: dict[str, Any] = {"effort": self.settings.effort}
        if request.json_schema is not None:
            output_config["format"] = {"type": "json_schema", "schema": request.json_schema}
        kwargs: dict[str, Any] = {
            "model": self.settings.model,
            "max_tokens": self.settings.max_tokens,
            "system": request.system,
            "messages": [{"role": "user", "content": request.user}],
            "output_config": output_config,
        }
        if self.settings.model in _FALLBACK_MODELS:
            kwargs["betas"] = [_FALLBACK_BETA]
            kwargs["fallbacks"] = "default"
        try:
            response = self._client.beta.messages.create(**kwargs)
        except self._anthropic.APIStatusError as e:
            raise AgentError(f"Anthropic API error {e.status_code}: {e.message}") from e
        except self._anthropic.APIConnectionError as e:
            raise AgentError(f"could not reach the Anthropic API: {e}") from e
        if response.stop_reason == "refusal":
            raise AgentError("the model declined this request")
        if response.stop_reason == "max_tokens":
            raise AgentError("the response was cut off at max_tokens")
        text = "".join(b.text for b in response.content if b.type == "text")
        if not text.strip():
            raise AgentError("the model returned no text")
        return text
