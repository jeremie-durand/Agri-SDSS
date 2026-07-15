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
