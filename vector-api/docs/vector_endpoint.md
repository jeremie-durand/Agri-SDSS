# Vector API Endpoint Documentation

This document describes the Vector API endpoint implementation, following the OGC API - Features standard for serving vector geospatial data stored in PostGIS.

## Overview

The Vector API provides access to vector geospatial data through a RESTful interface, implementing the OGC API - Features specification. All vector data is stored and managed in PostGIS database.

## Getting Started

### Running the Services

- **Full container stack**: `docker compose up --build`
- **Vector API only**: `docker compose up vector-api --build`

Once running, the Vector API is reached through the deployment's public origin at
`https://<host>/vector-api/` — port 8083 is container-internal (`expose:`) and is not
published to the host. Collections live under a backend prefix: `postgis/` for PostGIS
tables and `parquet/` for GeoParquet. Against a local deployment add `-k`
(`curl -k https://localhost/...`) because the certificate is self-signed.

### Configuration

The Vector API configuration is managed through environment variables and database connection settings defined in the Dockerfile and docker-compose configuration.

## Demo Collections

The system includes two demo collections for testing and demonstration purposes:

- **sites_maricoles_2024_12**: Quebec mariculture permit sites — 38 polygons in EPSG:4326
- **bdppad_demo_an_2025**: BDPPAD agricultural parcel demo extract — 14 556 polygons in EPSG:4326

## API Endpoints

### Query Overview

#### Get All Collections

```http
GET /collections
```

Returns a list of all available vector collections.

Example:

```bash
curl -k https://localhost/vector-api/postgis/collections
```

Response: List of collections

#### Get Collection Information

```http
GET /collections/{collectionId}
```

Returns detailed information about a specific collection.

Parameters:
collectionId (string): The identifier of the collection

Examples:

```bash
# Get mariculture sites collection info
curl -k https://localhost/vector-api/postgis/collections/public.sites_maricoles_2024_12

# Get agricultural parcels collection info
curl -k https://localhost/vector-api/postgis/collections/public.bdppad_demo_an_2025
```

Response (illustrative sample captured from an earlier dataset; ids and link hrefs
shown are not the current ones):

```json
{"id":"public.sud_du_quebec_4326","title":"public.sud_du_quebec_4326","links":[{"href":"http://localhost:8083/collections/public.sud_du_quebec_4326","rel":"self","type":"application/json"},{"href":"http://localhost:8083/collections/public.sud_du_quebec_4326/items","rel":"items","type":"application/geo+json","title":"Items"},{"href":"http://localhost:8083/collections/public.sud_du_quebec_4326/items?f=csv","rel":"alternate","type":"text/csv","title":"Items (CSV)"},{"href":"http://localhost:8083/collections/public.sud_du_quebec_4326/items?f=geojsonseq","rel":"alternate","type":"application/geo+json-seq","title":"Items (GeoJSONSeq)"},{"href":"http://localhost:8083/collections/public.sud_du_quebec_4326/queryables","rel":"queryables","type":"application/schema+json","title":"Queryables"}],"extent":{"spatial":{"bbox":[[-74.66980081171282,44.99135832579372,-69.62529737300314,47.4119438131845]],"crs":"http://www.opengis.net/def/crs/OGC/1.3/CRS84"},"temporal":{"interval":[["2024-01-01T00:00:00+00:00","2024-12-31T00:00:00+00:00"],["2024-12-31T00:00:00+00:00","2024-12-31T00:00:00+00:00"],["2024-01-01T00:00:00+00:00","2024-01-01T00:00:00+00:00"]],"trs":"http://www.opengis.net/def/uom/ISO-8601/0/Gregorian"}},"itemType":"feature","crs":["http://www.opengis.net/def/crs/OGC/1.3/CRS84"]}
```

#### Get All Features from Collection

```http
GET /collections/{collectionId}/items
```

Returns all features from the specified collection.

Parameters:
collectionId (string): The identifier of the collection

Query Parameters:
limit (integer): Maximum number of features to return (default: 10)
offset (integer): Number of features to skip
bbox (array): Bounding box filter [minx,miny,maxx,maxy]

Examples:

```bash
# Get mariculture sites with spatial filter
curl -k "https://localhost/vector-api/postgis/collections/public.sites_maricoles_2024_12/items?limit=5&bbox=-70,47,-57,52"

# Get agricultural parcels with pagination
curl -k "https://localhost/vector-api/postgis/collections/public.bdppad_demo_an_2025/items?limit=10&offset=20"
```

Response: GeoJSON FeatureCollection

#### Get Specific Feature

```http
GET /collections/{collectionId}/items/{featureId}
```

Returns a specific feature by its identifier.

Parameters:
collectionId (string): The identifier of the collection
featureId (string): The identifier of the feature

```bash
# Get specific mariculture site
curl -k https://localhost/vector-api/postgis/collections/public.sites_maricoles_2024_12/items/1

# Get specific agricultural parcel
curl -k https://localhost/vector-api/postgis/collections/public.bdppad_demo_an_2025/items/1
```

Response (illustrative sample from an earlier dataset):

```json
{
  "type": "Feature",
  "id": "region-x",
  "geometry": {
    "type": "Polygon",
    "coordinates": [[
      [-73.123, 45.456],
      [-73.124, 45.457],
      [-73.125, 45.456],
      [-73.123, 45.456]
    ]]
  },
  "properties": {
    "name": "Montérégie",
    "region_code": "16",
    "area_km2": 11111.5,
    "population": 1534000
  }
}
```

## Data Storage

PostGIS Integration
Vector data is stored in PostGIS tables with the following requirements:

- Geometry Column: Must be properly indexed for spatial queries
- Primary Key: Required for feature identification
- SRID: Spatial reference system identifier must be set (4326 for demo collections)

## Standards Compliance

OGC API - Features
This implementation follows the OGC API - Features specification, providing:

- RESTful API design
- JSON and GeoJSON responses
- Standard query parameters
- Pagination support
- Spatial filtering capabilities

Coordinate Reference Systems

- Default CRS: WGS84 (EPSG:4326)
- Demo Collections CRS: All demo collections use EPSG:4326

## Development Notes

- All responses follow GeoJSON specification for spatial data
- Spatial indexes are automatically used for bbox queries
- Feature properties are dynamically generated from PostGIS table columns
- Demo collections are automatically loaded from the DEMO_VECTOR_TABLES environment variable
