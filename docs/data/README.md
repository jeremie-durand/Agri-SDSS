# Data Integration Documentation

Scope: This page is a navigational index and how-to guide. For authoritative, up-to-date details about integrated datasets (formats, CRS, status, links), see the catalog in [CATALOG.md](CATALOG.md).

## Data Catalog/Sources

See [CATALOG.md](CATALOG.md) for the single source of truth about integrated data sources, including:
- Data type (raster, vector, tabular)
- CRS and file formats
- Update frequency
- Integration status
- Access details

## Integration Examples

Templates and real examples from the project:

- [PostGIS Schema](examples/postgis_schema.md) - Standard table structure and geometry types
- [STAC Metadata](examples/stac_metadata.md) - Metadata template and examples

## Implementation Guides

Step-by-step guides for common tasks:

- [Adding New Data Sources](guides/adding_new_data.md) - Complete workflow for data ingestion
- [CRS Management & Transformation](guides/crs_management.md) - Best practices for coordinate systems
