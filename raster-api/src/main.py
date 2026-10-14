"""Custom Raster API Application.

Extends the stock TiTiler application with a /collections endpoint so the
frontend data catalog can discover locally-mounted COG files, which TiTiler
itself has no mechanism to list (it only serves a COG given its exact path).
"""
from titiler.application.main import app

from .collections_router import router as collections_router

# Mutates the shared TiTiler app singleton in place (not a copy) so every
# existing route, middleware, and OpenAPI entry is preserved unchanged.
app.include_router(collections_router)
