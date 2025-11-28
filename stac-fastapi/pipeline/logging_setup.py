import logging
import sys
from logging.handlers import RotatingFileHandler
from os import getenv
from pathlib import Path

import structlog


def setup_logging():
    """Set up structured logging with structlog + standard logging."""
    log_level_str = getenv("LOG_LEVEL", "INFO").upper()
    numeric_level = getattr(logging, log_level_str, logging.INFO)

    log_dir = Path(__file__).parent / "logs"
    log_dir.mkdir(exist_ok=True)
    log_path = str(log_dir / "app.log")

    file_handler = RotatingFileHandler(
        log_path,
        mode="a",
        maxBytes=10 * 1024 * 1024,  # 10 MB for development
        backupCount=5,
        encoding="utf-8",
    )
    stream_handler = logging.StreamHandler(sys.stdout)

    # Python standard logging configuration
    logging.basicConfig(
        level=numeric_level,
        format="%(message)s",  # structlog handles formatting
        handlers=[file_handler, stream_handler],
    )

    # structlog configuration
    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    logger = structlog.get_logger()
    logger.info("Logging initialized", log_file=log_path)
    return structlog.get_logger()


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
