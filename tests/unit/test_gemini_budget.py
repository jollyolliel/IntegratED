"""One Gemini `complete()` call — retries and fallback included — fits in one request timeout.

`loop.TURN_DEADLINE_SECONDS` is only checked between calls, so the worst case of a turn is the
deadline plus one whole call; that sum has to stay inside gunicorn's `--timeout 60`.
"""

from __future__ import annotations

import pytest
import requests

pytestmark = pytest.mark.unit


class _Clock:
    def __init__(self):
        self.now = 1000.0

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


@pytest.fixture
def clock(monkeypatch):
    from helpers.ai import gemini

    fake = _Clock()
    monkeypatch.setattr(gemini.time, "monotonic", fake.monotonic)
    monkeypatch.setattr(gemini.time, "sleep", fake.sleep)
    monkeypatch.setenv("GEMINI_AISTUDIO_API_KEY", "test-key")
    return fake


def test_a_hanging_model_gives_up_within_one_request_timeout(clock, monkeypatch):
    from helpers.ai import gemini
    from helpers.ai.provider import ProviderError

    timeouts = []

    def hang(url, *, json, headers, timeout):
        timeouts.append(timeout)
        clock.now += timeout
        raise requests.Timeout("read timed out")

    monkeypatch.setattr(gemini.requests, "post", hang)
    provider = gemini.GeminiProvider(model="primary", fallback_model="backup")
    started = clock.now

    with pytest.raises(ProviderError):
        provider.complete(system="s", messages=[{"role": "user", "content": "hi"}], tools=[])

    assert clock.now - started <= gemini.REQUEST_TIMEOUT_SECONDS
    assert all(t > 0 for t in timeouts)


def test_a_server_error_still_retries_while_time_remains(clock, monkeypatch):
    from helpers.ai import gemini

    class _Reply:
        def __init__(self, status):
            self.status_code = status
            self.text = ""

        def json(self):
            return {"candidates": [{"content": {"parts": [{"text": "hello"}]}}]}

    replies = iter([_Reply(503), _Reply(200)])
    monkeypatch.setattr(gemini.requests, "post", lambda *a, **k: next(replies))
    provider = gemini.GeminiProvider(model="primary", fallback_model="backup")

    reply = provider.complete(system="s", messages=[{"role": "user", "content": "hi"}], tools=[])

    assert reply.text == "hello"
    assert provider.last_model_used == "primary"
