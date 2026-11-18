"""Unit tests for the job response rules installed on pygeoapi's Flask app."""

from __future__ import annotations

import json
from typing import Any

import pytest
from flask import Flask, Response, request
from flask.testing import FlaskClient
from processes.jobs.http import (
    JOB_LIST_REL,
    install_job_http_rules,
    rewrite_job_control,
)

pytestmark = pytest.mark.unit

ASYNC_CAPABLE: list[str] = ["sync-execute", "async-execute"]
LANDING_HTML: str = f"""<head>
      <link rel="{JOB_LIST_REL}" type="application/json" title="Jobs" href="https://x/jobs"/>
      <link rel="self" href="https://x/"/>
</head>
  <section id="processes"><h2>Processes</h2></section>
  <section id="jobs">
      <h2>Jobs</h2>
      <p>
        <a title="Browse jobs" href="https://x/jobs">Browse jobs</a>
      </p>
  </section>
"""


class StubManager:
    """Declares job control per process, as processor metadata would."""

    def __init__(self, declared: dict[str, dict[str, Any]]) -> None:
        self.processes = {process_id: {} for process_id in declared}
        self._declared = declared

    def get_processor(self, process_id: str) -> Any:
        processor = type("Processor", (), {})()
        processor.metadata = self._declared[process_id]
        return processor


def _description(process_id: str) -> dict[str, Any]:
    return {
        "id": process_id,
        "jobControlOptions": ASYNC_CAPABLE,
        "links": [
            {"rel": JOB_LIST_REL, "href": "/jobs?f=json"},
            {"rel": "self", "href": f"/processes/{process_id}"},
        ],
    }


@pytest.fixture
def client() -> FlaskClient:
    app = Flask(__name__)
    manager = StubManager(
        {
            "lidar-fetch": {"jobControlOptions": ASYNC_CAPABLE},
            "water-distance": {},
        }
    )

    @app.get("/processes")
    def processes() -> Response:
        body = {
            "processes": [_description("lidar-fetch"), _description("water-distance")]
        }
        return Response(json.dumps(body))

    @app.get("/processes/<process_id>")
    def process(process_id: str) -> Response:
        return Response(json.dumps(_description(process_id)))

    @app.post("/processes/<process_id>/execution")
    def execution(process_id: str) -> Response:
        status = 201 if process_id == "lidar-fetch" else 200
        return Response("{}", status, headers={"Location": "https://x/jobs/1"})

    @app.get("/")
    def landing() -> Response:
        if request.args.get("f") == "html":
            return Response(LANDING_HTML, mimetype="text/html")
        links = [{"rel": JOB_LIST_REL, "href": "/jobs"}, {"rel": "self", "href": "/"}]
        return Response(json.dumps({"links": links}))

    install_job_http_rules(app, manager)
    return app.test_client()


def test_description_without_json_mimetype_is_rewritten(client):
    assert client.get("/processes/water-distance").get_json(force=True)[
        "jobControlOptions"
    ] == ["sync-execute"]
    assert (
        client.get("/processes/lidar-fetch").get_json(force=True)["jobControlOptions"]
        == ASYNC_CAPABLE
    )


def test_process_list_is_rewritten(client):
    listed = client.get("/processes").get_json(force=True)["processes"]

    assert all(JOB_LIST_REL not in str(p["links"]) for p in listed)

    assert {p["id"]: p["jobControlOptions"] for p in listed} == {
        "lidar-fetch": ASYNC_CAPABLE,
        "water-distance": ["sync-execute"],
    }


def test_location_dropped_from_sync_answers_only(client):
    assert "Location" not in client.post("/processes/water-distance/execution").headers
    assert (
        client.post("/processes/lidar-fetch/execution").headers["Location"]
        == "https://x/jobs/1"
    )


def test_description_drops_job_list_links(client):
    links = client.get("/processes/lidar-fetch").get_json(force=True)["links"]

    assert links == [{"rel": "self", "href": "/processes/lidar-fetch"}]


def test_unknown_process_keeps_its_job_control():
    payload = {"id": "other", "jobControlOptions": ASYNC_CAPABLE}

    assert (
        rewrite_job_control(payload, lambda process_id: None)["jobControlOptions"]
        == ASYNC_CAPABLE
    )


def test_landing_json_drops_the_job_list_link(client):
    links = client.get("/").get_json(force=True)["links"]

    assert links == [{"rel": "self", "href": "/"}]


def test_landing_html_drops_the_job_list(client):
    html = client.get("/?f=html").get_data(as_text=True)

    assert "/jobs" not in html
    assert '<link rel="self" href="https://x/"/>' in html
    assert '<section id="processes">' in html
