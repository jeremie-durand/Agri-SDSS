"""Shared gettext helpers for Agri-SDSS backend services.

User-facing messages are written in English at the call site, which makes the
English source string the msgid. Only non-English catalogs are shipped; an
English request falls through to the untranslated msgid.

The active locale lives in a :class:`contextvars.ContextVar` so concurrent
requests never share state. ``gettext.install()`` and a process-global ``_``
must not be used: they are process-wide and would leak one request's language
into another.
"""

from __future__ import annotations

import gettext as _gettext
from contextlib import contextmanager
from contextvars import ContextVar, Token
from pathlib import Path
from typing import Iterator, List, Optional, Tuple

DOMAIN = "messages"
LOCALE_DIR = Path(__file__).resolve().parent / "locales"

SUPPORTED: Tuple[str, ...] = ("fr", "en")
DEFAULT = "fr"

_locale: ContextVar[str] = ContextVar("agri_i18n_locale", default=DEFAULT)
_catalogs: dict[str, _gettext.NullTranslations] = {}


def clear_cache() -> None:
    """Drop memoised catalogs so a changed ``LOCALE_DIR`` takes effect."""
    _catalogs.clear()


def _catalog(code: str) -> _gettext.NullTranslations:
    """Return the catalog for ``code``, falling back to untranslated msgids."""
    cached = _catalogs.get(code)
    if cached is not None:
        return cached
    catalog = _gettext.translation(
        DOMAIN, localedir=str(LOCALE_DIR), languages=[code], fallback=True
    )
    _catalogs[code] = catalog
    return catalog


def _parse_accept_language(header: str) -> List[str]:
    """Return the header's language codes ordered by descending quality.

    Args:
        header: Raw ``Accept-Language`` value, e.g. ``"fr-CA,fr;q=0.9,en;q=0.8"``.

    Returns:
        Lower-cased language tags, best match first. Entries with ``q=0`` or an
        unparsable quality are dropped.
    """
    ranked: List[Tuple[float, int, str]] = []
    for index, part in enumerate(header.split(",")):
        token = part.strip()
        if not token:
            continue
        tag, _sep, params = token.partition(";")
        tag = tag.strip().lower()
        if not tag:
            continue
        quality = 1.0
        for param in params.split(";"):
            key, sep, value = param.partition("=")
            if sep and key.strip().lower() == "q":
                try:
                    quality = float(value.strip())
                except ValueError:
                    quality = 0.0
        if quality > 0:
            ranked.append((-quality, index, tag))
    ranked.sort()
    return [tag for _quality, _index, tag in ranked]


def normalize(tag: Optional[str]) -> Optional[str]:
    """Reduce a language tag to a supported code, or ``None`` if unsupported.

    ``fr-CA``, ``FR`` and ``fr`` all normalise to ``fr``.
    """
    if not tag:
        return None
    primary = tag.strip().lower().replace("_", "-").split("-")[0]
    return primary if primary in SUPPORTED else None


def negotiate(
    accept_language: Optional[str] = None, explicit: Optional[str] = None
) -> str:
    """Resolve the locale to use for a request.

    Args:
        accept_language: Raw ``Accept-Language`` header value, if any.
        explicit: An explicit override such as a ``lang`` query parameter or a
            request-body field. Takes precedence over the header when supported.

    Returns:
        A code from :data:`SUPPORTED`, or :data:`DEFAULT` when nothing matches.
    """
    chosen = normalize(explicit)
    if chosen is not None:
        return chosen
    for tag in _parse_accept_language(accept_language or ""):
        if tag == "*":
            return DEFAULT
        matched = normalize(tag)
        if matched is not None:
            return matched
    return DEFAULT


def set_locale(code: Optional[str]) -> Token:
    """Bind the active locale for the current context.

    Args:
        code: A language tag; unsupported or missing values bind :data:`DEFAULT`.

    Returns:
        A token to hand back to :func:`reset_locale`.
    """
    return _locale.set(normalize(code) or DEFAULT)


def reset_locale(token: Token) -> None:
    """Restore the locale bound before the matching :func:`set_locale`."""
    _locale.reset(token)


def get_locale() -> str:
    """Return the locale bound to the current context."""
    return _locale.get()


@contextmanager
def use_locale(code: Optional[str]) -> Iterator[str]:
    """Bind ``code`` for the duration of the block, then restore the previous."""
    token = set_locale(code)
    try:
        yield get_locale()
    finally:
        reset_locale(token)


def gettext(message: str) -> str:
    """Translate ``message`` into the context's locale.

    The argument must be a literal string: pybabel extracts msgids statically,
    so an f-string or a concatenation yields no catalog entry and silently
    never translates. Interpolate after the lookup instead::

        _("Invalid geometry: {error}").format(error=exc)
    """
    return _catalog(get_locale()).gettext(message)


def ngettext(singular: str, plural: str, n: int) -> str:
    """Translate a countable message, picking the locale's plural form."""
    return _catalog(get_locale()).ngettext(singular, plural, n)


_ = gettext

__all__ = [
    "DEFAULT",
    "DOMAIN",
    "LOCALE_DIR",
    "SUPPORTED",
    "_",
    "clear_cache",
    "get_locale",
    "gettext",
    "negotiate",
    "ngettext",
    "normalize",
    "reset_locale",
    "set_locale",
    "use_locale",
]
