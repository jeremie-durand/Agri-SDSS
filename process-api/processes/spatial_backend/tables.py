"""Guards for operator-configured table and column names interpolated into SQL."""

from __future__ import annotations

import re

from ..config import COLUMN_NAME_PATTERN

_TABLE_NAME = re.compile(r"^[a-zA-Z0-9_.]+$")
_COLUMN_NAME = re.compile(COLUMN_NAME_PATTERN)


def checked_table_name(name: str) -> str:
    """Return *name* unchanged, or raise ValueError if it is not a plain identifier.

    Table names come from env config, never from requests, but are still
    interpolated into SQL, so anything beyond ``schema.table`` is refused.
    """
    if not _TABLE_NAME.match(name):
        raise ValueError(f"Table name contains disallowed characters: {name!r}")
    return name


def checked_column_name(name: str) -> str:
    """Return *name* unchanged, or raise ValueError if it is not a lowercase identifier.

    The name goes into SQL unquoted, and PostgreSQL folds unquoted names to
    lowercase, so a mixed-case column could never be found.
    """
    if not _COLUMN_NAME.match(name):
        raise ValueError(f"Column name is not a lowercase SQL identifier: {name!r}")
    return name
