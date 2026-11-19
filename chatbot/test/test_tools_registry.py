import asyncio

import pytest
import tools_registry
from tools_registry import (
    SDSS_TOOLS,
    execute_pygeoapi_process,
    get_process_schema,
    list_pygeoapi_processes,
)

import agri_i18n


@pytest.mark.unit
def test_sdss_tools_contains_pygeoapi_tools():
    assert isinstance(SDSS_TOOLS, set)
    assert list_pygeoapi_processes in SDSS_TOOLS
    assert get_process_schema in SDSS_TOOLS
    assert execute_pygeoapi_process in SDSS_TOOLS


@pytest.mark.unit
def test_pygeoapi_tools_are_async():
    assert asyncio.iscoroutinefunction(list_pygeoapi_processes)
    assert asyncio.iscoroutinefunction(get_process_schema)
    assert asyncio.iscoroutinefunction(execute_pygeoapi_process)


@pytest.mark.unit
@pytest.mark.parametrize("language,expected", [("en", "en"), ("fr", "fr")])
def test_tool_calls_forward_the_bound_locale(monkeypatch, language, expected):
    """Server-side tool calls carry Accept-Language to process-api.

    No browser header reaches these calls, so without this the LLM's process
    catalog and error messages would always be the platform default whatever
    language the user is chatting in.
    """
    captured = {}

    class _FakeClient:
        def __init__(self, *args, **kwargs):
            captured["headers"] = kwargs.get("headers")

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def get(self, url):
            return _FakeResponse()

        async def post(self, url, json=None):
            return _FakeResponse()

    class _FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"processes": []}

    monkeypatch.setattr(tools_registry.httpx, "AsyncClient", _FakeClient)

    with agri_i18n.use_locale(language):
        asyncio.run(tools_registry.list_pygeoapi_processes())

    assert captured["headers"] == {"Accept-Language": expected}


class _JobFakeClient:
    """httpx.AsyncClient stand-in replaying scripted process-api answers."""

    answers: list = []
    calls: list = []
    client_headers: list = []

    def __init__(self, *args, **kwargs):
        _JobFakeClient.client_headers.append(kwargs.get("headers"))

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, url):
        _JobFakeClient.calls.append(("GET", url, None))
        return _JobFakeClient.answers.pop(0)

    async def post(self, url, json=None, headers=None):
        _JobFakeClient.calls.append(("POST", url, headers))
        return _JobFakeClient.answers.pop(0)


class _JobResponse:
    def __init__(self, status_code=200, body=None, location=None):
        self.status_code = status_code
        self._body = body
        self.headers = {"Location": location} if location else {}

    def raise_for_status(self):
        return None

    def json(self):
        return self._body


PUBLIC_LOCATION = "https://example.org/process-api/jobs/abc"


@pytest.fixture
def job_client(monkeypatch):
    _JobFakeClient.answers = []
    _JobFakeClient.calls = []
    _JobFakeClient.client_headers = []
    monkeypatch.setattr(tools_registry.httpx, "AsyncClient", _JobFakeClient)
    monkeypatch.setattr(tools_registry, "PROCESS_POLL_SECONDS", 0)
    return _JobFakeClient


@pytest.mark.mocked
def test_sync_answer_is_returned_unchanged(job_client):
    job_client.answers = [_JobResponse(200, {"distance_m": 12})]

    result = asyncio.run(execute_pygeoapi_process("water-distance", {"farm_id": 1}))

    assert result == {"distance_m": 12}
    method, url, headers = job_client.calls[0]
    assert (method, url) == (
        "POST",
        "http://process-api:5000/processes/water-distance/execution",
    )
    assert headers == {"Prefer": "respond-async"}
    assert len(job_client.calls) == 1


@pytest.mark.mocked
def test_async_job_is_polled_on_the_internal_url_until_results(job_client):
    job_client.answers = [
        _JobResponse(201, location=PUBLIC_LOCATION),
        _JobResponse(200, {"status": "accepted"}),
        _JobResponse(200, {"status": "running"}),
        _JobResponse(200, {"status": "successful"}),
        _JobResponse(200, {"assets": {"dtm": {}}}),
    ]

    result = asyncio.run(execute_pygeoapi_process("lidar-fetch", {"products": ["dtm"]}))

    assert result == {"assets": {"dtm": {}}}
    assert [url for _, url, _ in job_client.calls[1:]] == [
        "http://process-api:5000/jobs/abc?f=json",
        "http://process-api:5000/jobs/abc?f=json",
        "http://process-api:5000/jobs/abc?f=json",
        "http://process-api:5000/jobs/abc/results?f=json",
    ]


