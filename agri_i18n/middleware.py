"""Request-scoped locale binding for ASGI and WSGI services.

Both middlewares resolve the locale once per request from ``Accept-Language``
and an optional ``lang`` query parameter, then bind it for the duration of the
request. ``lang`` matches ``pygeoapi.l10n.QUERY_PARAM`` so process-api's own
negotiation and ours agree on the same override.

Neither class imports a web framework: they implement the raw ASGI and WSGI
protocols, so they cost no dependency in any image.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, Iterable, Optional
from urllib.parse import parse_qs

from . import negotiate, reset_locale, set_locale

QUERY_PARAM = "lang"


def _query_override(query_string: str) -> Optional[str]:
    """Return the ``lang`` query parameter, or ``None`` when absent."""
    values = parse_qs(query_string).get(QUERY_PARAM)
    return values[0] if values else None


class LocaleASGIMiddleware:
    """Bind the negotiated locale around an ASGI application.

    Implemented as raw ASGI rather than Starlette's ``BaseHTTPMiddleware``,
    which runs the downstream app in a separate task and would strand the
    ``ContextVar`` this sets.
    """

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: Dict[str, Any], receive: Any, send: Any) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        header: Optional[str] = None
        for name, value in scope.get("headers") or []:
            if name == b"accept-language":
                header = value.decode("latin-1")
                break

        query = (scope.get("query_string") or b"").decode("latin-1")
        token = set_locale(negotiate(header, _query_override(query)))
        try:
            await self.app(scope, receive, send)
        finally:
            reset_locale(token)


class LocaleWSGIMiddleware:
    """Bind the negotiated locale around a WSGI application.

    Notes:
        The locale is released once the application callable returns. pygeoapi
        builds its responses eagerly inside the view, so nothing translates
        while the response iterable is consumed. A lazily-streaming app would
        need the reset deferred to the iterable's ``close``.
    """

    def __init__(self, app: Callable[..., Iterable[bytes]]) -> None:
        self.app = app

    def __call__(self, environ: Dict[str, Any], start_response: Any) -> Iterable[bytes]:
        token = set_locale(
            negotiate(
                environ.get("HTTP_ACCEPT_LANGUAGE"),
                _query_override(environ.get("QUERY_STRING", "")),
            )
        )
        try:
            return self.app(environ, start_response)
        finally:
            reset_locale(token)


__all__ = ["QUERY_PARAM", "LocaleASGIMiddleware", "LocaleWSGIMiddleware"]
