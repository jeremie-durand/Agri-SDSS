"""Response fixes pygeoapi needs once its process manager is async.

pygeoapi derives every served ``jobControlOptions`` from ``manager.is_async``
instead of the process metadata, so it would advertise ``async-execute`` for
processes that always answer synchronously. It also adds a ``Location`` job
link to every execution answer, although only async jobs are recorded, and its
landing page and process descriptions link the job list, which home nginx
does not serve publicly. These are corrected after each request; HTML process
pages are left as pygeoapi renders them.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from functools import cache
from typing import Any

from flask import Flask, Response, request
from pygeoapi.process.manager.base import BaseManager
from pygeoapi.util import ProcessExecutionMode

PROCESS_PATH: re.Pattern[str] = re.compile(r"^/processes(?:/[^/]+)?/?$")
EXECUTION_PATH: re.Pattern[str] = re.compile(r"^/processes/[^/]+/execution/?$")
JOB_LIST_REL: str = "http://www.opengis.net/def/rel/ogc/1.0/job-list"
HTML_JOB_LIST: tuple[re.Pattern[str], ...] = (
    re.compile(rf'\s*<link [^>]*rel="{re.escape(JOB_LIST_REL)}"[^>]*/>'),
    re.compile(r'\s*<section id="jobs">.*?</section>', re.DOTALL),
)
SYNC_ONLY: list[str] = [ProcessExecutionMode.sync_execute.value]


def rewrite_job_control(
    payload: dict[str, Any], declared: Callable[[str], list[str] | None]
) -> dict[str, Any]:
    """Give each process its declared ``jobControlOptions`` and drop its links
    to the job list."""
    descriptions = payload.get("processes", [payload])
    for description in descriptions:
        options = declared(description.get("id", ""))
        if options is not None and "jobControlOptions" in description:
            description["jobControlOptions"] = options
        drop_job_list_link(description)
    return payload


def drop_job_list_link(payload: dict[str, Any]) -> dict[str, Any]:
    """Remove links to the job list from a landing page or description."""
    payload["links"] = [
        link for link in payload.get("links", []) if link.get("rel") != JOB_LIST_REL
    ]
    return payload


def drop_html_job_list(html: str) -> str:
    """Remove the job list link and section from the HTML landing page."""
    for pattern in HTML_JOB_LIST:
        html = pattern.sub("", html)
    return html


def _drop_landing_job_list(response: Response) -> None:
    payload = response.get_json(force=True, silent=True)
    if isinstance(payload, dict):
        response.set_data(json.dumps(drop_job_list_link(payload)))
    else:
        response.set_data(drop_html_job_list(response.get_data(as_text=True)))


def install_job_http_rules(app: Flask, manager: BaseManager) -> None:
    """Register the response fixes on pygeoapi's Flask application."""

    @cache
    def declared(process_id: str) -> list[str] | None:
        if process_id not in manager.processes:
            return None
        metadata = manager.get_processor(process_id).metadata
        return list(metadata.get("jobControlOptions", SYNC_ONLY))

    @app.after_request
    def apply_job_rules(response: Response) -> Response:
        if request.method == "GET" and request.path == "/":
            _drop_landing_job_list(response)
        elif request.method == "GET" and PROCESS_PATH.match(request.path):
            payload = response.get_json(force=True, silent=True)
            if isinstance(payload, dict):
                response.set_data(json.dumps(rewrite_job_control(payload, declared)))
        elif (
            request.method == "POST"
            and EXECUTION_PATH.match(request.path)
            and response.status_code != 201
        ):
            response.headers.pop("Location", None)
        return response
