"""
Wrapper for stac_fastapi.pgstac.app that patches the deprecated ORJSONResponse
before the library initializes its routes.

stac-fastapi uses ORJSONResponse internally (deprecated in FastAPI 0.131+).
We replace it with a custom JSONResponse backed by orjson to preserve
performance while silencing the deprecation warning.
"""

import warnings


def configure_warnings() -> None:
    """Suppress the ORJSONResponse FastAPI deprecation warning.

    Must be called before any stac_fastapi import: the warning fires at import
    time of stac_fastapi.api.models. Omitting ``category`` matches both
    FastAPIDeprecationWarning and DeprecationWarning.
    """
    warnings.filterwarnings(
        "ignore",
        message=".*ORJSONResponse.*",
    )


# Register before any stac_fastapi import
configure_warnings()

import stac_fastapi.api.models as _stac_models  # noqa: E402

try:
    from typing import Any

    import orjson
    from fastapi.responses import JSONResponse as _JSONResponse

    class _OrjsonResponse(_JSONResponse):
        """Drop-in for ORJSONResponse that avoids the FastAPI deprecation."""

        media_type = "application/json"

        def render(self, content: Any) -> bytes:
            return orjson.dumps(
                content,
                option=orjson.OPT_NON_STR_KEYS | orjson.OPT_SERIALIZE_NUMPY,
            )

    # (stac-fastapi): if a future release drops its internal ORJSONResponse
    # usage, this entire try/except block becomes dead code and should be removed.
    _stac_models.JSONResponse = _OrjsonResponse  # type: ignore[attr-defined]
except ImportError:
    pass

from stac_fastapi.pgstac.app import app  # noqa: E402, F401
