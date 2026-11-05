#!/usr/bin/env python3
"""
Walk every public API catalog through home nginx and open each listed entry.

Each service's CI tests walk their own catalog on fixture data. This script
walks the real catalogs of a running stack, where bugs that depend on the data
show up (#277, #287, #289). For each catalog it asserts that:

1. every PostGIS, Parquet and STAC collection answers ``items?limit=1`` with
   200 and a GeoJSON FeatureCollection;
2. every listed process answers ``/processes/{id}`` with 200 and its own id.

Requests run one at a time. The first 502, 503 or 504 stops the walk of that
API, since the service is down and further requests only hit it while it
restarts. Parquet is capped at PARQUET_DEFAULT_CAP collections, evenly spaced
over the list: walking all of them OOM-kills vector-api until #288 is fixed.
``SMOKE_CATALOGS_ALL=1`` walks them all; run it on a local stack only.

Run it with ``make smoke-catalogs`` (``ALL=1`` for the full walk). It exits 1
and prints one line per failure when any check fails. Standard library only,
so it runs in a bare python image on eoapi-network.
"""

from __future__ import annotations

import http.client
import json
import os
import sys
import urllib.error
import urllib.request
from collections.abc import Iterator
from typing import Any
from urllib.parse import quote, urlparse

BASE_URL: str = os.environ.get("SMOKE_BASE_URL", "http://home:8080").rstrip("/")
WALK_ALL: bool = os.environ.get("SMOKE_CATALOGS_ALL") == "1"
TIMEOUT_SECONDS: int = 60
PARQUET_DEFAULT_CAP: int = 25
SERVICE_DOWN_STATUSES: frozenset[int] = frozenset({502, 503, 504})

COLLECTION_CATALOGS: dict[str, str] = {
    "postgis": "/vector-api/postgis/collections",
    "parquet": "/vector-api/parquet/collections",
    "stac": "/stac-api/collections",
}
PROCESS_LIST: str = "/process-api/processes"


class ServiceDown(Exception):
    """An API answered 502/503/504 or dropped the connection: stop walking it."""


class CatalogUnreadable(Exception):
    """A collection list answered, but not with a readable page of collections."""


def fetch_json(path: str, accept: str = "application/json") -> tuple[int, Any]:
    """GET ``path`` on home; return the status and the decoded JSON body.

    The body is None when it is not JSON, so a 200 with a broken body is
    reported as a failure rather than crashing the walk.
    """
    request = urllib.request.Request(f"{BASE_URL}{path}", headers={"Accept": accept})
    try:
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as resp:
                status, raw = resp.status, resp.read()
        except urllib.error.HTTPError as exc:
            status, raw = exc.code, exc.read()
    except (OSError, http.client.HTTPException) as exc:
        raise ServiceDown(f"{path}: no response ({exc!r})") from exc
    if status in SERVICE_DOWN_STATUSES:
        raise ServiceDown(f"{path}: HTTP {status}")
    try:
        return status, json.loads(raw)
    except ValueError:
        return status, None


def with_query(path: str, query: str) -> str:
    """Append ``query`` to ``path``, which may already carry a query string."""
    return f"{path}{'&' if '?' in path else '?'}{query}"


def next_page(body: dict[str, Any]) -> str | None:
    """Path and query of the ``next`` link, re-rooted on home.

    The href names the public origin, which is not reachable from the
    Docker network, so only its path and query are kept.
    """
    for link in body.get("links", []):
        if link.get("rel") == "next":
            parsed = urlparse(link["href"])
            return f"{parsed.path}?{parsed.query}" if parsed.query else parsed.path
    return None


def collection_ids(list_path: str) -> Iterator[str]:
    """Every collection id of a catalog, following ``next`` links."""
    page: str | None = with_query(list_path, "limit=100")
    seen: set[str] = set()
    while page:
        if page in seen:
            raise CatalogUnreadable(
                f"{page}: next link loops back to a page already read"
            )
        seen.add(page)
        status, body = fetch_json(page)
        if status != 200 or not isinstance(body, dict):
            raise CatalogUnreadable(
                f"{page}: HTTP {status}, collection list unreadable"
            )
        for collection in body.get("collections", []):
            yield collection["id"]
        page = next_page(body)


