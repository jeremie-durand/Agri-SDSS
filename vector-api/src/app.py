"""Custom Vector API Application.

This module creates a combined FastAPI application that includes:
1. TiPg (PostGIS-backed OGC API Features) at /postgis
2. Parquet router (DuckDB-backed) at /parquet

This allows serving both PostGIS collections and GeoParquet files
through a unified API with consistent namespace prefixes.
"""

import asyncio
import logging
from contextlib import asynccontextmanager

from agri_i18n.middleware import LocaleASGIMiddleware
from fastapi import FastAPI
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.openapi.utils import get_openapi
from starlette.middleware.cors import CORSMiddleware
from tipg.collections import register_collection_catalog
from tipg.database import close_db_connection, connect_to_db
from tipg.main import app as tipg_app
from tipg.settings import CustomSQLSettings, DatabaseSettings

from .config import (
    API_DESCRIPTION,
    EXTERNAL_ROOT,
    API_TITLE,
    API_VERSION,
    CORS_ALLOW_CREDENTIALS,
    CORS_ORIGINS,
    ENDPOINTS,
    PARQUET_COLLECTIONS,
    PARQUET_PREFIX,
    POSTGIS_COLLECTIONS,
    POSTGIS_PREFIX,
)
from .parquet_router import router as parquet_router
from .pedo_router import router as pedo_router
from .som_router import router as som_router
from .water_router import router as water_router


class MountRootPathMiddleware:
    """ASGI middleware that injects the mount prefix into the request scope.

    Notes :
        Create a fresh scope dict (avoiding upstream mutation) and force both
        root_path and app_root_path to the mount prefix so request.base_url
        returns the correct value regardless of Starlette version.

        The external proxy prefix is applied to the response body rather than
        the scope. Widening root_path to include it makes the sub-app fail to
        resolve its own routes (verified: /postgis/* returns 404), so the
        prefix is inserted into emitted hrefs after routing has happened.
    """

    def __init__(self, app: FastAPI, root_path: str, external_root: str = "") -> None:
        self.app = app
        self.root_path = root_path
        self.external_root = external_root

    @staticmethod
    def _origin(scope) -> str:
        """Public origin of the request, as the sub-app will emit it."""
        headers = {k.lower(): v for k, v in scope.get("headers", [])}
        host = headers.get(b"host", b"").decode() or "localhost"
        proto = headers.get(b"x-forwarded-proto", b"").decode() or scope.get(
            "scheme", "http"
        )
        return f"{proto}://{host}"

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] in ("http", "websocket"):
            scope = {
                **scope,
                "root_path": self.root_path,
                "app_root_path": self.root_path,
            }
        if not self.external_root:
            await self.app(scope, receive, send)
            return
        origin = self._origin(scope)
        needle = f"{origin}{self.root_path}".encode()
        replacement = f"{origin}{self.external_root}{self.root_path}".encode()
        await self.app(scope, receive, self._rewriting_send(send, needle, replacement))

    def _rewriting_send(self, send, needle: bytes, replacement: bytes):
        """Wrap send so hrefs in JSON bodies carry the proxy prefix."""
        state = {"rewrite": False}

        async def wrapped(message):
            if message["type"] == "http.response.start":
                headers = [
                    (k, v)
                    for k, v in message.get("headers", [])
                    if k.lower() != b"content-length"
                ]
                state["rewrite"] = any(
                    k.lower() == b"content-type" and b"json" in v.lower()
                    for k, v in headers
                )
                message = {**message, "headers": headers}
            elif message["type"] == "http.response.body" and state["rewrite"]:
                body = message.get("body", b"")
                if body:
                    message = {**message, "body": body.replace(needle, replacement)}
            await send(message)

        return wrapped


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

db_settings = DatabaseSettings()
custom_sql_settings = CustomSQLSettings()


