"""Guard for operator-configured table names interpolated into SQL."""

from __future__ import annotations

import re

_TABLE_NAME = re.compile(r"^[a-zA-Z0-9_.]+$")


def checked_table_name(name: str) -> str:
    """Return *name* unchanged, or raise ValueError if it is not a plain identifier.

    Table names come from env config, never from requests, but are still
    interpolated into SQL, so anything beyond ``schema.table`` is refused.
    """
    if not _TABLE_NAME.match(name):
        raise ValueError(f"Table name contains disallowed characters: {name!r}")
    return name
