"""Gunicorn entry point for process-api.

Wraps pygeoapi's Flask application so the request locale is bound before any
processor runs. pygeoapi negotiates a locale for its own responses but never
threads it into ``BaseProcessor.execute``, so processors would otherwise have
no way to localise the errors they raise.

Importing ``pygeoapi.flask_app`` reads ``PYGEOAPI_CONFIG`` and
``PYGEOAPI_OPENAPI`` at module load; ``start.sh`` exports both beforehand.
The job response rules (``jobs/http.py``) are installed on that app here.
"""

from pygeoapi.flask_app import APP as PYGEOAPI_APP
from pygeoapi.flask_app import api_ as PYGEOAPI_API

from agri_i18n.middleware import LocaleWSGIMiddleware

from .jobs.http import install_job_http_rules

install_job_http_rules(PYGEOAPI_APP, PYGEOAPI_API.manager)

APP = LocaleWSGIMiddleware(PYGEOAPI_APP)

__all__ = ["APP"]
