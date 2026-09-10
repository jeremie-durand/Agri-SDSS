class GISPipelineError(Exception):
    """Base exception for all GIS pipeline errors."""


class VectorProcessingError(GISPipelineError):
    """Raised when vector data processing fails."""


class RasterProcessingError(GISPipelineError):
    """Raised when raster data processing fails."""


class ConfigurationError(GISPipelineError):
    """Raised when the pipeline configuration is invalid or missing."""
