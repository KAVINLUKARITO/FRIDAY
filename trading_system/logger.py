from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from threading import Lock

from config import settings

_LOGGER_LOCK = Lock()
_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"


def get_logger(name: str) -> logging.Logger:
    with _LOGGER_LOCK:
        logger = logging.getLogger(name)
        logger.setLevel(getattr(logging, settings.log_level, logging.INFO))
        logger.propagate = False

        settings.log_path.parent.mkdir(parents=True, exist_ok=True)
        formatter = logging.Formatter(_FORMAT)

        has_stream = any(
            isinstance(handler, logging.StreamHandler)
            and getattr(handler, "stream", None) is sys.stdout
            for handler in logger.handlers
        )
        if not has_stream:
            stream_handler = logging.StreamHandler(sys.stdout)
            stream_handler.setLevel(logger.level)
            stream_handler.setFormatter(formatter)
            logger.addHandler(stream_handler)

        resolved_log_path = str(settings.log_path.resolve())
        has_file = any(
            isinstance(handler, RotatingFileHandler)
            and getattr(handler, "baseFilename", None) == resolved_log_path
            for handler in logger.handlers
        )
        if not has_file:
            file_handler = RotatingFileHandler(
                settings.log_path,
                maxBytes=10 * 1024 * 1024,
                backupCount=5,
                encoding="utf-8",
            )
            file_handler.setLevel(logger.level)
            file_handler.setFormatter(formatter)
            logger.addHandler(file_handler)

        return logger