@pytest.mark.mocked
def test_lidar_flowpath_runs_as_a_job_and_returns_the_asset_hrefs(job_client):
    ls_href = "https://example.org/cog/lidar_flowpath_ls_farm_7_m300_v1.tif"
    results = {
        "stac_items": ["lidar_flowpath_ls_farm_7_m300_v1"],
        "assets": {"ls": {"href": ls_href}},
        "summary": {"ls": {"mean": 0.82}},
    }
    job_client.answers = [
        _JobResponse(201, location=PUBLIC_LOCATION),
        _JobResponse(200, {"status": "successful"}),
        _JobResponse(200, results),
    ]
    inputs = {"location_type": "farm_id", "farm_id": "7"}

    result = asyncio.run(execute_pygeoapi_process("lidar-flowpath", inputs))

    assert result == results
    assert job_client.calls[0] == (
        "POST",
        "http://process-api:5000/processes/lidar-flowpath/execution",
        {"Prefer": "respond-async"},
    )
    assert [url for _, url, _ in job_client.calls[1:]] == [
        "http://process-api:5000/jobs/abc?f=json",
        "http://process-api:5000/jobs/abc/results?f=json",
    ]


@pytest.mark.mocked
def test_failed_job_raises_with_its_message(job_client):
    job_client.answers = [
        _JobResponse(201, location=PUBLIC_LOCATION),
        _JobResponse(200, {"status": "failed", "message": "Paramètres invalides"}),
    ]

    with pytest.raises(tools_registry.ProcessJobFailed, match="Paramètres invalides"):
        asyncio.run(execute_pygeoapi_process("lidar-fetch", {}))


@pytest.mark.mocked
def test_wait_cap_returns_the_job_id_and_status(job_client, monkeypatch):
    monkeypatch.setattr(tools_registry, "PROCESS_WAIT_SECONDS", 0)
    job_client.answers = [
        _JobResponse(201, location=PUBLIC_LOCATION),
        _JobResponse(200, {"status": "running"}),
    ]

    result = asyncio.run(execute_pygeoapi_process("som-predict-soil", {}))

    assert result["job_id"] == "abc"
    assert result["job_url"] == PUBLIC_LOCATION
    assert result["status"] == "running"
    assert "still running" in result["message"]


@pytest.mark.mocked
def test_every_job_request_carries_the_locale(job_client):
    job_client.answers = [
        _JobResponse(201, location=PUBLIC_LOCATION),
        _JobResponse(200, {"status": "successful"}),
        _JobResponse(200, {"value": 1}),
    ]

    with agri_i18n.use_locale("en"):
        asyncio.run(execute_pygeoapi_process("lidar-fetch", {}))

    assert len(job_client.calls) == 3
    assert job_client.client_headers == [{"Accept-Language": "en"}]


class _SteppingClock:
    """``time`` stand-in whose clock moves 300 s at every reading."""

    def __init__(self):
        self.now = -300.0

    def monotonic(self):
        self.now += 300.0
        return self.now


@pytest.mark.mocked
def test_calls_of_one_request_share_the_wait_budget(job_client, monkeypatch):
    monkeypatch.setattr(tools_registry, "time", _SteppingClock())
    monkeypatch.setattr(tools_registry, "PROCESS_WAIT_SECONDS", 480)
    job_client.answers = [
        _JobResponse(201, location=PUBLIC_LOCATION),
        _JobResponse(200, {"status": "running"}),
        _JobResponse(200, {"status": "successful"}),
        _JobResponse(200, {"value": 1}),
        _JobResponse(201, location="https://example.org/process-api/jobs/def"),
        _JobResponse(200, {"status": "running"}),
    ]

    async def one_request():
        tools_registry.start_process_wait_budget()
        first = await execute_pygeoapi_process("lidar-fetch", {})
        second = await execute_pygeoapi_process("sentinel-fetch", {})
        return first, second

    first, second = asyncio.run(one_request())

    assert first == {"value": 1}
    assert second["job_id"] == "def"
    assert second["status"] == "running"
    assert job_client.answers == []
