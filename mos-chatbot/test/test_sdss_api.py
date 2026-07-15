from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sdss_api import _build_process_catalog, _extract_text_tool_call, router


@pytest.mark.unit
def test_extract_text_tool_call_valid():
    content = '{"name": "list_pygeoapi_processes", "parameters": {}}'
    result = _extract_text_tool_call(content)
    assert result is not None
    assert result[0]["name"] == "list_pygeoapi_processes"
    assert result[0]["parameters"] == {}


@pytest.mark.unit
def test_extract_text_tool_call_with_arguments_key():
    content = '{"name": "execute_pygeoapi_process", "arguments": {"process_id": "hello-world-pygeoapi", "inputs": {"name": "Alice"}}}'
    result = _extract_text_tool_call(content)
    assert result is not None
    assert result[0]["name"] == "execute_pygeoapi_process"


@pytest.mark.unit
def test_extract_text_tool_call_unknown_tool():
    content = '{"name": "unknown_tool", "parameters": {}}'
    assert _extract_text_tool_call(content) is None


@pytest.mark.unit
def test_extract_text_tool_call_plain_text():
    assert _extract_text_tool_call("Hello, here are the processes:") is None


@pytest.mark.unit
def test_extract_text_tool_call_invalid_json():
    assert _extract_text_tool_call("{not valid json}") is None


@pytest.mark.unit
def test_extract_text_tool_call_empty_string():
    assert _extract_text_tool_call("") is None


@pytest.mark.unit
def test_extract_text_tool_call_missing_name_key():
    """JSON object with no name/function field must return None."""
    assert _extract_text_tool_call('{"parameters": {}}') is None


@pytest.mark.unit
def test_router_has_query_endpoint():
    routes = {r.path for r in router.routes}
    assert "/query" in routes


@pytest.mark.mocked
async def test_build_process_catalog_formats_inputs():
    mock_processes = [
        {
            "id": "hello-world-pygeoapi",
            "title": "Hello World",
            "description": "Echoes a name",
        }
    ]
    mock_schema = {
        "inputs": {
            "name": {
                "schema": {"type": "string"},
                "description": "The name to echo",
                "minOccurs": 1,
            }
        }
    }
    with (
        patch(
            "sdss_api.list_pygeoapi_processes",
            new=AsyncMock(return_value=mock_processes),
        ),
        patch("sdss_api.get_process_schema", new=AsyncMock(return_value=mock_schema)),
    ):
        catalog = await _build_process_catalog()

    assert "hello-world-pygeoapi" in catalog
    assert "name (string)" in catalog
    assert "[required]" in catalog
    assert "The name to echo" in catalog


@pytest.mark.mocked
async def test_build_process_catalog_handles_schema_failure():
    mock_processes = [
        {"id": "broken-process", "title": "Broken", "description": "Fails"}
    ]
    with (
        patch(
            "sdss_api.list_pygeoapi_processes",
            new=AsyncMock(return_value=mock_processes),
        ),
        patch(
            "sdss_api.get_process_schema",
            new=AsyncMock(side_effect=Exception("timeout")),
        ),
    ):
        catalog = await _build_process_catalog()

    assert "broken-process" in catalog


@pytest.mark.mocked
async def test_build_process_catalog_handles_list_failure():
    with patch(
        "sdss_api.list_pygeoapi_processes",
        new=AsyncMock(side_effect=Exception("network error")),
    ):
        catalog = await _build_process_catalog()

    assert "unavailable" in catalog


@pytest.mark.unit
def test_sdss_query_no_auth_required_when_disabled(monkeypatch):
    """When ENABLE_AUTH=false, /sdss/query passes without any API key."""
    monkeypatch.setenv("ENABLE_AUTH", "false")
    monkeypatch.setenv("API_KEY", "secret")
    monkeypatch.setenv("LLM_API_KEY", "")
    app = FastAPI()
    app.include_router(router, prefix="/sdss")
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.post("/sdss/query", json={"query": "hello"})
    assert resp.status_code == 503  # LLM_API_KEY missing, not 401


@pytest.mark.unit
def test_sdss_query_rejects_missing_key_when_auth_enabled(monkeypatch):
    """When ENABLE_AUTH=true, missing X-API-Key returns 401."""
    monkeypatch.setenv("ENABLE_AUTH", "true")
    monkeypatch.setenv("API_KEY", "secret")
    app = FastAPI()
    app.include_router(router, prefix="/sdss")
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.post("/sdss/query", json={"query": "hello"})
    assert resp.status_code == 401


@pytest.mark.unit
def test_sdss_query_rejects_wrong_key_when_auth_enabled(monkeypatch):
    """When ENABLE_AUTH=true, wrong X-API-Key returns 401."""
    monkeypatch.setenv("ENABLE_AUTH", "true")
    monkeypatch.setenv("API_KEY", "secret")
    app = FastAPI()
    app.include_router(router, prefix="/sdss")
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.post(
        "/sdss/query",
        json={"query": "hello"},
        headers={"X-API-Key": "wrong"},
    )
    assert resp.status_code == 401


@pytest.mark.unit
def test_sdss_query_passes_correct_key_when_auth_enabled(monkeypatch):
    """When ENABLE_AUTH=true, correct X-API-Key proceeds past auth (503 for missing LLM key)."""
    monkeypatch.setenv("ENABLE_AUTH", "true")
    monkeypatch.setenv("API_KEY", "secret")
    monkeypatch.setenv("LLM_API_KEY", "")
    app = FastAPI()
    app.include_router(router, prefix="/sdss")
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.post(
        "/sdss/query",
        json={"query": "hello"},
        headers={"X-API-Key": "secret"},
    )
    assert resp.status_code == 503  # auth passed, LLM key missing
