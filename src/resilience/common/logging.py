"""Structured logging setup shared by every pipeline stage.

Emits one JSON object per line (region, stage, and message are always
present) so pipeline runs can be grepped/parsed the same way whether they
run on a laptop or in a container.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from typing import Any


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        extra = getattr(record, "context", None)
        if extra:
            payload.update(extra)
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(level: str = "INFO") -> None:
    """Idempotently configure the root logger to emit structured JSON to stdout."""
    root = logging.getLogger()
    root.setLevel(level)
    if any(isinstance(h, logging.StreamHandler) for h in root.handlers):
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(_JsonFormatter())
    root.addHandler(handler)


class StructuredLogger:
    """Thin wrapper so call sites can pass `context={...}` without fighting
    stdlib logging's `extra=` plumbing (which forbids reserved keys and does
    not merge nested dicts on its own)."""

    def __init__(self, logger: logging.Logger) -> None:
        self._logger = logger

    def _log(self, level: int, msg: str, context: dict[str, Any] | None, exc_info: bool = False) -> None:
        self._logger.log(level, msg, extra={"context": context or {}}, exc_info=exc_info)

    def debug(self, msg: str, context: dict[str, Any] | None = None) -> None:
        self._log(logging.DEBUG, msg, context)

    def info(self, msg: str, context: dict[str, Any] | None = None) -> None:
        self._log(logging.INFO, msg, context)

    def warning(self, msg: str, context: dict[str, Any] | None = None) -> None:
        self._log(logging.WARNING, msg, context)

    def error(self, msg: str, context: dict[str, Any] | None = None, exc_info: bool = False) -> None:
        self._log(logging.ERROR, msg, context, exc_info=exc_info)


def get_logger(name: str) -> StructuredLogger:
    return StructuredLogger(logging.getLogger(name))
