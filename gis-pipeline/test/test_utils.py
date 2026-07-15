"""Unit tests for gis_pipeline/utils.py logging utility functions."""

from unittest.mock import MagicMock

import pytest


@pytest.mark.unit
def test_generate_processing_report_logs_summary_header():
    """generate_processing_report must log the 'PROCESSING REPORT SUMMARY' header."""
    from gis_pipeline.utils import generate_processing_report

    mock_log = MagicMock()
    generate_processing_report(
        log=mock_log,
        report_data={"vector_data": {"processed": 0, "errors": 0, "skipped": 0}},
    )

    logged_strings = [str(c.args[0]) for c in mock_log.info.call_args_list]
    assert any("PROCESSING REPORT SUMMARY" in s for s in logged_strings)


@pytest.mark.unit
def test_generate_processing_report_logs_each_data_type():
    """generate_processing_report must emit a line for every top-level key."""
    from gis_pipeline.utils import generate_processing_report

    mock_log = MagicMock()
    generate_processing_report(
        log=mock_log,
        report_data={
            "vector_data": {"processed": 3, "errors": 0, "skipped": 1},
            "raster_data": {"processed": 2, "errors": 1, "skipped": 0},
        },
    )

    logged_strings = [str(c.args[0]) for c in mock_log.info.call_args_list]
    combined = " ".join(logged_strings).lower()
    assert "vector data" in combined
    assert "raster data" in combined


@pytest.mark.unit
def test_generate_processing_report_logs_stat_values():
    """generate_processing_report must log the actual counter values."""
    from gis_pipeline.utils import generate_processing_report

    mock_log = MagicMock()
    generate_processing_report(
        log=mock_log,
        report_data={"vector_data": {"processed": 42, "errors": 7, "skipped": 0}},
    )

    logged_strings = [str(c.args[0]) for c in mock_log.info.call_args_list]
    combined = " ".join(logged_strings)
    assert "42" in combined
    assert "7" in combined


@pytest.mark.unit
def test_add_section_to_logger_logs_title():
    """add_section_to_logger must log the section title string."""
    from gis_pipeline.utils import add_section_to_logger

    mock_log = MagicMock()
    add_section_to_logger(mock_log, "My Section Title")

    logged_strings = [str(c.args[0]) for c in mock_log.info.call_args_list]
    assert any("My Section Title" in s for s in logged_strings)


@pytest.mark.unit
def test_add_process_to_logger_logs_with_prefix():
    """add_process_to_logger must log with '[PROCESS]:' prefix."""
    from gis_pipeline.utils import add_process_to_logger

    mock_log = MagicMock()
    add_process_to_logger(mock_log, "Running ETL")

    logged_strings = [str(c.args[0]) for c in mock_log.info.call_args_list]
    assert any("[PROCESS]:" in s and "Running ETL" in s for s in logged_strings)
