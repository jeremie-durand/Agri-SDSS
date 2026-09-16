import pytest


@pytest.mark.unit
def test_gis_pipeline_error_is_exception():
    """GISPipelineError must be a subclass of Exception."""
    from gis_pipeline.core.exceptions import GISPipelineError

    assert issubclass(GISPipelineError, Exception)


@pytest.mark.unit
def test_vector_processing_error_is_gis_pipeline_error():
    """VectorProcessingError must be catchable as GISPipelineError."""
    from gis_pipeline.core.exceptions import GISPipelineError, VectorProcessingError

    assert issubclass(VectorProcessingError, GISPipelineError)


@pytest.mark.unit
def test_raster_processing_error_is_gis_pipeline_error():
    """RasterProcessingError must be catchable as GISPipelineError."""
    from gis_pipeline.core.exceptions import GISPipelineError, RasterProcessingError

    assert issubclass(RasterProcessingError, GISPipelineError)


@pytest.mark.unit
def test_configuration_error_is_gis_pipeline_error():
    """ConfigurationError must be catchable as GISPipelineError."""
    from gis_pipeline.core.exceptions import ConfigurationError, GISPipelineError

    assert issubclass(ConfigurationError, GISPipelineError)


@pytest.mark.unit
def test_can_catch_specific_as_base():
    """Raising a specific subclass must be caught by the base class handler."""
    from gis_pipeline.core.exceptions import GISPipelineError, VectorProcessingError

    with pytest.raises(GISPipelineError):
        raise VectorProcessingError("test vector error")


@pytest.mark.unit
def test_exception_preserves_message():
    """All exception classes must preserve their message string."""
    from gis_pipeline.core.exceptions import (
        ConfigurationError,
        GISPipelineError,
        RasterProcessingError,
        VectorProcessingError,
    )

    for cls in (
        GISPipelineError,
        VectorProcessingError,
        RasterProcessingError,
        ConfigurationError,
    ):
        exc = cls("my error message")
        assert "my error message" in str(exc)
