"""
Reads a PostgreSQL plain-SQL dump from stdin and writes only the
COPY blocks for the 'public' schema to stdout.

Usage:
    gunzip -c dump.sql.gz | python3 filter_public_copy.py | psql ...
"""

import sys

in_public_copy = False
copy_end = "\\."

for raw_line in sys.stdin.buffer:
    line = raw_line.decode("utf-8", errors="replace")
    stripped = line.rstrip("\n\r")

    if stripped.startswith("COPY public.") and "FROM stdin" in stripped:
        in_public_copy = True
        sys.stdout.write(line)
    elif stripped.startswith("COPY "):
        in_public_copy = False
    elif stripped == copy_end:
        if in_public_copy:
            sys.stdout.write(line)
        in_public_copy = False
    elif in_public_copy:
        sys.stdout.write(line)
