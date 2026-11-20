"""Unit tests for core/logging_setup.py."""

import logging
from logging.handlers import RotatingFileHandler
from unittest.mock import MagicMock, patch

import pytest
import structlog
from gis_pipeline.core.logging_setup import handle_error, setup_logging
from structlog.testing import capture_logs

ROOT_LEVEL_AT_IMPORT: int = logging.getLogger().level

# ---------------------------------------------------------------------------
# TestHandleError
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestHandleError:
    def test_raises_default_runtime_error(self) -> None:
        mock_logger = MagicMock()
        with pytest.raises(RuntimeError):
            handle_error(mock_logger, "something went wrong")

    def test_raises_custom_exception_class(self) -> None:
        mock_logger = MagicMock()
        with pytest.raises(ValueError):
            handle_error(mock_logger, "bad value", exc_class=ValueError)

    def test_message_preserved_in_exception(self) -> None:
        mock_logger = MagicMock()
        msg = "descriptive error message"
        with pytest.raises(RuntimeError, match=msg):
            handle_error(mock_logger, msg)

    def test_logger_exception_called(self) -> None:
        mock_logger = MagicMock()
        msg = "log this"
        with pytest.raises(RuntimeError):
            handle_error(mock_logger, msg)
        mock_logger.exception.assert_called_once_with(msg)

    def test_always_raises_never_returns(self) -> None:
        mock_logger = MagicMock()
        with pytest.raises(Exception):
            handle_error(mock_logger, "msg")


# ---------------------------------------------------------------------------
# TestSetupLogging
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.usefixtures("restore_logging_state")
class TestSetupLogging:
    def test_returns_object_with_info_method(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setattr(
            "gis_pipeline.core.logging_setup.Config.LOG_DIR", str(tmp_path)
        )
        logger = setup_logging()
        assert hasattr(logger, "info")
        assert hasattr(logger, "warning")

    def test_log_level_defaults_to_info(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setattr(
            "gis_pipeline.core.logging_setup.Config.LOG_DIR", str(tmp_path)
        )
        monkeypatch.delenv("LOG_LEVEL", raising=False)
        setup_logging()
        assert logging.getLogger().level == logging.INFO

    def test_log_level_env_override_debug(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setattr(
            "gis_pipeline.core.logging_setup.Config.LOG_DIR", str(tmp_path)
        )
        monkeypatch.setenv("LOG_LEVEL", "DEBUG")
        setup_logging()
        assert logging.getLogger().level == logging.DEBUG

    def test_permission_error_on_file_handler_does_not_raise(
        self, tmp_path, monkeypatch
    ) -> None:
        monkeypatch.setattr(
            "gis_pipeline.core.logging_setup.Config.LOG_DIR", str(tmp_path)
        )
        with patch.object(RotatingFileHandler, "__init__", side_effect=PermissionError):
            # Must not raise even if file handler cannot be created
            setup_logging()


@pytest.mark.unit
def test_setup_logging_tests_leave_no_logging_state() -> None:
    """Fail if TestSetupLogging leaked structlog or root logger state.

    Relies on pytest running this file in definition order, after the class.
    """
    root = logging.getLogger()

    with capture_logs() as logs:
        structlog.get_logger().debug("debug_event")

    assert logs == [{"event": "debug_event", "log_level": "debug"}]
    assert root.level == ROOT_LEVEL_AT_IMPORT
    assert not [
        handler
        for handler in root.handlers
        if isinstance(handler.formatter, structlog.stdlib.ProcessorFormatter)
    ]
