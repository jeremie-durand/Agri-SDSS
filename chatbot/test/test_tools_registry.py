import asyncio

import pytest
from tools_registry import (
    SDSS_TOOLS,
    execute_pygeoapi_process,
    get_process_schema,
    list_pygeoapi_processes,
)


@pytest.mark.unit
def test_sdss_tools_contains_pygeoapi_tools():
    assert isinstance(SDSS_TOOLS, set)
    assert list_pygeoapi_processes in SDSS_TOOLS
    assert get_process_schema in SDSS_TOOLS
    assert execute_pygeoapi_process in SDSS_TOOLS


@pytest.mark.unit
def test_pygeoapi_tools_are_async():
    import asyncio

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
    import agri_i18n
    import tools_registry

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
