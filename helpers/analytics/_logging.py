import atexit
import json
import logging
import sys
import threading
from typing import Any

# Opentelemetry imports are now assumed to be present as per pyproject.toml
from opentelemetry import _logs as logs
from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor

from helpers.analytics import analytics_enabled, posthog_client
from helpers.analytics._capture import capture_exception
from settings import get_settings

logger_provider = None
_logging_initialized = False
_atexit_registered = False
_module_logger = logging.getLogger(__name__)


def log_info(message: str, **extra: Any) -> None:
    """Log an INFO message with extra structured fields.

    Args:
        message (str): Log message.
        **extra: Extra fields attached to the log record.

    Returns:
        None
    """
    logging.getLogger(__name__).info(message, extra=extra)


def log_warning(message: str, **extra: Any) -> None:
    """Log a WARNING message with extra structured fields.

    Args:
        message (str): Log message.
        **extra: Extra fields attached to the log record.

    Returns:
        None
    """
    logging.getLogger(__name__).warning(message, extra=extra)


def log_error(message: str, **extra: Any) -> None:
    """Log an ERROR message with extra structured fields.

    Args:
        message (str): Log message.
        **extra: Extra fields attached to the log record.

    Returns:
        None
    """
    logging.getLogger(__name__).error(message, extra=extra)


def flush_analytics() -> None:
    """Flush pending OpenTelemetry log records and PostHog events.

    Returns:
        None
    """
    global _logging_initialized
    if logger_provider and hasattr(logger_provider, "shutdown"):
        try:
            logger_provider.shutdown()
        except Exception as exc:  # noqa: BLE001 - best-effort shutdown flush, exporter surface is unbounded
            _module_logger.debug("OTel logger provider shutdown failed: %s", exc)
    try:
        posthog_client().flush()
    except Exception as exc:  # noqa: BLE001 - best-effort shutdown flush, SDK surface is unbounded
        _module_logger.debug("PostHog flush on shutdown failed: %s", exc)
    _logging_initialized = False


class _GcpJsonFormatter(logging.Formatter):
    """Structured JSON lines so Cloud Logging parses severity — plain-text logs
    land as severity DEFAULT and are invisible to severity>=ERROR filters/alerts."""

    def format(self, record: logging.LogRecord) -> str:
        """Render a log record as a single JSON line.

        Args:
            record (logging.LogRecord): The record to format.

        Returns:
            str: JSON with `severity`, `message`, `logger`, `time`, and
                `exception` if present.
        """
        entry = {
            "severity": record.levelname,
            "message": record.getMessage(),
            "logger": record.name,
            "time": self.formatTime(record),
        }
        if record.exc_info:
            entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(entry, ensure_ascii=False, default=str)


def init_logging() -> None:
    """Set up console + OpenTelemetry logging and global exception capture.

    Idempotent — safe to call more than once. Wires up: a `LoggerProvider`
    with a `BatchLogRecordProcessor` + `OTLPLogExporter`, a `logging` handler
    attached to the root logger, an `atexit` flush, and global + threading
    exception hooks that route uncaught exceptions to `capture_exception()`.

    Returns:
        None
    """
    global logger_provider, _logging_initialized, _atexit_registered

    if _logging_initialized:
        return

    # Ensure a console handler exists regardless of analytics status
    root_logger = logging.getLogger()
    if not any(isinstance(h, logging.StreamHandler) for h in root_logger.handlers):
        console_handler = logging.StreamHandler()
        if get_settings().is_production:
            console_handler.setFormatter(_GcpJsonFormatter())
        else:
            console_handler.setFormatter(logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
            ))
        root_logger.addHandler(console_handler)

    if analytics_enabled():
        logger_provider = LoggerProvider()
        logs.set_logger_provider(logger_provider)

        settings = get_settings()
        otlp_endpoint = f"{settings.posthog_host.rstrip('/')}/i/v1/logs?token={settings.posthog_api_key}"
        otlp_exporter = OTLPLogExporter(endpoint=otlp_endpoint)
        logger_provider.add_log_record_processor(BatchLogRecordProcessor(otlp_exporter))

        root_logger.addHandler(LoggingHandler())
        root_logger.setLevel(logging.INFO)
    else:
        root_logger.setLevel(logging.INFO)

    def global_exception_handler(exc_type: type[BaseException], exc_value: BaseException, exc_traceback: Any) -> None:
        """`sys.excepthook` replacement: logs and reports every unhandled exception.

        Args:
            exc_type (type[BaseException]): Exception class.
            exc_value (BaseException): Exception instance.
            exc_traceback (Any): Traceback object.

        Returns:
            None
        """
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
            return

        logging.getLogger(__name__).error(
            "Unhandled exception", exc_info=(exc_type, exc_value, exc_traceback)
        )
        capture_exception(
            None,
            exc_value,
            properties={"unhandled": True},
            tb=(exc_type, exc_value, exc_traceback),
        )

    sys.excepthook = global_exception_handler

    if hasattr(threading, "excepthook"):
        def thread_exception_handler(args: Any) -> None:
            """`threading.excepthook` replacement: logs and reports thread exceptions.

            Args:
                args (Any): The `threading.ExceptHookArgs` passed by the runtime.

            Returns:
                None
            """
            logging.getLogger(__name__).error(
                "Unhandled exception in thread %s",
                getattr(args.thread, "name", "unknown"),
                exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
            )
            capture_exception(
                None,
                args.exc_value,
                properties={
                    "unhandled": True,
                    "thread_name": getattr(args.thread, "name", "unknown"),
                },
                tb=(args.exc_type, args.exc_value, args.exc_traceback),
            )
            try:
                posthog_client().flush()
            except Exception as exc:  # noqa: BLE001 - best-effort flush after an unhandled thread exception, SDK surface is unbounded
                _module_logger.debug("PostHog flush after thread exception failed: %s", exc)

        threading.excepthook = thread_exception_handler

    if not _atexit_registered:
        atexit.register(flush_analytics)
        _atexit_registered = True

    _logging_initialized = True
