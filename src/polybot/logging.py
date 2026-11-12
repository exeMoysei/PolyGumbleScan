"""Structured JSON logs with secret masking (bot tokens, API keys, long chat ids)."""

from __future__ import annotations

import json
import logging
import re
import sys
from datetime import UTC, datetime
from typing import Any

_PATTERNS = [
    (re.compile(r"\b\d{6,12}:[A-Za-z0-9_-]{30,}\b"), "<bot-token>"),
    (
        re.compile(r"(apiKey|api_key|token|password|secret)([\"']?\s*[=:]\s*[\"']?)[^&\s\"',}]+", re.IGNORECASE),
        r"\1\2***",
    ),
    (re.compile(r"(postgres(?:ql)?(?:\+asyncpg)?://[^:/\s]+:)[^@\s]+@"), r"\1***@"),
]
_STD = set(vars(logging.LogRecord("", 0, "", 0, "", (), None)).keys()) | {"message", "asctime"}


def mask(text: str) -> str:
    for rx, repl in _PATTERNS:
        text = rx.sub(repl, text)
    return text


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        doc: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": mask(record.getMessage()),
        }
        for k, v in record.__dict__.items():
            if k not in _STD and not k.startswith("_"):
                doc[k] = v
        if record.exc_info:
            doc["exc"] = mask(self.formatException(record.exc_info))
        return mask(json.dumps(doc, default=str, ensure_ascii=False))


class MaskingFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return mask(super().format(record))


def setup_logging(level: str = "INFO", json_logs: bool = True) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        JsonFormatter() if json_logs else MaskingFormatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    )
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level.upper())
    for noisy in ("httpx", "httpcore", "aiogram.event", "asyncio"):
        logging.getLogger(noisy).setLevel("WARNING")
