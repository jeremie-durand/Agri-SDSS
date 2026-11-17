"""Real integration tests for the stac-api (stac-fastapi.pgstac).

Uses FastAPI TestClient against the real stac-fastapi app backed by pgstac.
All tests are automatically skipped when PostgreSQL is unavailable.

Test strategy: session-scoped fixtures create a collection and item once,
run all read/search assertions against them, then clean up: items via the
API, the collection out-of-band as the pgstac admin (see db_utils).
This avoids polluting the shared database between test runs.
"""

import math
import os
import re
import subprocess
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg import sql
from stac_api.test.db_utils import (
    admin_connection,
    admin_credentials_available,
    admin_delete_collection,
    app_connection,
)

PAGE_LIMIT = 3
PAGING_ITEM_COUNT = 7
EXPECTED_PAGES = math.ceil(PAGING_ITEM_COUNT / PAGE_LIMIT)
APP_ROLE = os.getenv("PGUSER", "agri_sdss")
GRANTS_SQL = Path(__file__).resolve().parents[2] / "scripts" / "apply_pgstac_grants.sql"

DIRECT_PGSTAC_GRANTS_SQL = """
SELECT 'schema pgstac' FROM pg_namespace n, aclexplode(n.nspacl) a
 WHERE n.nspname = 'pgstac' AND a.grantee = %(role)s::regrole
UNION ALL
SELECT 'relation ' || c.relname FROM pg_class c, aclexplode(c.relacl) a
 WHERE c.relnamespace = 'pgstac'::regnamespace AND a.grantee = %(role)s::regrole
UNION ALL
SELECT 'routine ' || p.proname || '(' || oidvectortypes(p.proargtypes) || ')'
  FROM pg_proc p, aclexplode(p.proacl) a
 WHERE p.pronamespace = 'pgstac'::regnamespace AND a.grantee = %(role)s::regrole
UNION ALL
SELECT 'default privileges on ' || d.defaclobjtype::text
  FROM pg_default_acl d, aclexplode(d.defaclacl) a
 WHERE d.defaclnamespace = 'pgstac'::regnamespace AND a.grantee = %(role)s::regrole
"""

# ------------------------------------------
# Session-scoped fixtures — create once, clean up after
# ------------------------------------------


@pytest.fixture(scope="session")
def _created_collection(stac_integration_client, sample_stac_collection):
    """Create test collection; yield its ID; delete it after the session."""
    if not admin_credentials_available():
        pytest.skip("PGSTAC admin credentials unset — cannot clean up; skipping")
    collection_id = sample_stac_collection["id"]
    resp = stac_integration_client.post("/collections", json=sample_stac_collection)
    if resp.status_code not in (200, 201):
        pytest.fail(
            f"Could not create test collection {collection_id!r} "
            f"(status {resp.status_code}): {resp.text}"
        )
    try:
        yield collection_id
    finally:
        admin_delete_collection(collection_id)


@pytest.fixture(scope="session")
def _created_item(stac_integration_client, _created_collection, sample_stac_item):
    """Create test item inside the test collection; yield its ID; delete after session."""
    item_id = sample_stac_item["id"]
    resp = stac_integration_client.post(
        f"/collections/{_created_collection}/items",
        json=sample_stac_item,
    )
    if resp.status_code not in (200, 201):
        pytest.fail(
            f"Could not create test item {item_id!r} "
            f"(status {resp.status_code}): {resp.text}"
        )
    try:
        yield item_id
    finally:
        stac_integration_client.delete(
            f"/collections/{_created_collection}/items/{item_id}"
        )


@pytest.fixture(scope="session")
def _paging_collection(
    stac_integration_client: TestClient,
    sample_stac_collection: dict[str, Any],
    sample_stac_item: dict[str, Any],
    unique_suffix: str,
) -> Iterator[tuple[str, list[str]]]:
    """Collection holding more items than one page; yield its ID and item IDs."""
    if not admin_credentials_available():
        pytest.skip("PGSTAC admin credentials unset — cannot clean up; skipping")
    collection_id = f"test-integration-paging-{unique_suffix}"
    resp = stac_integration_client.post(
        "/collections", json={**sample_stac_collection, "id": collection_id}
    )
    if resp.status_code not in (200, 201):
        pytest.fail(
            f"Could not create paging collection {collection_id!r} "
            f"(status {resp.status_code}): {resp.text}"
        )
    item_ids: list[str] = []
    try:
        for index in range(PAGING_ITEM_COUNT):
            item = {
                **sample_stac_item,
                "id": f"test-integration-paging-item-{index}-{unique_suffix}",
                "properties": {"datetime": f"2024-06-{index + 1:02d}T12:00:00Z"},
            }
            resp = stac_integration_client.post(
                f"/collections/{collection_id}/items", json=item
            )
            if resp.status_code not in (200, 201):
                pytest.fail(
                    f"Could not create paging item {item['id']!r} "
                    f"(status {resp.status_code}): {resp.text}"
                )
            item_ids.append(item["id"])
        yield collection_id, item_ids
    finally:
        admin_delete_collection(collection_id)


