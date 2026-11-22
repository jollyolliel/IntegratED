"""Gemini implementation of LLMProvider — Google AI Studio, not Vertex AI.

Talks to `generativelanguage.googleapis.com` with an AI Studio key over plain
`requests` (already a direct dependency; docs/operations/deployment.md requires pyproject.toml's
dependencies to list only direct imports, so no new SDK).

Deliberately a different env var from `scripts/translation_audit.py`'s
`GEMINI_API_KEY` — that is a dev-time script with its own key and quota, and is
left alone.
"""

import json
import logging
import os
import time
from typing import Any

import requests

from helpers.ai.provider import (
    LLMProvider,
    ProviderError,
    ProviderReply,
    ToolCall,
    ToolSpec,
)
from settings import get_settings

logger = logging.getLogger(__name__)

API_ROOT = "https://generativelanguage.googleapis.com/v1beta/models"

# A hung call otherwise holds one of gunicorn's 8 threads until the worker
# timeout — the hazard documented on helpers/eleven_labs.py's TTS_TIMEOUT.
# Also the budget for one whole `complete()` — every retry and the fallback
# model included — so `loop.TURN_DEADLINE_SECONDS` + one call still fits
# inside gunicorn's `--timeout 60`.
REQUEST_TIMEOUT_SECONDS = 25

# Below this much budget a fresh request is not worth starting.
_MIN_ATTEMPT_SECONDS = 1.0

DEFAULT_MODEL = "gemini-3.7-flash"
DEFAULT_FALLBACK_MODEL = "gemini-3.6-flash"

# JSON Schema keywords Gemini's function-declaration schema does not accept.
_SCHEMA_DROP = {"additionalProperties", "$schema", "default", "examples"}


def _clean_schema(node: Any) -> Any:
    """Strip keywords Gemini rejects, recursively. Everything else passes.

    Args:
        node (Any): A JSON Schema node (dict/list/scalar) to clean.

    Returns:
        Any: The same structure with `_SCHEMA_DROP` keys removed.
    """
    if isinstance(node, dict):
        return {
            key: _clean_schema(value)
            for key, value in node.items()
            if key not in _SCHEMA_DROP
        }
    if isinstance(node, list):
        return [_clean_schema(item) for item in node]
    return node


