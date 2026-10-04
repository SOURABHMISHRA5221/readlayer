"""JSON structured logging for Cloud Logging, with request-scoped context.

Log lines carry `request_id` and a pseudonymous `uid_hash`; never emails, tokens or article text.
"""

import hashlib
import hmac
import json
import logging
import sys
from contextvars import ContextVar
from datetime import UTC, datetime

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)
uid_hash_var: ContextVar[str | None] = ContextVar("uid_hash", default=None)

# Attributes every LogRecord has; anything else passed via `extra=` is emitted as a field.
_RESERVED = set(vars(logging.makeLogRecord({}))) | {"message", "asctime", "taskName"}


def hash_uid(uid: str, salt: str) -> str:
    """Stable, salted, non-reversible id for logs."""
    return hmac.new(salt.encode(), uid.encode(), hashlib.sha256).hexdigest()[:16]


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, object] = {
            "severity": record.levelname,
            "message": record.getMessage(),
            "time": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "logger": record.name,
            "request_id": request_id_var.get(),
            "uid_hash": uid_hash_var.get(),
        }
        entry.update({k: v for k, v in vars(record).items() if k not in _RESERVED})
        if record.exc_info:
            entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(entry, default=str)


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)
    # LiteLLM is chatty at INFO and may echo prompts; keep it to warnings.
    for noisy in ("LiteLLM", "litellm", "httpx"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
