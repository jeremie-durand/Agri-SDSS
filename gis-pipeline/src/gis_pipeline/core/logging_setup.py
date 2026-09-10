import logging
import sys
from logging.handlers import RotatingFileHandler
from os import getenv
from pathlib import Path

import structlog
from gis_pipeline.core.config import Config


def setup_logging():
    """Configure structlog and file logging, then return a structlog logger."""
    log_level_str = getenv("LOG_LEVEL", "INFO").upper()
    numeric_level = getattr(logging, log_level_str, logging.INFO)

    log_dir = Path(Config.LOG_DIR)
    log_dir.mkdir(parents=True, exist_ok=True)

    log_path = log_dir / "app.log"

    formatter = structlog.stdlib.ProcessorFormatter(
        processor=structlog.dev.ConsoleRenderer(pad_level=False),
        foreign_pre_chain=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
        ],
    )

    handlers: list[logging.Handler] = []
    try:
        file_handler = RotatingFileHandler(
            log_path,
            mode="a",
            maxBytes=10 * 1024 * 1024,
            backupCount=5,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        handlers.append(file_handler)
    except PermissionError:
        pass  # log directory not writable (e.g. CI bind mount owned by root)

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)
    handlers.append(stream_handler)

    root_logger = logging.getLogger()
    root_logger.setLevel(numeric_level)
    for handler in handlers:
        root_logger.addHandler(handler)

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(numeric_level),
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    logger = structlog.get_logger()
    logger.info("Logging initialized", log_file=str(log_path))
    return logger


def handle_error(
    logger: structlog.BoundLogger,
    error_msg: str,
    exc_class: type[Exception] = RuntimeError,
) -> None:
    """
    Log an error message and raise an exception.

    Args:
        error_msg: The message describing the error.
        exc_class: The exception class to raise (default: RuntimeError).
    """
    logger.exception(error_msg)
    raise exc_class(error_msg)