_DB_INIT_RETRIES = 5
_DB_INIT_RETRY_DELAY_SECONDS = 5


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan that initialises TiPg's DB connection on the mounted sub-app.

    Retries on transient connection failures (e.g. database recovering from an
    unclean shutdown at startup).

    Notes :
        Create a fresh scope dict (avoiding upstream mutation) and force both
        root_path and app_root_path to the mount prefix so request.base_url
        returns the correct value regardless of Starlette version.
    """
    for attempt in range(1, _DB_INIT_RETRIES + 1):
        try:
            await connect_to_db(
                tipg_app,
                schemas=db_settings.schemas,
                tipg_schema=db_settings.tipg_schema,
                user_sql_files=custom_sql_settings.sql_files,
            )
            await register_collection_catalog(tipg_app, db_settings=db_settings)
            logger.info("TiPg DB connection and collection catalog initialised")
            break
        except Exception as exc:
            try:
                await close_db_connection(tipg_app)
            except Exception:
                pass
            if attempt < _DB_INIT_RETRIES:
                logger.warning(
                    f"DB init attempt {attempt}/{_DB_INIT_RETRIES} failed: {exc}. "
                    f"Retrying in {_DB_INIT_RETRY_DELAY_SECONDS}s..."
                )
                await asyncio.sleep(_DB_INIT_RETRY_DELAY_SECONDS)
            else:
                raise

    yield

    await close_db_connection(tipg_app)
    logger.info("TiPg DB connection closed")


# Create the main application
app = FastAPI(
    title=API_TITLE,
    description=API_DESCRIPTION,
    version=API_VERSION,
    lifespan=lifespan,
)

# Bind the request locale before routing so error messages localise.
# Accept-Language is CORS-safelisted, so this needs no CORS allowance.
app.add_middleware(LocaleASGIMiddleware)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=CORS_ALLOW_CREDENTIALS,
    allow_methods=["GET"],
    allow_headers=["*"],
)

# Mount TiPg under /postgis prefix, wrapped so request.base_url includes the prefix.
app.mount(
    POSTGIS_PREFIX,
    MountRootPathMiddleware(tipg_app, POSTGIS_PREFIX, EXTERNAL_ROOT),
)

# Include the Parquet router
app.include_router(parquet_router)

# Include the water-distance router
app.include_router(water_router)

# Include the pedo-coverage router
app.include_router(pedo_router)

# Include the SOM field-match router
app.include_router(som_router)

logger.info("Vector API initialized with TiPg + Parquet router")
logger.info(f"PostGIS collections available at: {POSTGIS_COLLECTIONS}")
logger.info(f"Parquet collections available at: {PARQUET_COLLECTIONS}")


@app.get("/", tags=["Landing"])
async def root_landing():
    """Root landing page for Vector API.

    Returns information about available data source namespaces.
    """
    return {
        "title": API_TITLE,
        "description": API_DESCRIPTION,
        "links": [
            {
                "href": POSTGIS_PREFIX,
                "rel": "data",
                "type": "application/json",
                "title": f"{ENDPOINTS['postgis']['title']}",
            },
            {
                "href": PARQUET_PREFIX,
                "rel": "data",
                "type": "application/json",
                "title": f"{ENDPOINTS['parquet']['title']}",
            },
            {
                "href": POSTGIS_COLLECTIONS,
                "rel": "data",
                "type": "application/json",
                "title": "PostGIS Collections List",
            },
            {
                "href": PARQUET_COLLECTIONS,
                "rel": "data",
                "type": "application/json",
                "title": "Parquet Collections List",
            },
        ],
    }


@app.get("/parquet/openapi.json", include_in_schema=False)
async def parquet_openapi_spec():
    """OpenAPI schema filtered to Parquet routes only."""
    parquet_routes = [
        route
        for route in app.routes
        if hasattr(route, "tags") and route.tags and "Parquet Collections" in route.tags
    ]
    return get_openapi(
        title=ENDPOINTS["parquet"]["title"],
        version=API_VERSION,
        description=ENDPOINTS["parquet"]["long_description"],
        routes=parquet_routes,
        servers=[{"url": EXTERNAL_ROOT}] if EXTERNAL_ROOT else None,
    )


@app.get("/parquet/api.html", include_in_schema=False)
async def parquet_swagger_ui():
    """Swagger UI for the Parquet Collections API."""
    return get_swagger_ui_html(
        openapi_url=f"{EXTERNAL_ROOT}/parquet/openapi.json",
        title=ENDPOINTS["parquet"]["title"],
    )


@app.get(PARQUET_PREFIX, tags=["Parquet Landing"])
async def parquet_landing():
    """Landing page for Parquet API namespace.

    Returns information about the Parquet API endpoints.
    """
    return {
        "title": ENDPOINTS["parquet"]["title"],
        "description": ENDPOINTS["parquet"]["long_description"],
        "links": [
            {
                "href": PARQUET_COLLECTIONS,
                "rel": "data",
                "type": "application/json",
                "title": "Parquet Collections",
            },
            {
                "href": POSTGIS_COLLECTIONS,
                "rel": "related",
                "type": "application/json",
                "title": ENDPOINTS["postgis"]["title"],
            },
        ],
    }
