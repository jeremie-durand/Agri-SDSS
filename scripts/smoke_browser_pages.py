#!/usr/bin/env python3
"""
Smoke-check the HTML pages and CORS headers the APIs serve through home nginx.

Each service's own tests call it without the proxy, so they cannot see defects
that only appear once home and Caddy sit in front of it. For every page below,
this script asserts that:

1. the response carries at most one Access-Control-Allow-Origin header;
2. every same-origin link stays under the page's public prefix;
3. every external script and stylesheet origin is allowed by the CSP that
   caddy/Caddyfile sets on API paths;
4. every same-origin, non-templated link of each API landing page answers 200;
5. every slash redirect, requested with Caddy's X-Forwarded-Proto: https,
   stays on the public HTTPS origin, under the page's prefix, and lands on a 200.

Run it with ``make smoke-browser-pages``. It exits 1 and prints one line per
failure when any check fails. Standard library only, so it runs in a bare
python image on eoapi-network.
"""

from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.request
from html.parser import HTMLParser
from urllib.parse import quote, urljoin, urlparse

BASE_URL: str = os.environ.get("SMOKE_BASE_URL", "http://home:8080").rstrip("/")
PUBLIC_HOST: str = os.environ.get("SMOKE_PUBLIC_HOST", "localhost")
CADDYFILE: str = os.environ.get("SMOKE_CADDYFILE", "/caddy/Caddyfile")
ORIGIN: str = "https://smoke.example"
TIMEOUT_SECONDS: int = 60

HTML_PAGES: list[str] = [
    "/stac-api/api.html",
    "/vector-api/docs",
    "/vector-api/redoc",
    "/vector-api/postgis/",
    "/vector-api/postgis/collections",
    "/vector-api/postgis/api.html",
    "/vector-api/parquet/api.html",
    "/raster-api/",
    "/raster-api/api.html",
    "/raster-api/cog/viewer",
    "/process-api/",
    "/process-api/processes",
]

CORS_ONLY_PAGES: list[str] = [
    "/stac-api/collections",
    "/process-api/processes?f=json",
]

LANDING_PAGES: list[str] = [
    "/stac-api/",
    "/vector-api/",
    "/vector-api/parquet",
    "/vector-api/postgis/?f=json",
    "/raster-api/",
    "/process-api/?f=json",
]

REDIRECT_PAGES: list[str] = [
    "/stac-api",
    "/stac-api/collections/",
    "/vector-api",
    "/vector-api/postgis",
    "/vector-api/postgis/collections/",
    "/vector-api/parquet/",
    "/raster-api",
    "/raster-api/tileMatrixSets/",
    "/process-api",
]

EXTERNAL_CORS_PAGES: list[str] = [
    "/aac-identify/?f=json",
]

SKIPPED_SCHEMES: tuple[str, ...] = ("data:", "blob:", "javascript:", "mailto:", "#")

JS_URL_PATTERN = re.compile(r"""(?:\burl|spec-url)\s*[:=]\s*['"]([^'"]+)['"]""")


class _AssetCollector(HTMLParser):
    """Collect link targets, scripts and stylesheets from an HTML page."""

    def __init__(self) -> None:
        super().__init__()
        self.links: list[str] = []
        self.scripts: list[str] = []
        self.stylesheets: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {name: value or "" for name, value in attrs}
        for name in ("href", "src", "action", "spec-url"):
            if values.get(name):
                self.links.append(values[name])
        if tag == "script" and values.get("src"):
            self.scripts.append(values["src"])
        if (
            tag == "link"
            and "stylesheet" in values.get("rel", "").split()
            and values.get("href")
        ):
            self.stylesheets.append(values["href"])


