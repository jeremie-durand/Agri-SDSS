"""Gunicorn entry point for process-api.

Wraps pygeoapi's Flask application so the request locale is bound before any
processor runs. pygeoapi negotiates a locale for its own responses but never
threads it into ``BaseProcessor.execute``, so processors would otherwise have
no way to localise the errors they raise.

Importing ``pygeoapi.flask_app`` reads ``PYGEOAPI_CONFIG`` and
``PYGEOAPI_OPENAPI`` at module load; ``start.sh`` exports both beforehand.
"""

from agri_i18n.middleware import LocaleWSGIMiddleware
from pygeoapi.flask_app import APP as PYGEOAPI_APP

APP = LocaleWSGIMiddleware(PYGEOAPI_APP)

__all__ = ["APP"]
