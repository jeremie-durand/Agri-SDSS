"""CI gate for the gettext catalogs. Run with ``make i18n-check``.

Three failures are caught here because none of them break a test or a build:

1. A new ``_()`` call whose msgid never reached the catalogs, so the message
   silently never translates.
2. An empty or fuzzy ``msgstr``, so a translated locale falls back to English
   for that one message.
3. A non-literal argument to ``_()`` -- typically an f-string. pybabel extracts
   msgids statically, so ``_(f"...")`` yields no catalog entry at all and fails
   silently at runtime. This is the easiest mistake to make and the hardest to
   notice, which is why it is a build failure.

Authoring tool: not copied into any runtime image.
"""

from __future__ import annotations

import ast
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Iterator, List, Tuple

ROOT = Path(__file__).resolve().parent.parent
BABEL_CFG = ROOT / "agri_i18n" / "babel.cfg"
LOCALES = ROOT / "agri_i18n" / "locales"

TRANSLATION_FUNCS = {"_", "gettext", "ngettext"}
# ngettext takes both a singular and a plural msgid.
LITERAL_ARG_COUNT = {"_": 1, "gettext": 1, "ngettext": 2}


def _extraction_roots() -> List[Path]:
    """Return the directories babel.cfg scans, so both agree on one source."""
    roots = []
    for line in BABEL_CFG.read_text().splitlines():
        match = re.match(r"^\[python:\s*(.+?)\]", line.strip())
        if match:
            pattern = match.group(1)
            roots.append(ROOT / pattern.split("/**")[0])
    return roots


def _python_files() -> Iterator[Path]:
    """Yield every source file subject to extraction."""
    for root in _extraction_roots():
        yield from sorted(root.rglob("*.py"))


def check_no_dynamic_msgids() -> List[str]:
    """Report every ``_()`` call whose msgid is not a literal string."""
    errors = []
    for path in _python_files():
        try:
            tree = ast.parse(path.read_text(), filename=str(path))
        except SyntaxError as exc:
            errors.append(f"{path.relative_to(ROOT)}: cannot parse ({exc})")
            continue

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = (
                func.id
                if isinstance(func, ast.Name)
                else func.attr if isinstance(func, ast.Attribute) else None
            )
            if name not in TRANSLATION_FUNCS:
                continue

            for index in range(LITERAL_ARG_COUNT[name]):
                if index >= len(node.args):
                    continue
                arg = node.args[index]
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    continue
                kind = (
                    "f-string"
                    if isinstance(arg, ast.JoinedStr)
                    else type(arg).__name__
                )
                errors.append(
                    f"{path.relative_to(ROOT)}:{arg.lineno}: {name}() argument "
                    f"{index + 1} is a {kind}, not a literal string. pybabel "
                    f"cannot extract it, so it will never translate. Use "
                    f'_("... {{name}}").format(name=value) instead.'
                )
    return errors


def _msgids(po_path: Path) -> set:
    """Return the msgids in a .po/.pot file, ignoring formatting and headers."""
    from babel.messages.pofile import read_po

    with open(po_path, "rb") as handle:
        return {message.id for message in read_po(handle) if message.id}


def _source_msgids() -> Tuple[set, List[str]]:
    """Extract msgids from the source tree into a throwaway .pot.

    The .pot is a build intermediate for ``pybabel update``, not a committed
    artifact, so it is regenerated here rather than read from disk.
    """
    with tempfile.TemporaryDirectory() as tmp:
        pot = Path(tmp) / "messages.pot"
        result = subprocess.run(
            [
                "pybabel", "extract",
                "-F", str(BABEL_CFG),
                "--omit-header",
                "-o", str(pot),
                ".",
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            return set(), [f"pybabel extract failed:\n{result.stderr}"]
        return _msgids(pot), []


def check_catalogs_cover_source() -> List[str]:
    """Report msgids in the source that no catalog carries, and vice versa.

    Compares msgid sets rather than file bytes: different Babel versions wrap
    and order catalogs differently, and that formatting drift is not a defect.
    What matters is that no message escapes translation.
    """
    in_source, errors = _source_msgids()
    if errors:
        return errors

    catalogs = sorted(LOCALES.glob("*/LC_MESSAGES/messages.po"))
    if not catalogs:
        return [f"no catalogs found under {LOCALES.relative_to(ROOT)}"]

    for po_path in catalogs:
        rel = po_path.relative_to(ROOT)
        translated = _msgids(po_path)
        for msgid in sorted(in_source - translated):
            errors.append(f"{rel}: missing msgid from source: {msgid!r}")
        for msgid in sorted(translated - in_source):
            errors.append(f"{rel}: stale msgid no longer in source: {msgid!r}")

    if errors:
        errors.append("Run: make i18n-update (then translate any new entries)")
    return errors


def check_catalogs_complete() -> List[str]:
    """Report untranslated or fuzzy entries in every shipped catalog."""
    from babel.messages.pofile import read_po

    errors = []
    for po_path in sorted(LOCALES.glob("*/LC_MESSAGES/messages.po")):
        with open(po_path, "rb") as handle:
            catalog = read_po(handle)
        rel = po_path.relative_to(ROOT)
        for message in catalog:
            if not message.id:
                continue
            if not message.string:
                errors.append(f"{rel}: untranslated msgid {message.id!r}")
            elif "fuzzy" in message.flags:
                errors.append(f"{rel}: fuzzy msgid {message.id!r} needs review")
    return errors


def main() -> int:
    """Run every check, reporting all failures rather than the first."""
    checks: List[Tuple[str, List[str]]] = [
        ("no dynamic msgids", check_no_dynamic_msgids()),
        ("catalogs cover the source", check_catalogs_cover_source()),
        ("catalogs fully translated", check_catalogs_complete()),
    ]

    failed = False
    for label, errors in checks:
        if errors:
            failed = True
            print(f"FAIL  {label}", file=sys.stderr)
            for error in errors:
                print(f"      {error}", file=sys.stderr)
        else:
            print(f"ok    {label}")

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
