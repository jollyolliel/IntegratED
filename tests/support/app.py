"""Application fixture and deterministic replacements for external services."""

from __future__ import annotations

import functools
import logging
import os
import sys
import types
from typing import ClassVar

import werkzeug.security


class FakePosthogClient:
    """Small in-memory PostHog substitute that records event payloads."""

    instances: ClassVar[list[FakePosthogClient]] = []

    def __init__(self, *args, **kwargs):
        self.captures: list[dict] = []
        self.flushed = False
        self.__class__.instances.append(self)

    def capture(self, distinct_id=None, event=None, properties=None):
        self.captures.append(
            {
                "distinct_id": distinct_id,
                "event": event,
                "properties": properties or {},
            }
        )

    def flush(self):
        self.flushed = True


class _NoopLoggingHandler(logging.Handler):
    def emit(self, record):
        return None


def _install_external_fakes() -> None:
    # A ModuleType has no static attributes of its own — assigning fake
    # implementations onto it is exactly what a runtime module-swap needs,
    # and ty has no way to type-check that structurally.
    compress = types.ModuleType("flask_compress")
    compress.Compress = type("Compress", (), {"init_app": lambda self, app: None})  # ty: ignore[missing-attribute]
    sys.modules["flask_compress"] = compress

    posthog = types.ModuleType("posthog")
    posthog.Posthog = FakePosthogClient  # ty: ignore[missing-attribute]
    sys.modules["posthog"] = posthog

    module_names = [
        "opentelemetry",
        "opentelemetry._logs",
        "opentelemetry.sdk",
        "opentelemetry.sdk._logs",
        "opentelemetry.sdk._logs.export",
        "opentelemetry.exporter",
        "opentelemetry.exporter.otlp",
        "opentelemetry.exporter.otlp.proto",
        "opentelemetry.exporter.otlp.proto.http",
        "opentelemetry.exporter.otlp.proto.http._log_exporter",
    ]
    for name in module_names:
        sys.modules.setdefault(name, types.ModuleType(name))

    logs = sys.modules["opentelemetry._logs"]
    logs.set_logger_provider = lambda provider: None  # ty: ignore[missing-attribute]
    sdk_logs = sys.modules["opentelemetry.sdk._logs"]
    sdk_logs.LoggerProvider = type(  # ty: ignore[missing-attribute]
        "FakeLoggerProvider",
        (),
        {
            "add_log_record_processor": lambda self, processor: None,
            "shutdown": lambda self: None,
        },
    )
    sdk_logs.LoggingHandler = _NoopLoggingHandler  # ty: ignore[missing-attribute]
    sdk_export = sys.modules["opentelemetry.sdk._logs.export"]
    sdk_export.BatchLogRecordProcessor = type(  # ty: ignore[missing-attribute]
        "FakeBatchLogRecordProcessor", (), {"__init__": lambda self, exporter: None}
    )
    exporter = sys.modules["opentelemetry.exporter.otlp.proto.http._log_exporter"]
    exporter.OTLPLogExporter = type(  # ty: ignore[missing-attribute]
        "FakeOTLPLogExporter", (), {"__init__": lambda self, endpoint=None: None}
    )


def configure_test_environment() -> None:
    """Set import-time configuration before importing ``main``."""

    os.environ["SECRET_KEY"] = "test-secret-key"
    os.environ["GOOGLE_CLIENT_ID"] = "test-client-id"
    os.environ["GOOGLE_CLIENT_SECRET"] = "test-client-secret"
    os.environ["APP_ENV"] = "development"
    # Shared in-memory SQLite keeps the schema alive when SQLAlchemy returns a
    # connection to its pool between Flask application contexts.
    os.environ["TEST_DATABASE_URL"] = (
        "sqlite:///file:test_suite?mode=memory&cache=shared&uri=true"
    )
    os.environ["POSTHOG_API_KEY"] = ""
    _install_external_fakes()

    # The production password method is intentionally expensive. This remains
    # a real salted KDF and still verifies wrong passwords; it only removes the
    # stretching cost that is unrelated to application behavior in tests.
    werkzeug.security.generate_password_hash = functools.partial(  # ty: ignore[invalid-assignment]
        werkzeug.security.generate_password_hash, method="pbkdf2:sha256:1"
    )


def use_environment(app, monkeypatch, env: str, **overrides) -> None:
    """Run the rest of the test as if `APP_ENV` were `env`, with any settings fields overridden.

    Args:
        app: The Flask app fixture.
        monkeypatch: pytest's monkeypatch, which restores the real settings afterwards.
        env (str): An `Environment` value, e.g. "production".
        **overrides: Settings fields to replace, e.g. `database_url="postgresql://..."`.
    """
    from dataclasses import replace

    from settings import Environment

    monkeypatch.setitem(app.config, "SETTINGS", replace(app.config["SETTINGS"], env=Environment(env), **overrides))
