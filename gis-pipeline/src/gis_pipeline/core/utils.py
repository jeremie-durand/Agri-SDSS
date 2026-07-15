import hashlib
import re

import structlog
from gis_pipeline.core.config import Config
from gis_pipeline.core.logging_setup import handle_error

logger = structlog.get_logger()


def harmonize_name(name: str, pattern: str, max_len: int) -> str:
    """Normalize a string to a PostgreSQL-compatible identifier.

    Lowercases the input, replaces invalid characters via regex, and appends an
    MD5 hash suffix when the result exceeds ``max_len``.

    Args:
        name: The original name to harmonize.
        pattern: Regex pattern whose matches are replaced with ``_``.
        max_len: Maximum allowed length for the returned identifier.

    Returns:
        A harmonized, PostgreSQL-compatible identifier.

    Raises:
        ValueError: If ``name`` is empty or whitespace-only.
    """
    if not name.strip():
        error_msg = f"Name must not be empty or whitespace. Received: '{name}'"
        handle_error(logger=logger, error_msg=error_msg, exc_class=ValueError)

    clean_name = re.sub(pattern, Config.HASH_SEPARATOR, name.lower()).strip(
        Config.HASH_SEPARATOR
    )

    if len(clean_name) > max_len:
        h = hashlib.md5(clean_name.encode()).hexdigest()[: Config.HASH_HEX_LENGTH]
        available_length = max_len - Config.HASH_SUFFIX_LENGTH
        if available_length > 0:
            clean_name = f"{clean_name[:available_length]}{Config.HASH_SEPARATOR}{h}"
        else:
            clean_name = h[:max_len]

    return clean_name
