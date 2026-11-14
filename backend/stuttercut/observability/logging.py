"""JSON Lines logging to a rotating file (one object per line).

Context such as job_id or step goes in ``extra={...}``; every extra key becomes a JSON field.
"""

import json
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from stuttercut.config import LogConfig

LOG_FILE = "app.jsonl"
# Attributes every LogRecord has; anything else on a record came from ``extra``.
_STANDARD = set(logging.makeLogRecord({}).__dict__) | {"message", "asctime", "taskName"}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, object] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S") + f".{int(record.msecs):03d}",
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        entry.update({k: v for k, v in record.__dict__.items() if k not in _STANDARD})
        if record.exc_info:
            entry["exc"] = self.formatException(record.exc_info)
        return json.dumps(entry, ensure_ascii=False, default=str)


def setup_logging(log_dir: Path, cfg: LogConfig) -> Path:
    """Attach the rotating JSON Lines handler to the ``stuttercut`` logger (idempotent)."""
    log_dir.mkdir(parents=True, exist_ok=True)
    path = log_dir / LOG_FILE
    logger = logging.getLogger("stuttercut")
    logger.setLevel(cfg.level)
    for handler in list(logger.handlers):
        if getattr(handler, "_stuttercut", False):
            logger.removeHandler(handler)
            handler.close()
    handler = RotatingFileHandler(
        path, maxBytes=cfg.max_bytes, backupCount=cfg.backup_count, encoding="utf-8"
    )
    handler.setFormatter(JsonFormatter())
    handler._stuttercut = True  # type: ignore[attr-defined]
    logger.addHandler(handler)
    return path
