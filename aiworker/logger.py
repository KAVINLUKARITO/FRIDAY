from __future__ import annotations

import logging
import sys
from pathlib import Path

from config import settings

LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"


def get_logger(name: str) -> logging.Logger:
    """Return a configured logger with stdout and file handlers."""

    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, settings.log_level, logging.INFO))
    logger.propagate = False

    runtime_dir = settings.db_path.parent.resolve()
    runtime_dir.mkdir(parents=True, exist_ok=True)
    log_path = Path(runtime_dir, "agent.log").resolve()
    formatter = logging.Formatter(LOG_FORMAT)

    has_stdout = any(
        isinstance(handler, logging.StreamHandler)
        and getattr(handler, "stream", None) is sys.stdout
        for handler in logger.handlers
    )
    if not has_stdout:
        stdout_handler = logging.StreamHandler(sys.stdout)
        stdout_handler.setFormatter(formatter)
        stdout_handler.setLevel(logger.level)
        logger.addHandler(stdout_handler)

    has_file = any(
        isinstance(handler, logging.FileHandler)
        and Path(getattr(handler, "baseFilename", "")).resolve() == log_path
        for handler in logger.handlers
    )
    if not has_file:
        file_handler = logging.FileHandler(log_path, encoding="utf-8")
        file_handler.setFormatter(formatter)
        file_handler.setLevel(logger.level)
        logger.addHandler(file_handler)

    return logger