class GeminiProvider(LLMProvider):
    """`LLMProvider` implementation talking to Google AI Studio's Gemini REST API."""
    name = "gemini"

    def __init__(self, model: str | None = None, fallback_model: str | None = None) -> None:
        """Configure the primary and fallback Gemini models.

        Args:
            model (str | None): Primary model id; defaults to `ASSISTANT_MODEL` env var.
            fallback_model (str | None): Retried on primary failure; defaults
                to `ASSISTANT_MODEL_FALLBACK` env var.

        Returns:
            None
        """
        self.model = model or os.environ.get("ASSISTANT_MODEL", DEFAULT_MODEL)
        self.fallback_model = fallback_model or os.environ.get(
            "ASSISTANT_MODEL_FALLBACK", DEFAULT_FALLBACK_MODEL
        )
        #: Set when a turn had to fall back — the loop emits a step about it.
        self.last_model_used = None
        self.downgraded = False

    # ── key ──────────────────────────────────────────────────────────────────

    @staticmethod
    def _api_key() -> str:
        """The configured key (`settings.py`).

        Returns:
            str: The Gemini AI Studio API key.
        """
        key = get_settings().gemini_api_key
        if not key:
            raise ProviderError(
                "GEMINI_AISTUDIO_API_KEY is not set — the assistant has no model to call."
            )
        return key

    # ── translation: ours -> Gemini ──────────────────────────────────────────

    @staticmethod
    def _to_contents(messages: list[dict]) -> list[dict[str, Any]]:
        """Neutral transcript -> Gemini `contents` (`user`/`model` roles; a tool result rides as a `user` functionResponse part).

        Args:
            messages (list[dict]): Neutral transcript messages.

        Returns:
            list[dict[str, Any]]: Gemini-shaped `contents` list.
        """
        contents = []
        for message in messages:
            role = message.get("role")
            if role == "user":
                contents.append({
                    "role": "user",
                    "parts": [{"text": str(message.get("content") or "")}],
                })
            elif role == "assistant":
                # Replay the model's own turn byte for byte when we kept it.
                # Gemini 3 stamps each functionCall part with a
                # `thoughtSignature` and rejects the follow-up request that
                # omits it — rebuilding the parts from name + args drops the
                # stamp and every tool-using turn 400s.
                original = message.get("provider_turn")
                if original and original.get("parts"):
                    contents.append({**original, "role": "model"})
                    continue

                parts = []
                text = message.get("content")
                if text:
                    parts.append({"text": str(text)})
                for call in message.get("tool_calls") or []:
                    parts.append({
                        "functionCall": {
                            "name": call.name,
                            "args": call.arguments or {},
                        }
                    })
                if parts:
                    contents.append({"role": "model", "parts": parts})
            elif role == "tool":
                payload = message.get("content")
                if not isinstance(payload, dict):
                    payload = {"result": payload}
                contents.append({
                    "role": "user",
                    "parts": [{
                        "functionResponse": {
                            "name": message.get("name") or "tool",
                            "response": payload,
                        }
                    }],
                })
        return contents

    @staticmethod
    def _to_declarations(tools: list[ToolSpec]) -> list[dict[str, Any]]:
        """Neutral tool specs -> Gemini `functionDeclarations`.

        Args:
            tools (list[ToolSpec]): Tools offered to the model.

        Returns:
            list[dict[str, Any]]: Gemini-shaped `tools` payload (one entry).
        """
        return [{
            "functionDeclarations": [
                {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": _clean_schema(tool.parameters),
                }
                for tool in tools
            ]
        }]

    # ── translation: Gemini -> ours ──────────────────────────────────────────

    @staticmethod
    def _to_reply(data: dict[str, Any]) -> ProviderReply:
        """Gemini response JSON -> neutral `ProviderReply`.

        Args:
            data (dict[str, Any]): Raw `generateContent` response body.

        Returns:
            ProviderReply: Text, tool calls, finish reason, and the raw candidate.
        """
        candidates = data.get("candidates") or []
        if not candidates:
            # A prompt blocked by safety filters comes back with no candidate.
            blocked = (data.get("promptFeedback") or {}).get("blockReason")
            raise ProviderError(
                f"The model returned no answer ({blocked or 'no candidates'})."
            )

        candidate = candidates[0]
        parts = (candidate.get("content") or {}).get("parts") or []

        text_chunks, calls = [], []
        for index, part in enumerate(parts):
            if "text" in part:
                text_chunks.append(part["text"])
            call = part.get("functionCall")
            if call:
                calls.append(ToolCall(
                    id=f"{call.get('name', 'call')}-{index}",
                    # Gemini sometimes namespaces the call ("default_api:foo").
                    # Registered tool names never contain a colon, so the last
                    # segment is always the real name.
                    name=(call.get("name") or "").split(":")[-1],
                    arguments=call.get("args") or {},
                ))

        raw_finish = (candidate.get("finishReason") or "STOP").upper()
        finish = "tool_calls" if calls else {
            "STOP": "stop", "MAX_TOKENS": "length",
        }.get(raw_finish, "stop")

        return ProviderReply(
            text="".join(text_chunks).strip(),
            tool_calls=calls,
            finish_reason=finish,
            raw=data,
            # Kept whole so the next request can replay it unmodified.
            provider_turn=candidate.get("content"),
        )

    # ── the call ─────────────────────────────────────────────────────────────

    def _post(self, model: str, payload: dict[str, Any], budget_end: float) -> dict[str, Any]:
        """POST one `generateContent` request, retrying on rate-limit/5xx/network errors.

        Args:
            model (str): Gemini model id to call.
            payload (dict[str, Any]): Request body.
            budget_end (float): `time.monotonic()` by which every attempt must be over;
                each request's timeout shrinks to fit, and no retry starts past it.

        Returns:
            dict[str, Any]: The parsed JSON response body.
        """
        url = f"{API_ROOT}/{model}:generateContent"
        # Key goes in a header, not the query string — a URL with the key in it
        # lands in access logs and error messages.
        headers = {"x-goog-api-key": self._api_key()}

        def wait_before_retry(attempt: int) -> bool:
            """Sleep before the next attempt; False when that would leave no budget for it."""
            delay = 1.5 * (attempt + 1)
            if budget_end - time.monotonic() - delay < _MIN_ATTEMPT_SECONDS:
                return False
            time.sleep(delay)
            return True

        last_error = None
        for attempt in range(3):
            remaining = budget_end - time.monotonic()
            if remaining < _MIN_ATTEMPT_SECONDS:
                break
            try:
                response = requests.post(
                    url, json=payload, headers=headers,
                    timeout=min(REQUEST_TIMEOUT_SECONDS, remaining),
                )
            except requests.RequestException as exc:
                last_error = f"request failed: {exc}"
                if not wait_before_retry(attempt):
                    break
                continue

            if response.status_code == 200:
                try:
                    return response.json()
                except json.JSONDecodeError as exc:
                    raise ProviderError(f"Model returned unreadable JSON: {exc}")

            if response.status_code == 429:
                last_error = (
                    "The model is rate-limited right now — give it a minute and "
                    "ask again."
                )
                if not wait_before_retry(attempt):
                    break
                continue

            if response.status_code >= 500:
                last_error = f"The model service is having trouble (HTTP {response.status_code})."
                if not wait_before_retry(attempt):
                    break
                continue

            raise ProviderError(
                f"Model error {response.status_code}: {response.text[:300]}"
            )

        raise ProviderError(last_error or "Model unreachable")

    def complete(self, *, system: str, messages: list[dict], tools: list[ToolSpec]) -> ProviderReply:
        """One turn against Gemini, with an automatic fallback-model retry, all within
        `REQUEST_TIMEOUT_SECONDS`.

        Args:
            system (str): System prompt for this turn.
            messages (list[dict]): Neutral transcript so far.
            tools (list[ToolSpec]): Tools offered to the model this turn.

        Returns:
            ProviderReply: The model's reply — text and/or tool calls.
        """
        payload = {
            "contents": self._to_contents(messages),
            "systemInstruction": {"parts": [{"text": system}]},
            "generationConfig": {"temperature": 0.2},
        }
        if tools:
            payload["tools"] = self._to_declarations(tools)

        self.downgraded = False
        budget_end = time.monotonic() + REQUEST_TIMEOUT_SECONDS
        try:
            data = self._post(self.model, payload, budget_end)
            self.last_model_used = self.model
        except ProviderError as primary_error:
            if not self.fallback_model or self.fallback_model == self.model:
                raise
            if budget_end - time.monotonic() < _MIN_ATTEMPT_SECONDS:
                raise
            logger.warning(
                "Assistant primary model %s failed (%s) — trying %s",
                self.model, primary_error, self.fallback_model,
            )
            data = self._post(self.fallback_model, payload, budget_end)
            self.last_model_used = self.fallback_model
            self.downgraded = True

        return self._to_reply(data)
