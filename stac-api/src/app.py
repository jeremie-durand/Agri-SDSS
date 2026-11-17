"""Entry point of the stac-api: the upstream stac-fastapi-pgstac app factory.

Started with ``uvicorn stac_api.app:create_app --factory``. Patches to the
upstream app belong here, in a ``create_app`` that wraps the upstream one.
"""

from stac_fastapi.pgstac.app import create_app

__all__ = ["create_app"]
