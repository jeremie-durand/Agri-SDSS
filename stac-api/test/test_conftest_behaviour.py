"""The integration client fixture must skip only for an absent database."""
import pytest

from stac_api.test import conftest


@pytest.mark.unit
def test_client_fixture_reraises_unexpected_errors(monkeypatch):
    """A non-connection error must propagate, not become a skip."""

    class _Boom(TypeError):
        pass

    def _explode(*_args, **_kwargs):
        raise _Boom("programming error, not a missing database")

    monkeypatch.setattr(conftest, "TestClient", _explode)

    gen = conftest.stac_integration_client.__wrapped__()
    with pytest.raises(_Boom):
        next(gen)


@pytest.mark.unit
def test_client_fixture_skips_when_database_unreachable(monkeypatch):
    """A connection-level failure is still a legitimate skip."""

    def _unreachable(*_args, **_kwargs):
        raise ConnectionRefusedError("no database here")

    monkeypatch.setattr(conftest, "TestClient", _unreachable)

    gen = conftest.stac_integration_client.__wrapped__()
    with pytest.raises(pytest.skip.Exception):
        next(gen)