def check_items(list_path: str, collection_id: str) -> list[str]:
    """Open the first items page as GeoJSON.

    TiPg answers ``Accept: application/json`` with a plain JSON array of rows,
    so items pages ask for ``application/geo+json``.
    """
    path = f"{list_path}/{quote(collection_id, safe='')}/items?limit=1"
    status, body = fetch_json(path, "application/geo+json")
    if status != 200:
        return [f"{path}: HTTP {status}"]
    if not isinstance(body, dict) or body.get("type") != "FeatureCollection":
        return [f"{path}: not a FeatureCollection"]
    return []


def spread_sample(ids: list[str], cap: int) -> list[str]:
    """``cap`` ids evenly spaced over the whole list, first one included.

    Parquet lists collections by file name, so the first ``cap`` would all
    come from one data family; spacing them out reaches the others.
    """
    if len(ids) <= cap:
        return ids
    return [ids[i * len(ids) // cap] for i in range(cap)]


def walk_collections(name: str, list_path: str, cap: int | None) -> list[str]:
    """Open the items page of every collection, or of ``cap`` spread over them."""
    failures: list[str] = []
    walked = 0
    last_walked = "(none)"
    try:
        ids = list(collection_ids(list_path))
        if not ids:
            failures.append(f"{name}: {list_path} lists no collections")
        if cap is not None and len(ids) > cap:
            print(f"note: {name}: {cap} of {len(ids)} collections, evenly spaced")
            ids = spread_sample(ids, cap)
        for collection_id in ids:
            failures += check_items(list_path, collection_id)
            walked += 1
            last_walked = collection_id
    except CatalogUnreadable as exc:
        failures.append(f"{name}: {exc}")
    except ServiceDown as exc:
        failures.append(f"{name}: service down after {last_walked}: {exc}")
    print(f"{name}: {walked} collections walked, {len(failures)} failures")
    return failures


def walk_processes() -> list[str]:
    """Describe every listed process.

    pygeoapi cuts the list at ``limit`` without a ``next`` link, so the walk
    asks for its configured maximum instead of paging.
    """
    failures: list[str] = []
    walked = 0
    last_walked = "(none)"
    try:
        status, body = fetch_json(f"{PROCESS_LIST}?f=json&limit=1000")
        if status != 200 or not isinstance(body, dict):
            return [f"{PROCESS_LIST}: HTTP {status}, process list unreadable"]
        processes = body.get("processes", [])
        if not processes:
            failures.append(f"processes: {PROCESS_LIST} lists no processes")
        for process in processes:
            process_id = process["id"]
            path = f"{PROCESS_LIST}/{quote(process_id, safe='')}?f=json"
            status, description = fetch_json(path)
            if status != 200:
                failures.append(f"{path}: HTTP {status}")
            elif not isinstance(description, dict) or (
                description.get("id") != process_id
            ):
                failures.append(f"{path}: description id is not {process_id!r}")
            walked += 1
            last_walked = process_id
    except ServiceDown as exc:
        failures.append(f"processes: service down after {last_walked}: {exc}")
    print(f"processes: {walked} processes walked, {len(failures)} failures")
    return failures


def main() -> int:
    """Walk every catalog and return the process exit code."""
    if WALK_ALL:
        print(
            "warning: walking every Parquet collection can OOM-kill vector-api "
            "until #288 is fixed; run it on a local stack only",
            flush=True,
        )
    failures: list[str] = []
    for name, list_path in COLLECTION_CATALOGS.items():
        cap = PARQUET_DEFAULT_CAP if name == "parquet" and not WALK_ALL else None
        failures += walk_collections(name, list_path, cap)
    failures += walk_processes()

    for failure in failures:
        print(f"✗ {failure}")
    if failures:
        print(f"{len(failures)} failure(s)")
        return 1
    print("✓ every listed catalog entry opens")
    return 0


if __name__ == "__main__":
    sys.exit(main())
