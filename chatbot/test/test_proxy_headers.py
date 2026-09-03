"""Guards for the client-IP resolution the backend rate limiter depends on.

RateLimitMiddleware buckets on request.client.host. Behind Caddy + home nginx
that is the proxy's address unless uvicorn resolves X-Forwarded-For, which
collapses RATE_LIMIT_LLM into a single global bucket that one visitor can
exhaust for everyone.

uvicorn is pinned by the upstream requirements.txt, so a CHATBOT_VERSION bump
can move it. Which entry of the forwarded chain uvicorn picks has changed
across releases, so these tests assert the behaviour rather than the version.
"""

import pathlib

import pytest
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

PROXY_CHAIN = b"203.0.113.9, 10.0.0.5"
REAL_CLIENT = "203.0.113.9"
NEAREST_PROXY = "10.0.0.5"


def _scope(headers: list[tuple[bytes, bytes]]) -> dict:
    return {
        "type": "http",
        "scheme": "http",
        "client": ("127.0.0.1", 1234),
        "headers": headers,
    }


async def _capture_client(scope, receive, send) -> None:
    _capture_client.seen = scope["client"][0] if scope["client"] else None
    await send({"type": "http.response.start", "status": 200, "headers": []})
    await send({"type": "http.response.body", "body": b""})


async def _drive(middleware, scope) -> str:
    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(_message):
        return None

    await middleware(scope, receive, send)
    return _capture_client.seen


@pytest.mark.unit
async def test_trusting_whole_chain_resolves_the_real_client():
    """forwarded-allow-ips="*" must yield the leftmost X-Forwarded-For entry.

    Caddy runs without trusted_proxies and so replaces any client-supplied
    header, making that leftmost entry the authoritative remote address.
    """
    middleware = ProxyHeadersMiddleware(_capture_client, trusted_hosts="*")
    seen = await _drive(middleware, _scope([(b"x-forwarded-for", PROXY_CHAIN)]))
    assert seen == REAL_CLIENT


@pytest.mark.unit
async def test_default_trusted_hosts_resolve_only_to_the_nearest_proxy():
    """Without the flag uvicorn stops at the nearest untrusted hop.

    This is the behaviour the entrypoint flags exist to avoid: every visitor
    would share one rate-limit bucket keyed on the proxy's address.
    """
    middleware = ProxyHeadersMiddleware(_capture_client, trusted_hosts="127.0.0.1")
    seen = await _drive(middleware, _scope([(b"x-forwarded-for", PROXY_CHAIN)]))
    assert seen == NEAREST_PROXY


@pytest.mark.unit
async def test_no_forwarded_header_keeps_the_peer_address():
    """A request with no forwarded header must keep the socket peer."""
    middleware = ProxyHeadersMiddleware(_capture_client, trusted_hosts="*")
    seen = await _drive(middleware, _scope([]))
    assert seen == "127.0.0.1"


@pytest.mark.unit
def test_entrypoint_enables_proxy_header_resolution():
    """The flags must stay on the uvicorn command line.

    Overrides are flattened into /app in the runtime image, so look there as
    well as in the repository layout used when running tests from a checkout.
    """
    here = pathlib.Path(__file__).resolve()
    candidates = [
        here.parents[1] / "overrides/backend/entrypoint.sh",
        pathlib.Path("/app/entrypoint.sh"),
    ]
    entrypoint = next((c for c in candidates if c.is_file()), None)
    assert entrypoint is not None, f"entrypoint.sh not found in any of {candidates}"
    command = entrypoint.read_text()
    assert "--proxy-headers" in command
    assert "--forwarded-allow-ips" in command


@pytest.mark.unit
def test_rate_limiter_buckets_per_resolved_client():
    """Two clients behind the same proxy must not share a rate-limit bucket."""
    from rate_limit_middleware import RateLimitMiddleware, _llm_limit

    app = Starlette(
        routes=[Route("/api/query", lambda r: PlainTextResponse("ok"), methods=["POST"])]
    )
    app.add_middleware(RateLimitMiddleware)
    allowed = _llm_limit.amount

    with TestClient(app, client=("198.51.100.1", 1111)) as first:
        for i in range(allowed):
            assert first.post("/api/query").status_code != 429, f"blocked at {i + 1}"
        assert first.post("/api/query").status_code == 429

    with TestClient(app, client=("198.51.100.2", 2222)) as second:
        assert (
            second.post("/api/query").status_code != 429
        ), "a second client inherited the first client's exhausted bucket"