def fetch(path: str, accept: str) -> tuple[int, list[str], str, str]:
    """GET a path through home and return status, ACAO values, type and body."""
    request = urllib.request.Request(
        f"{BASE_URL}{path}",
        headers={"Accept": accept, "Origin": ORIGIN, "User-Agent": "smoke-browser"},
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            body = response.read().decode("utf-8", "replace")
            return (
                response.status,
                response.headers.get_all("Access-Control-Allow-Origin") or [],
                response.headers.get("Content-Type", ""),
                body,
            )
    except urllib.error.HTTPError as exc:
        return (
            exc.code,
            exc.headers.get_all("Access-Control-Allow-Origin") or [],
            "",
            "",
        )
    except urllib.error.URLError as exc:
        print(f"note: {path}: {exc.reason}", flush=True)
        return 0, [], "", ""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Surface redirects as HTTPError so their Location can be inspected."""

    def redirect_request(self, *args, **kwargs) -> None:
        return None


def redirect_location(path: str) -> tuple[int, str]:
    """GET a path through home, as Caddy forwards it, without following redirects."""
    opener = urllib.request.build_opener(_NoRedirect)
    request = urllib.request.Request(
        f"{BASE_URL}{path}",
        headers={"User-Agent": "smoke-browser", "X-Forwarded-Proto": "https"},
    )
    try:
        with opener.open(request, timeout=TIMEOUT_SECONDS) as response:
            return response.status, ""
    except urllib.error.HTTPError as exc:
        return exc.code, exc.headers.get("Location", "")
    except urllib.error.URLError as exc:
        print(f"note: {path}: {exc.reason}", flush=True)
        return 0, ""


def check_redirect(path: str) -> list[str]:
    """Report a redirect that leaves the origin or prefix, or lands on an error.

    A relative Location is resolved by the browser against the public origin;
    an absolute one must name that origin itself, not home's internal port, and
    keep https: an http:// one means the service ignored X-Forwarded-Proto
    (FORWARDED_ALLOW_IPS unset) and the browser would leave HTTPS.
    """
    status, location = redirect_location(path)
    if status not in (301, 302, 307, 308):
        return [f"{path}: expected a redirect, got HTTP {status}"]
    target = urlparse(location)
    if target.scheme and target.scheme != "https":
        return [f"{path}: redirects to {target.scheme}:// behind HTTPS: {location}"]
    if target.netloc and target.netloc not in self_hosts():
        return [f"{path}: redirects off the public origin to {location}"]
    prefix = f"/{path.strip('/').split('/')[0]}"
    if not under_prefix(target.path, prefix):
        return [f"{path}: redirects outside {prefix} to {location}"]
    landing = f"{target.path}?{target.query}" if target.query else target.path
    landed = fetch(landing, "application/json")[0]
    if landed != 200:
        return [f"{path}: redirect target {landing} -> HTTP {landed}"]
    return []


def api_csp(caddyfile_text: str) -> dict[str, list[str]]:
    """Return the CSP directives Caddy applies to API paths.

    A ``header @api_pages`` block wins; otherwise the first unmatched
    Content-Security-Policy applies to every path, API paths included.
    """
    scoped = re.search(
        r'header\s+@api_pages\s*\{[^}]*?Content-Security-Policy\s+"([^"]+)"',
        caddyfile_text,
    )
    policy = scoped or re.search(r'Content-Security-Policy\s+"([^"]+)"', caddyfile_text)
    if policy is None:
        raise SystemExit(f"No Content-Security-Policy found in {CADDYFILE}")
    directives: dict[str, list[str]] = {}
    for part in policy.group(1).split(";"):
        tokens = part.split()
        if tokens:
            directives[tokens[0]] = tokens[1:]
    return directives


def self_hosts() -> set[str]:
    """Hostnames that are the platform itself: home internally, HOST_URL publicly.

    Services build absolute URLs from either the forwarded Host (home) or the
    configured public origin (pygeoapi), and both are 'self' to a browser.
    """
    return {urlparse(BASE_URL).hostname or "", PUBLIC_HOST}


def csp_allows(directives: dict[str, list[str]], directive: str, url: str) -> bool:
    """Whether a CSP directive (or default-src) allows loading ``url``."""
    sources = directives.get(directive, directives.get("default-src", []))
    parsed = urlparse(url)
    if "*" in sources or f"{parsed.scheme}:" in sources:
        return True
    if parsed.hostname in self_hosts():
        return "'self'" in sources
    return f"{parsed.scheme}://{parsed.netloc}" in sources


def under_prefix(path: str, prefix: str) -> bool:
    """Whether a URL path sits under a public prefix such as ``/vector-api``."""
    return path == prefix or path.startswith(f"{prefix}/")


def check_cors(path: str, values: list[str]) -> list[str]:
    """Report a response carrying several Access-Control-Allow-Origin values."""
    if len(values) > 1:
        return [f"{path}: {len(values)} Access-Control-Allow-Origin values {values}"]
    return []


def same_origin_urls(page_url: str, body: str, collector: _AssetCollector) -> set[str]:
    """Absolute same-origin URLs referenced by the page, attributes and inline JS."""
    hosts = self_hosts()
    host_alternatives = "|".join(re.escape(host) for host in sorted(hosts))
    absolute_pattern = re.compile(
        rf"""["'](https?://(?:{host_alternatives})(?::\d+)?/[^"'\s]*)["']"""
    )
    candidates = collector.links + JS_URL_PATTERN.findall(body)
    candidates += absolute_pattern.findall(body)
    urls: set[str] = set()
    for candidate in candidates:
        if not candidate or candidate.startswith(SKIPPED_SCHEMES):
            continue
        resolved = urlparse(urljoin(page_url, candidate))
        if resolved.hostname in hosts:
            urls.add(resolved.path)
    return urls


def check_html_page(
    path: str, html_url: str, body: str, directives: dict[str, list[str]]
) -> list[str]:
    """Report links outside the public prefix and assets the CSP blocks."""
    prefix = f"/{path.strip('/').split('/')[0]}"
    collector = _AssetCollector()
    collector.feed(body)
    failures: list[str] = []
    outside = sorted(
        url
        for url in same_origin_urls(html_url, body, collector)
        if not under_prefix(url, prefix)
    )
    if outside:
        shown = ", ".join(outside[:5])
        more = f" (+{len(outside) - 5} more)" if len(outside) > 5 else ""
        failures.append(f"{path}: links outside {prefix}: {shown}{more}")
    for kind, directive, assets in (
        ("script", "script-src", collector.scripts),
        ("stylesheet", "style-src", collector.stylesheets),
    ):
        for asset in sorted(set(assets)):
            absolute = urljoin(html_url, asset)
            if not csp_allows(directives, directive, absolute):
                failures.append(f"{path}: CSP {directive} blocks {kind} {absolute}")
    return failures


def check_landing_links(path: str, body: str) -> list[str]:
    """Report same-origin, non-templated landing links that do not answer 200."""
    try:
        document = json.loads(body)
    except ValueError:
        return [f"{path}: landing page is not JSON"]
    if not isinstance(document, dict):
        return [f"{path}: landing page is not a JSON object"]
    links = document.get("links", [])
    failures: list[str] = []
    for link in links:
        href = link.get("href", "")
        if not href or "{" in href:
            continue
        resolved = urlparse(urljoin(f"{BASE_URL}{path}", href))
        if resolved.hostname not in self_hosts():
            continue
        target = (
            f"{resolved.path}?{resolved.query}" if resolved.query else resolved.path
        )
        status = fetch(target, "application/json")[0]
        if status == 404 and _is_empty_catalog_queryables(target):
            print(f"note: {target} 404 on an empty STAC catalog, not checked")
            continue
        if status != 200:
            failures.append(f"{path}: rel={link.get('rel')} {target} -> HTTP {status}")
    return failures


def _is_empty_catalog_queryables(target: str) -> bool:
    """stac-fastapi-pgstac answers /queryables 404 while no collection exists."""
    return target == "/stac-api/queryables" and stac_catalog_is_empty()


def first_collection_items_page() -> str | None:
    """Items page of the first PostGIS collection whose items answer 200.

    TiPg also lists SQL functions as collections (PostGIS's own postgis_srs,
    for one), and those 422 without their arguments. Nothing in the
    collection metadata tells them apart from tables, so probe each in turn.
    """
    status, _, _, body = fetch(
        "/vector-api/postgis/collections?f=json&limit=100", "application/json"
    )
    if status != 200:
        return None
    try:
        collections = json.loads(body).get("collections", [])
    except (ValueError, AttributeError):
        return None
    for collection in collections:
        collection_id = quote(collection["id"], safe="")
        page = f"/vector-api/postgis/collections/{collection_id}/items?limit=5"
        if fetch(page, "application/geo+json")[0] == 200:
            return page
    return None


def stac_catalog_is_empty() -> bool:
    """Whether stac-api holds no collection, as in CI's fresh database."""
    status, _, _, body = fetch("/stac-api/collections", "application/json")
    try:
        return status == 200 and not json.loads(body).get("collections")
    except (ValueError, AttributeError):
        return False


def main() -> int:
    """Run every check and return the process exit code."""
    with open(CADDYFILE, encoding="utf-8") as caddyfile:
        directives = api_csp(caddyfile.read())

    pages = list(HTML_PAGES)
    items_page = first_collection_items_page()
    if items_page:
        pages.append(items_page)
    else:
        print(
            "note: no PostGIS collection serves items, items page not checked",
            flush=True,
        )

    failures: list[str] = []
    for path in pages:
        status, acao, content_type, body = fetch(path, "text/html")
        if status != 200:
            failures.append(f"{path}: HTTP {status}")
            continue
        failures += check_cors(path, acao)
        if "html" not in content_type:
            failures.append(f"{path}: expected HTML, got {content_type!r}")
            continue
        failures += check_html_page(path, f"{BASE_URL}{path}", body, directives)

    for path in CORS_ONLY_PAGES:
        status, acao, _, _ = fetch(path, "application/json")
        if status != 200:
            failures.append(f"{path}: HTTP {status}")
            continue
        failures += check_cors(path, acao)

    for path in LANDING_PAGES:
        status, acao, _, body = fetch(path, "application/json")
        if status != 200:
            failures.append(f"{path}: HTTP {status}")
            continue
        failures += check_cors(path, acao)
        failures += check_landing_links(path, body)

    for path in REDIRECT_PAGES:
        failures += check_redirect(path)

    for path in EXTERNAL_CORS_PAGES:
        status, acao, _, _ = fetch(path, "application/json")
        if status != 200:
            print(f"note: {path} upstream answered {status}, not checked", flush=True)
            continue
        failures += check_cors(path, acao)

    for failure in failures:
        print(f"✗ {failure}", flush=True)
    checked = (
        len(pages)
        + len(CORS_ONLY_PAGES)
        + len(LANDING_PAGES)
        + len(REDIRECT_PAGES)
        + len(EXTERNAL_CORS_PAGES)
    )
    if failures:
        print(f"{len(failures)} failure(s) across {checked} URLs", flush=True)
        return 1
    print(f"✓ {checked} URLs passed", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