def _walk_pages(
    client: TestClient, method: str, url: str, body: dict[str, Any] | None = None
) -> tuple[list[str], int]:
    """Follow ``next`` links from a first request; return item IDs and page count.

    Each link's method and body are applied, and its body is merged into the
    previous one when the link sets ``merge``, as a STAC client does.
    """
    item_ids: list[str] = []
    for page_count in range(1, EXPECTED_PAGES + 3):
        resp = client.request(method, url, json=body)
        assert resp.status_code == 200, resp.text
        page = resp.json()
        item_ids += [feature["id"] for feature in page["features"]]
        link = next((ln for ln in page["links"] if ln["rel"] == "next"), None)
        if link is None:
            return item_ids, page_count
        method = link.get("method", "GET").upper()
        url = link["href"]
        if method == "POST":
            link_body = link.get("body", {})
            body = {**(body or {}), **link_body} if link.get("merge") else link_body
        else:
            body = None
    pytest.fail(f"paging still had a next link after {page_count} pages")


# ------------------------------------------
# Root and conformance
# ------------------------------------------


@pytest.mark.integration
def test_stac_root_returns_catalog(stac_integration_client):
    """GET / returns a valid STAC catalog landing page."""
    resp = stac_integration_client.get("/")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/json"
    data = resp.json()
    assert "links" in data
    assert "stac_version" in data


@pytest.mark.integration
def test_stac_conformance_returns_classes(stac_integration_client):
    """GET /conformance returns a conformsTo list with at least one OGC/STAC URI."""
    resp = stac_integration_client.get("/conformance")
    assert resp.status_code == 200
    data = resp.json()
    assert "conformsTo" in data
    assert isinstance(data["conformsTo"], list)
    assert len(data["conformsTo"]) > 0


# ------------------------------------------
# Collections — read
# ------------------------------------------


@pytest.mark.integration
def test_stac_collections_list_includes_created_collection(
    stac_integration_client, _created_collection
):
    """GET /collections returns a list containing the created test collection."""
    resp = stac_integration_client.get("/collections")
    assert resp.status_code == 200
    data = resp.json()
    assert "collections" in data
    ids = [c["id"] for c in data["collections"]]
    assert _created_collection in ids, f"'{_created_collection}' not found in {ids}"


@pytest.mark.integration
def test_every_listed_collection_serves_items(
    stac_integration_client: TestClient, _created_item: str
) -> None:
    """Every listed collection answers its items page, so the catalog can be walked."""
    resp = stac_integration_client.get("/collections?limit=1000")
    assert resp.status_code == 200
    data = resp.json()
    assert not [link for link in data["links"] if link["rel"] == "next"]
    collection_ids = [c["id"] for c in data["collections"]]
    assert collection_ids

    failures: list[str] = []
    for collection_id in collection_ids:
        items = stac_integration_client.get(
            f"/collections/{collection_id}/items?limit=1"
        )
        if items.status_code != 200 or items.json().get("type") != "FeatureCollection":
            failures.append(f"{collection_id}: {items.status_code}")
    assert failures == []


