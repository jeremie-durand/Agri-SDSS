"""Unit tests for the ASGI and WSGI locale-binding middlewares.

The apps under test are raw protocol callables, so these tests exercise the
middlewares without pulling in a web framework.
"""

import asyncio

import pytest

from agri_i18n import DEFAULT, get_locale
from agri_i18n.middleware import LocaleASGIMiddleware, LocaleWSGIMiddleware

# --- ASGI ---


def _scope(accept_language=None, query=b"", scope_type="http"):
    """Build a minimal ASGI scope."""
    headers = []
    if accept_language is not None:
        headers.append((b"accept-language", accept_language.encode("latin-1")))
    return {"type": scope_type, "headers": headers, "query_string": query}


async def _record_locale(scope, receive, send):
    """Downstream ASGI app that reports the locale bound during the call."""
    scope["observed"] = get_locale()


def _run_asgi(scope):
    """Drive the middleware once and return the locale the app observed."""
    app = LocaleASGIMiddleware(_record_locale)
    asyncio.run(app(scope, None, None))
    return scope.get("observed")


@pytest.mark.unit
@pytest.mark.parametrize(
    "header,expected",
    [
        (None, DEFAULT),
        ("fr-CA,fr;q=0.9", "fr"),
        ("en-US,en;q=0.9", "en"),
        ("de", DEFAULT),
        ("", DEFAULT),
    ],
)
def test_asgi_binds_accept_language(header, expected):
    """The downstream app sees the negotiated locale."""
    assert _run_asgi(_scope(accept_language=header)) == expected


@pytest.mark.unit
def test_asgi_query_param_overrides_header():
    """?lang= wins over Accept-Language, matching pygeoapi's QUERY_PARAM."""
    scope = _scope(accept_language="fr-CA,fr;q=0.9", query=b"lang=en&f=json")
    assert _run_asgi(scope) == "en"


@pytest.mark.unit
def test_asgi_unsupported_query_param_falls_back_to_header():
    """An unsupported ?lang= is ignored rather than forcing the default."""
    scope = _scope(accept_language="en-US,en;q=0.9", query=b"lang=de")
    assert _run_asgi(scope) == "en"


@pytest.mark.unit
def test_asgi_resets_locale_after_request():
    """The binding does not outlive the request."""
    _run_asgi(_scope(accept_language="en"))
    assert get_locale() == DEFAULT


@pytest.mark.unit
def test_asgi_resets_locale_when_app_raises():
    """A failing downstream app still releases the binding."""

    async def boom(scope, receive, send):
        raise RuntimeError("downstream failure")

    app = LocaleASGIMiddleware(boom)
    with pytest.raises(RuntimeError):
        asyncio.run(app(_scope(accept_language="en"), None, None))
    assert get_locale() == DEFAULT


@pytest.mark.unit
@pytest.mark.parametrize("scope_type", ["lifespan", "websocket"])
def test_asgi_passes_through_non_http_scopes(scope_type):
    """Non-HTTP scopes are forwarded untouched and bind nothing."""
    scope = _scope(accept_language="en", scope_type=scope_type)
    assert _run_asgi(scope) == DEFAULT


@pytest.mark.unit
def test_asgi_concurrent_requests_do_not_leak():
    """Interleaved requests keep independent locales."""

    async def slow_app(scope, receive, send):
        await asyncio.sleep(scope["delay"])
        scope["observed"] = get_locale()

    async def main():
        app = LocaleASGIMiddleware(slow_app)
        english = _scope(accept_language="en-US")
        english["delay"] = 0.02
        french = _scope(accept_language="fr-CA")
        french["delay"] = 0.0
        await asyncio.gather(
            app(english, None, None), app(french, None, None)
        )
        return english["observed"], french["observed"]

    assert asyncio.run(main()) == ("en", "fr")


# --- WSGI ---


def _environ(accept_language=None, query=""):
    """Build a minimal WSGI environ."""
    environ = {"QUERY_STRING": query}
    if accept_language is not None:
        environ["HTTP_ACCEPT_LANGUAGE"] = accept_language
    return environ


def _run_wsgi(environ):
    """Drive the middleware once and return the locale the app observed."""
    observed = {}

    def app(env, start_response):
        observed["locale"] = get_locale()
        return [b""]

    LocaleWSGIMiddleware(app)(environ, None)
    return observed["locale"]


@pytest.mark.unit
@pytest.mark.parametrize(
    "header,expected",
    [
        (None, DEFAULT),
        ("fr-CA,fr;q=0.9", "fr"),
        ("en-US,en;q=0.9", "en"),
        ("de", DEFAULT),
    ],
)
def test_wsgi_binds_accept_language(header, expected):
    """The wrapped WSGI app sees the negotiated locale."""
    assert _run_wsgi(_environ(accept_language=header)) == expected


@pytest.mark.unit
def test_wsgi_query_param_overrides_header():
    """?lang= wins over Accept-Language."""
    environ = _environ(accept_language="fr-CA", query="lang=en&f=json")
    assert _run_wsgi(environ) == "en"


@pytest.mark.unit
def test_wsgi_resets_locale_after_request():
    """The binding does not outlive the request."""
    _run_wsgi(_environ(accept_language="en"))
    assert get_locale() == DEFAULT


@pytest.mark.unit
def test_wsgi_resets_locale_when_app_raises():
    """A failing wrapped app still releases the binding."""

    def boom(environ, start_response):
        raise RuntimeError("downstream failure")

    with pytest.raises(RuntimeError):
        LocaleWSGIMiddleware(boom)(_environ(accept_language="en"), None)
    assert get_locale() == DEFAULT
