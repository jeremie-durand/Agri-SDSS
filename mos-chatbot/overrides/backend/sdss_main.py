"""
Entry point wrapper — imports the upstream FastAPI app and mounts the SDSS router.

uvicorn runs this module (sdss_main:app) instead of fastapi_app:app so that
/sdss/* routes are available alongside all upstream routes.
"""

from fastapi_app import app
from sdss_api import router as sdss_router

app.include_router(sdss_router, prefix="/sdss")