@pytest.mark.integration
def test_stac_collection_metadata_is_valid(
    stac_integration_client, _created_collection
):
    """GET /collections/{id} returns a valid STAC Collection object."""
    resp = stac_integration_client.get(f"/collections/{_created_collection}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == _created_collection
    assert data["type"] == "Collection"
    assert "extent" in data
    assert "links" in data


# ------------------------------------------
# Items — read (requires _created_item)
# ------------------------------------------


@pytest.mark.integration
def test_stac_items_endpoint_returns_feature_collection(
    stac_integration_client, _created_item, _created_collection
):
    """GET /collections/{id}/items returns a FeatureCollection containing the test item."""
    resp = stac_integration_client.get(f"/collections/{_created_collection}/items")
    assert resp.status_code == 200
    data = resp.json()
    assert data["type"] == "FeatureCollection"
    assert "features" in data
    ids = [f["id"] for f in data["features"]]
    assert _created_item in ids, f"'{_created_item}' not found in items"


@pytest.mark.integration
def test_stac_item_by_id_returns_feature(
    stac_integration_client, _created_item, _created_collection
):
    """GET /collections/{id}/items/{item_id} returns a valid STAC Feature."""
    resp = stac_integration_client.get(
        f"/collections/{_created_collection}/items/{_created_item}"
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["type"] == "Feature"
    assert data["id"] == _created_item
    assert "geometry" in data
    assert "properties" in data
    assert "assets" in data


# ------------------------------------------
# Search
# ------------------------------------------


@pytest.mark.integration
def test_stac_search_finds_created_item(
    stac_integration_client, _created_item, _created_collection
):
    """POST /search with collection filter returns the created item."""
    resp = stac_integration_client.post(
        "/search",
        json={"collections": [_created_collection]},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["type"] == "FeatureCollection"
    ids = [f["id"] for f in data["features"]]
    assert _created_item in ids, f"'{_created_item}' not found in search results"


@pytest.mark.integration
def test_stac_search_bbox_filters_item(
    stac_integration_client, _created_item, _created_collection
):
    """POST /search with bbox enclosing the item returns at least one feature."""
    # item bbox is [-73.5, 45.5, -73.4, 45.6] — well inside [-74, 45, -73, 46]
    resp = stac_integration_client.post(
        "/search",
        json={
            "collections": [_created_collection],
            "bbox": [-74.0, 45.0, -73.0, 46.0],
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["type"] == "FeatureCollection"
    assert len(data["features"]) >= 1


# ------------------------------------------
# Paging (next links)
# ------------------------------------------


@pytest.mark.integration
def test_item_listing_pages_cover_every_item_once(
    stac_integration_client: TestClient, _paging_collection: tuple[str, list[str]]
) -> None:
    """GET /collections/{id}/items paging returns each item once, then stops."""
    collection_id, expected_ids = _paging_collection
    item_ids, pages = _walk_pages(
        stac_integration_client,
        "GET",
        f"/collections/{collection_id}/items?limit={PAGE_LIMIT}",
    )
    assert sorted(item_ids) == sorted(expected_ids)
    assert pages == EXPECTED_PAGES


@pytest.mark.integration
def test_post_search_pages_cover_every_match_once(
    stac_integration_client: TestClient, _paging_collection: tuple[str, list[str]]
) -> None:
    """POST /search paging, applying each next link's method and body."""
    collection_id, expected_ids = _paging_collection
    item_ids, pages = _walk_pages(
        stac_integration_client,
        "POST",
        "/search",
        {"collections": [collection_id], "limit": PAGE_LIMIT},
    )
    assert sorted(item_ids) == sorted(expected_ids)
    assert pages == EXPECTED_PAGES


@pytest.mark.integration
def test_get_search_pages_cover_every_match_once(
    stac_integration_client: TestClient, _paging_collection: tuple[str, list[str]]
) -> None:
    """GET /search paging, following each next link's href."""
    collection_id, expected_ids = _paging_collection
    item_ids, pages = _walk_pages(
        stac_integration_client,
        "GET",
        f"/search?collections={collection_id}&limit={PAGE_LIMIT}",
    )
    assert sorted(item_ids) == sorted(expected_ids)
    assert pages == EXPECTED_PAGES


# ------------------------------------------
# Transactions as the application role
# ------------------------------------------


@pytest.mark.integration
def test_item_lifecycle_as_the_app_role(
    stac_integration_client: TestClient,
    _created_collection: str,
    sample_stac_item: dict[str, Any],
    unique_suffix: str,
) -> None:
    """Create (201), update (200) and delete (200) an item, as publishers do.

    Publishers re-POST an item on every run and fall back to PUT on 409.
    """
    item_id = f"test-integration-lifecycle-{unique_suffix}"
    item = {**sample_stac_item, "id": item_id}
    items_url = f"/collections/{_created_collection}/items"

    created = stac_integration_client.post(items_url, json=item)
    assert created.status_code == 201, created.text
    duplicate = stac_integration_client.post(items_url, json=item)
    assert duplicate.status_code == 409, duplicate.text

    updated_properties = {**item["properties"], "title": "updated"}
    updated = stac_integration_client.put(
        f"{items_url}/{item_id}", json={**item, "properties": updated_properties}
    )
    assert updated.status_code == 200, updated.text
    fetched = stac_integration_client.get(f"{items_url}/{item_id}")
    assert fetched.json()["properties"]["title"] == "updated"

    deleted = stac_integration_client.delete(f"{items_url}/{item_id}")
    assert deleted.status_code == 200, deleted.text
    assert stac_integration_client.get(f"{items_url}/{item_id}").status_code == 404


@pytest.mark.integration
def test_delete_populated_collection_as_the_app_role(
    stac_integration_client: TestClient,
    sample_stac_collection: dict[str, Any],
    sample_stac_item: dict[str, Any],
    unique_suffix: str,
) -> None:
    """DELETE /collections/{id} removes a collection that still has items."""
    if not admin_credentials_available():
        pytest.skip("PGSTAC admin credentials unset — cannot clean up; skipping")
    collection_id = f"test-integration-delete-{unique_suffix}"
    item_id = f"test-integration-delete-item-{unique_suffix}"
    try:
        created = stac_integration_client.post(
            "/collections", json={**sample_stac_collection, "id": collection_id}
        )
        assert created.status_code in (200, 201), created.text
        item = stac_integration_client.post(
            f"/collections/{collection_id}/items",
            json={**sample_stac_item, "id": item_id},
        )
        assert item.status_code in (200, 201), item.text

        deleted = stac_integration_client.delete(f"/collections/{collection_id}")
        assert deleted.status_code == 200, deleted.text

        assert (
            stac_integration_client.get(f"/collections/{collection_id}").status_code
            == 404
        )
        search = stac_integration_client.post("/search", json={"ids": [item_id]})
        assert search.status_code == 200
        assert search.json()["features"] == []
    finally:
        admin_delete_collection(collection_id)


# ------------------------------------------
# Application role privileges in pgstac
# ------------------------------------------


@pytest.fixture(scope="module")
def admin_db(stac_integration_client: TestClient) -> Iterator[psycopg.Connection]:
    """Admin connection for catalog checks; skipped without admin credentials."""
    if not admin_credentials_available():
        pytest.skip("PGSTAC admin credentials unset — cannot inspect privileges")
    with admin_connection() as conn:
        conn.autocommit = True
        yield conn


def _apply_pgstac_grants() -> subprocess.CompletedProcess[str]:
    """Run the grants file as entrypoint.sh does before uvicorn starts."""
    return subprocess.run(
        [
            "psql",
            "-X",
            "-q",
            "-v",
            "ON_ERROR_STOP=1",
            "--single-transaction",
            "-v",
            f"app_role={APP_ROLE}",
            "-f",
            str(GRANTS_SQL),
        ],
        env={
            **os.environ,
            "PGUSER": os.environ["PGSTAC_ADMIN_USER"],
            "PGPASSWORD": os.environ["PGSTAC_ADMIN_PASS"],
        },
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )


@pytest.fixture(scope="module")
def pgstac_grants_applied(admin_db: psycopg.Connection) -> None:
    """Privileges as they stand once the stac-api has started."""
    result = _apply_pgstac_grants()
    assert result.returncode == 0, result.stderr


@pytest.fixture
def app_db(
    stac_integration_client: TestClient, pgstac_grants_applied: None
) -> Iterator[psycopg.Connection]:
    """Connection as the app role; every statement is rolled back."""
    with app_connection() as conn:
        try:
            yield conn
        finally:
            conn.rollback()


@pytest.mark.integration
@pytest.mark.usefixtures("pgstac_grants_applied")
def test_app_role_is_a_pgstac_ingest_member(admin_db: psycopg.Connection) -> None:
    """pgSTAC grants its own objects to pgstac_ingest, migrations included."""
    row = admin_db.execute(
        "SELECT pg_has_role(%s, 'pgstac_ingest', 'MEMBER')", (APP_ROLE,)
    ).fetchone()
    assert row == (True,)


@pytest.mark.integration
@pytest.mark.usefixtures("pgstac_grants_applied")
def test_app_role_holds_no_direct_pgstac_privilege(
    admin_db: psycopg.Connection,
) -> None:
    """Access comes only through pgstac_ingest, which keeps pgSTAC config out."""
    rows = admin_db.execute(DIRECT_PGSTAC_GRANTS_SQL, {"role": APP_ROLE}).fetchall()
    assert [row[0] for row in rows] == []


@pytest.mark.integration
@pytest.mark.usefixtures("pgstac_grants_applied")
@pytest.mark.parametrize("role", [APP_ROLE, "pgstac_ingest"])
def test_role_cannot_create_in_pgstac(admin_db: psycopg.Connection, role: str) -> None:
    """CREATE would let the role shadow PostGIS functions pgSTAC calls unqualified."""
    row = admin_db.execute(
        "SELECT has_schema_privilege(%s, 'pgstac', 'CREATE')", (role,)
    ).fetchone()
    assert row == (False,)


@pytest.mark.integration
def test_grants_file_revokes_create_granted_back(
    admin_db: psycopg.Connection,
) -> None:
    """A pgSTAC migration can grant CREATE back; the next start revokes it."""
    admin_db.execute("GRANT CREATE ON SCHEMA pgstac TO pgstac_ingest")
    try:
        result = _apply_pgstac_grants()
        assert result.returncode == 0, result.stderr
        row = admin_db.execute(
            "SELECT has_schema_privilege('pgstac_ingest', 'pgstac', 'CREATE'), "
            "has_schema_privilege(%s, 'pgstac', 'CREATE')",
            (APP_ROLE,),
        ).fetchone()
        assert row == (False, False)
    finally:
        admin_db.execute("REVOKE CREATE ON SCHEMA pgstac FROM pgstac_ingest")


@pytest.mark.integration
def test_grants_file_revokes_direct_grants_from_a_restore(
    admin_db: psycopg.Connection,
) -> None:
    """Direct grants a restored dump brings back are gone after the next start."""
    role = sql.Identifier(APP_ROLE)
    seeds = [
        sql.SQL("GRANT USAGE ON SCHEMA pgstac TO {}").format(role),
        sql.SQL("GRANT SELECT ON pgstac.collections TO {}").format(role),
        sql.SQL("GRANT USAGE ON SEQUENCE pgstac.queryables_id_seq TO {}").format(role),
        sql.SQL("GRANT EXECUTE ON FUNCTION pgstac.search(jsonb) TO {}").format(role),
        sql.SQL(
            "ALTER DEFAULT PRIVILEGES IN SCHEMA pgstac GRANT SELECT ON TABLES TO {}"
        ).format(role),
    ] + [
        sql.SQL(
            "ALTER DEFAULT PRIVILEGES FOR ROLE pgstac_admin IN SCHEMA pgstac "
            "GRANT {} ON {} TO {}"
        ).format(sql.SQL(privilege), sql.SQL(objects), role)
        for privilege, objects in (
            ("SELECT", "TABLES"),
            ("USAGE", "SEQUENCES"),
            ("EXECUTE", "ROUTINES"),
            ("USAGE", "TYPES"),
        )
    ]
    try:
        for statement in seeds:
            admin_db.execute(statement)
        seeded = {
            row[0]
            for row in admin_db.execute(DIRECT_PGSTAC_GRANTS_SQL, {"role": APP_ROLE})
        }
        assert {
            "schema pgstac",
            "relation collections",
            "relation queryables_id_seq",
            "routine search(jsonb)",
            "default privileges on r",
            "default privileges on S",
            "default privileges on f",
            "default privileges on T",
        } <= seeded

        result = _apply_pgstac_grants()
        assert result.returncode == 0, result.stderr
        left = admin_db.execute(DIRECT_PGSTAC_GRANTS_SQL, {"role": APP_ROLE})
        assert [row[0] for row in left.fetchall()] == []
    finally:
        _apply_pgstac_grants()


@pytest.mark.integration
def test_app_role_cannot_create_a_function_in_pgstac(
    app_db: psycopg.Connection,
) -> None:
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        app_db.execute(
            "CREATE FUNCTION pgstac.stac_api_privilege_probe() RETURNS int "
            "LANGUAGE sql AS 'SELECT 1'"
        )


@pytest.mark.integration
def test_app_role_cannot_write_pgstac_configuration(
    app_db: psycopg.Connection,
) -> None:
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        app_db.execute(
            "INSERT INTO pgstac.queryable_wrappers VALUES ('stac_api_privilege_probe')"
        )


@pytest.mark.unit
def test_collection_id_carries_random_suffix(sample_stac_collection):
    """A fixed id turns one leftover row into a permanent 409."""
    suffix = sample_stac_collection["id"].rsplit("-", 1)[-1]
    assert re.fullmatch(r"[0-9a-f]{8}", suffix)
