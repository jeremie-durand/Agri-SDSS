# Raster API Endpoint Documentation

This document describes the Raster API endpoint implementation.

## Overview

The Raster API provides access to dynamic raster data through a RESTful interface. All raster data is stored and managed in a local folder.

## Getting Started

### Running the Services

- **Full container stack**: `docker compose up --build`
- **Raster API only**: `docker compose up raster-api --build`

Once running, the Raster API is available at: http://localhost:8082

### Configuration

The Raster API configuration is managed through environment variables and database connection settings defined in the Dockerfile and docker-compose files.

## Demo Collections

The system includes two demo collections for testing and demonstration purposes:

- **sud_du_quebec_4326**: Southern Quebec administrative boundaries in EPSG:4326
- **bdppad_2024_4326_sample_stac**: Sample agricultural parcels data for STAC integration in EPSG:4326

## API Endpoints

### Query Overview

#### Get COG (Cloud-Optimized GeoTIFFs) metadata
```http
GET /cog/info?url={absolutePath}
```
Returns metadata of COG file

Example:
```bash
curl http://localhost:8082/cog/info?url=file:///data/DEMO.tif
```
Response: Metadata of DEMO.tif COG file


#### Get COG demo viewer
```http
GET /cog/viewer?url={absolutePath}
```
Example:
```In Browser
http://localhost:8082/cog/viewer?url=file:///data/corg_fr_siigsol_cog.tif
```
Response: Web viewer of COG

#### Get dynamic tiles
```http
GET /cog/tiles/{tileMatrixSetId}/{z}/{x}/{y}[@{scale}x][.{format}]?url={absolutePath}
```

Example:
```XYZ Tiles
curl http://localhost:8082/cog/tiles/WebMercatorQuad/{z}/{x}/{y}.png?url=file:///data/corg_fr_siigsol_cog.tif&bidx=1
```

## Data Storage
PostGIS Integration
Raster data is stored locally and their metadata is stored in PostGIS tables following STAC compliance.

## Standards Compliance
OGC API - Tiles
This implementation follows the OGC API - Tiles specification, providing:
- RESTful API design for raster tile services
- Standard tile matrix sets (WebMercatorQuad, WorldCRS84Quad)
- Multiple output formats (PNG, JPEG, WebP)
- Dynamic tile generation from COG files
- Metadata endpoints for raster information

Coordinate Reference Systems
- Default Tile Matrix Set: WebMercatorQuad (EPSG:3857)

Cloud Optimized GeoTIFF (COG)
- All raster data must be in COG format for optimal performance
- Supports multi-band rasters with band selection via `bidx` parameter
- Internal overviews and tiling for efficient tile generation

# Development Notes
- Overviews are automatically generated during COG creation process
- Tiles are generated on-demand with internal caching
- Use appropriate compression (DEFLATE, LZW) for file size optimization
