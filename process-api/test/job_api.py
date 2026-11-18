"""A pygeoapi Processes API over a chosen jobs table, for integration tests.

``pygeoapi.flask_app`` reads its config once at import, so the tests mount
pygeoapi's own request handlers on a small Flask app built from the service
config, with the manager pointed at a throwaway table and test processors.
"""

from __future__ import annotations

import copy
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pygeoapi.api.processes as processes_api
from flask import Flask, Response, make_response, request
from processes.jobs.http import install_job_http_rules
from pygeoapi.api import API, APIRequest
from pygeoapi.util import yaml_load

from agri_i18n.middleware import LocaleWSGIMiddleware

SERVICE_CONFIG: Path = Path("/app/config/pygeoapi-config.yaml")
PUBLIC_URL: str = "https://agri.example.org/process-api"


def api_config(table: str, resources: dict[str, Any]) -> dict[str, Any]:
    """The service config with the jobs table and processes replaced."""
    with SERVICE_CONFIG.open() as fh:
        config = copy.deepcopy(yaml_load(fh))
    config["server"]["url"] = PUBLIC_URL
    config["server"]["manager"] = {
        "name": "processes.jobs.manager.AgriJobManager",
        "connection": {"table": table},
        "output_dir": None,
    }
    config["logging"] = {"level": "ERROR"}
    config["resources"] = resources
    return config


def build_app(config: dict[str, Any]) -> Flask:
    """Flask app routing the Processes endpoints to pygeoapi's handlers."""
    api = API(config, {})
    app = Flask(__name__)

    def respond(handler: Callable[..., Any], *args: Any) -> Response:
        api_request = APIRequest.from_flask(request, api.locales)
        headers, status, content = handler(api, api_request, *args)
        response = make_response(content, status)
        response.headers.update(headers)
        return response

    @app.get("/processes")
    def processes() -> Response:
        return respond(processes_api.describe_processes)

    @app.get("/processes/<process_id>")
    def process(process_id: str) -> Response:
        return respond(processes_api.describe_processes, process_id)

    @app.post("/processes/<process_id>/execution")
    def execution(process_id: str) -> Response:
        return respond(processes_api.execute_process, process_id)

    @app.get("/jobs")
    def jobs() -> Response:
        return respond(processes_api.get_jobs)

    @app.get("/jobs/<job_id>")
    def job(job_id: str) -> Response:
        return respond(processes_api.get_jobs, job_id)

    @app.get("/jobs/<job_id>/results")
    def results(job_id: str) -> Response:
        return respond(processes_api.get_job_result, job_id)

    install_job_http_rules(app, api.manager)
    app.wsgi_app = LocaleWSGIMiddleware(app.wsgi_app)
    return app
