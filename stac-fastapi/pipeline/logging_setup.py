import logging
import os
import sys

import structlog


def setup_logging():
    """Set up structured logging with structlog + standard logging."""
    log_level_str = os.getenv("LOG_LEVEL", "INFO").upper()
    numeric_level = getattr(logging, log_level_str, logging.INFO)

    # Python standard logging configuration
    logging.basicConfig(
        level=numeric_level,
        format="%(message)s",  # structlog handles formatting
        stream=sys.stdout,
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
