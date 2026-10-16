"""
Entry point wrapper — imports the upstream FastAPI app and mounts the SDSS router.

uvicorn runs this module (sdss_main:app) instead of fastapi_app:app so that
/sdss/* routes are available alongside all upstream routes.
"""

from agri_i18n.middleware import LocaleASGIMiddleware
from fastapi_app import app
from sdss_api import router as sdss_router
from starlette.middleware.cors import CORSMiddleware

app.include_router(sdss_router, prefix="/sdss")

# Negotiates Accept-Language for every route. /sdss/query overrides this from
# its request body, which carries the language the chat UI is displaying.
app.add_middleware(LocaleASGIMiddleware)


def _hoist_cors_to_outermost() -> None:
    """Move CORSMiddleware to the front of the middleware list.

    Starlette's add_middleware inserts at index 0, so the middleware registered
    last ends up outermost. Upstream registers CORS and then the API key check,
    which puts the auth middleware in front of CORS: a 401 short-circuits before
    CORSMiddleware can attach its headers, and a browser reports the rejection
    as a CORS failure instead of an authentication error. Upstream's comment
    ("registered AFTER CORSMiddleware so CORS headers are always added") reads
    the ordering backwards.

    Reordering here keeps the fix out of fastapi_app.py, which stays upstream.
    """
    cors = next(
        (m for m in app.user_middleware if m.cls is CORSMiddleware),
        None,
    )
    if cors is None:
        return
    app.user_middleware.remove(cors)
    app.user_middleware.insert(0, cors)
    app.middleware_stack = app.build_middleware_stack()


_hoist_cors_to_outermost()
