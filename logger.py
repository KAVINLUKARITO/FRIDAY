from __future__ import annotations

import logging
import sys
from pathlib import Path

from config import settings

_FORMAT = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
_DATE_FORMAT = "%Y-%m-%dT%H:%M:%S%z"


def get_logger(name: str) -> logging.Logger:
    """Return a logger configured for stdout and runtime file logging."""

    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, settings.log_level, logging.INFO))
    logger.propagate = False

    runtime_dir = settings.db_path.parent.resolve()
    runtime_dir.mkdir(parents=True, exist_ok=True)
    log_path = Path(runtime_dir, "agent.log")
    formatter = logging.Formatter(_FORMAT, datefmt=_DATE_FORMAT)

    if not any(
        isinstance(handler, logging.StreamHandler)
        and getattr(handler, "stream", None) is sys.stdout
        for handler in logger.handlers
    ):
        stream_handler = logging.StreamHandler(sys.stdout)
        stream_handler.setLevel(logger.level)
        stream_handler.setFormatter(formatter)
        logger.addHandler(stream_handler)

    if not any(
        isinstance(handler, logging.FileHandler)
        and Path(getattr(handler, "baseFilename", "")) == log_path.resolve()
        for handler in logger.handlers
    ):
        file_handler = logging.FileHandler(log_path, encoding="utf-8")
        file_handler.setLevel(logger.level)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    return logger
