import importlib
import re
import sys
import types
import warnings

import pytest

try:
    import orjson

    ORJSON_AVAILABLE = True
except ImportError:
    ORJSON_AVAILABLE = False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_app_module() -> types.ModuleType:
    """Return the stac_api.app module, reloading to capture fresh state."""
    return sys.modules.get("stac_api.app") or importlib.import_module("stac_api.app")


# ---------------------------------------------------------------------------
# _OrjsonResponse tests (skipped when orjson is not installed)
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.skipif(not ORJSON_AVAILABLE, reason="orjson not installed")
def test_orjson_response_media_type() -> None:
    """_OrjsonResponse must advertise application/json."""
    app_module = _get_app_module()
    OrjsonResponse = app_module._OrjsonResponse  # type: ignore[attr-defined]
    assert OrjsonResponse.media_type == "application/json"


@pytest.mark.unit
@pytest.mark.skipif(not ORJSON_AVAILABLE, reason="orjson not installed")
def test_orjson_response_render_returns_bytes() -> None:
    """render() must return bytes."""
    app_module = _get_app_module()
    OrjsonResponse = app_module._OrjsonResponse  # type: ignore[attr-defined]
    instance = OrjsonResponse.__new__(OrjsonResponse)
    result = instance.render({"key": "value"})
    assert isinstance(result, bytes)


@pytest.mark.unit
@pytest.mark.skipif(not ORJSON_AVAILABLE, reason="orjson not installed")
def test_orjson_response_render_valid_json() -> None:
    """render() output must be valid JSON matching the input."""
    app_module = _get_app_module()
    OrjsonResponse = app_module._OrjsonResponse  # type: ignore[attr-defined]
    instance = OrjsonResponse.__new__(OrjsonResponse)

    payload = {"name": "mos-gis", "version": 1, "active": True, "tags": ["stac", "api"]}
    result = instance.render(payload)

    decoded = orjson.loads(result)
    assert decoded == payload


@pytest.mark.unit
@pytest.mark.skipif(not ORJSON_AVAILABLE, reason="orjson not installed")
def test_orjson_response_render_non_str_keys() -> None:
    """render() must serialise dicts with non-string keys (OPT_NON_STR_KEYS)."""
    app_module = _get_app_module()
    OrjsonResponse = app_module._OrjsonResponse  # type: ignore[attr-defined]
    instance = OrjsonResponse.__new__(OrjsonResponse)

    result = instance.render({1: "one", 2: "two"})
    decoded = orjson.loads(result)
    # orjson converts integer keys to strings
    assert decoded == {"1": "one", "2": "two"}


@pytest.mark.unit
@pytest.mark.skipif(not ORJSON_AVAILABLE, reason="orjson not installed")
def test_orjson_response_render_list() -> None:
    """render() must handle list content."""
    app_module = _get_app_module()
    OrjsonResponse = app_module._OrjsonResponse  # type: ignore[attr-defined]
    instance = OrjsonResponse.__new__(OrjsonResponse)

    result = instance.render([1, "two", None])
    assert orjson.loads(result) == [1, "two", None]


@pytest.mark.unit
@pytest.mark.skipif(not ORJSON_AVAILABLE, reason="orjson not installed")
def test_orjson_response_render_nested() -> None:
    """render() must handle nested structures."""
    app_module = _get_app_module()
    OrjsonResponse = app_module._OrjsonResponse  # type: ignore[attr-defined]
    instance = OrjsonResponse.__new__(OrjsonResponse)

    payload = {
        "collections": [{"id": "s2-l2a", "bbox": [-74.66, 44.99, -69.62, 47.41]}]
    }
    result = instance.render(payload)
    assert orjson.loads(result) == payload


# ---------------------------------------------------------------------------
# Patch side-effect tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.skipif(not ORJSON_AVAILABLE, reason="orjson not installed")
def test_stac_models_patched() -> None:
    """stac_fastapi.api.models.JSONResponse must be replaced with _OrjsonResponse."""
    import stac_fastapi.api.models as stac_models

    app_module = _get_app_module()
    OrjsonResponse = app_module._OrjsonResponse  # type: ignore[attr-defined]
    assert stac_models.JSONResponse is OrjsonResponse


# ---------------------------------------------------------------------------
# Warning filter tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_configure_warnings_adds_filter() -> None:
    """configure_warnings() must add an ORJSONResponse ignore filter.

    Verified in isolation via catch_warnings() so pytest's own filter state
    does not interfere.
    """
    app_module = _get_app_module()

    with warnings.catch_warnings():
        warnings.resetwarnings()  # clear all filters inside this context
        app_module.configure_warnings()

        # Each entry is (action, compiled_message_re, category, compiled_module_re, lineno).
        matched = any(
            f[0] == "ignore"
            and f[1] is not None
            and re.search("ORJSONResponse", f[1].pattern, re.IGNORECASE)
            for f in warnings.filters
        )

    assert (
        matched
    ), "configure_warnings() did not register an ORJSONResponse ignore filter"


@pytest.mark.unit
def test_configure_warnings_suppresses_warning() -> None:
    """configure_warnings() must cause ORJSONResponse DeprecationWarnings to be ignored."""
    app_module = _get_app_module()

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")  # start clean — catch everything
        app_module.configure_warnings()  # apply the filter under test
        warnings.warn("ORJSONResponse is deprecated", DeprecationWarning, stacklevel=1)

    orjson_warnings = [w for w in caught if "ORJSONResponse" in str(w.message)]
    assert len(orjson_warnings) == 0, "ORJSONResponse warning was not suppressed"
