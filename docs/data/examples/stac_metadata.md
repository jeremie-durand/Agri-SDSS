# STAC Metadata Examples

Practical STAC Item and Collection templates for agri-sdss data.

## STAC Item - Vector Features

A STAC Item describes a single asset or feature collection:

```json
{
  "type": "Feature",
  "stac_version": "1.0.0",
  "stac_extensions": [
    "https://stac-extensions.github.io/projection/v1.0.0/schema.json",
    "https://stac-extensions.github.io/item-assets/v1.0.0/schema.json"
  ],
  "id": "grhq-watercourses-2024",
  "geometry": {
    "type": "Polygon",
    "coordinates": [[
      [-79.75, 41.75],
      [-79.75, 51.75],
      [-56.0, 51.75],
      [-56.0, 41.75],
      [-79.75, 41.75]
    ]]
  },
  "bbox": [-79.75, 41.75, -56.0, 51.75],
  "properties": {
    "datetime": "2024-01-15T00:00:00Z",
    "title": "GRHQ Watercourses - Quebec",
    "description": "Hydrographic network vector dataset containing watercourses (streams, rivers) for the province of Quebec",
    "platform": "government",
    "data_type": "vector",
    "proj:epsg": 4326,
    "dataset:source": "GRHQ",
    "dataset:version": "2.0",
    "dataset:license": "OGL-Q",
    "dataset:publisher": "MELCCFP",
    "vector:geometry_types": ["LineString", "MultiLineString"]
  },
  "assets": {
    "geopackage": {
      "href": "s3://agri-sdss-data/grhq/grhq_watercourses.gpkg",
      "type": "application/geopackage+sqlite3",
      "roles": ["data"],
      "title": "GRHQ Watercourses (GeoPackage)",
      "description": "Complete hydrographic network in GeoPackage format"
    },
    "geojson": {
      "href": "https://api.example.com/collections/grhq-watercourses/items.geojson",
      "type": "application/geo+json",
      "roles": ["data"],
      "title": "GRHQ Watercourses (GeoJSON)",
      "description": "Features accessible via vector API"
    },
    "metadata": {
      "href": "s3://agri-sdss-data/grhq/grhq_metadata.xml",
      "type": "application/xml",
      "roles": ["metadata"],
      "title": "ISO 19115 Metadata"
    }
  },
  "links": [
    {
      "rel": "parent",
      "href": "../catalog.json",
      "type": "application/json"
    },
    {
      "rel": "collection",
      "href": "../grhq-collection/collection.json",
      "type": "application/json"
    },
    {
      "rel": "derived_from",
      "href": "https://www.donneesquebec.ca/recherche/dataset/grhq",
      "title": "Original source on Données Québec"
    },
    {
      "rel": "alternate",
      "href": "http://localhost:8081/collections/grhq-watercourses/items/grhq-watercourses-2024",
      "type": "application/json",
      "title": "Item in STAC API"
    }
  ]
}
```

## STAC Item - Raster Data

Example for SIIGSOL gridded soil properties:

```json
{
  "type": "Feature",
  "stac_version": "1.0.0",
  "stac_extensions": [
    "https://stac-extensions.github.io/projection/v1.0.0/schema.json",
    "https://stac-extensions.github.io/raster/v1.1.0/schema.json",
    "https://stac-extensions.github.io/eo/v1.0.0/schema.json"
  ],
  "id": "siigsol-soil-properties-2024",
  "geometry": {
    "type": "Polygon",
    "coordinates": [[
      [-79.75, 41.75],
      [-79.75, 51.75],
      [-56.0, 51.75],
      [-56.0, 41.75],
      [-79.75, 41.75]
    ]]
  },
  "bbox": [-79.75, 41.75, -56.0, 51.75],
  "properties": {
    "datetime": "2024-01-01T00:00:00Z",
    "start_datetime": "2024-01-01T00:00:00Z",
    "end_datetime": "2024-12-31T23:59:59Z",
    "title": "SIIGSOL - Soil Properties Grid 100m",
    "description": "Multi-band raster of Quebec soil properties at 100m resolution: clay, silt, sand, organic matter, pH, CEC",
    "platform": "government",
    "instruments": ["remote-sensing", "soil-survey"],
    "data_type": "raster",
    "proj:epsg": 4326,
    "proj:shape": [1200, 1500],
    "proj:transform": [0.0009, 0, -79.75, 0, -0.0009, 51.75],
    "dataset:source": "SIIGSOL-100m",
    "dataset:version": "2.1",
    "dataset:license": "OGL-Q",
    "dataset:publisher": "MAPAQ",
    "dataset:pixel_size": 100
  },
  "assets": {
    "clay": {
      "href": "s3://agri-sdss-data/siigsol/siigsol_clay.cog.tif",
      "type": "image/tiff; application=geotiff; profile=cloud-optimized",
      "roles": ["data"],
      "title": "Clay Content (Band 1)",
      "description": "Percentage of clay particles (<2µm)",
      "raster:bands": [
        {
          "nodata": -9999,
          "data_type": "float32",
          "unit": "percent",
          "spatial_resolution": 100,
          "statistics": {
            "mean": 22.5,
            "minimum": 0,
            "maximum": 100,
            "stddev": 15.2
          }
        }
      ]
    },
    "organic_matter": {
      "href": "s3://agri-sdss-data/siigsol/siigsol_organic_matter.cog.tif",
      "type": "image/tiff; application=geotiff; profile=cloud-optimized",
      "roles": ["data"],
      "title": "Organic Matter / Carbon (Band 4)",
      "description": "Percentage of soil organic carbon (C_org)",
      "raster:bands": [
        {
          "nodata": -9999,
          "data_type": "float32",
          "unit": "percent",
          "spatial_resolution": 100,
          "statistics": {
            "mean": 3.2,
            "minimum": 0.1,
            "maximum": 15.0,
            "stddev": 2.8
          }
        }
      ]
    },
    "ph": {
      "href": "s3://agri-sdss-data/siigsol/siigsol_ph.cog.tif",
      "type": "image/tiff; application=geotiff; profile=cloud-optimized",
      "roles": ["data"],
      "title": "Soil pH (Band 5)",
      "description": "Soil pH value (0-14, 7=neutral)",
      "raster:bands": [
        {
          "nodata": -9999,
          "data_type": "float32",
          "unit": "pH",
          "spatial_resolution": 100,
          "statistics": {
            "mean": 6.8,
            "minimum": 4.2,
            "maximum": 8.1,
            "stddev": 0.9
          }
        }
      ]
    },
    "cec": {
      "href": "s3://agri-sdss-data/siigsol/siigsol_cec.cog.tif",
      "type": "image/tiff; application=geotiff; profile=cloud-optimized",
      "roles": ["data"],
      "title": "Cation Exchange Capacity (Band 6)",
      "description": "CEC - soil nutrient holding capacity (cmol/kg)",
      "raster:bands": [
        {
          "nodata": -9999,
          "data_type": "float32",
          "unit": "cmol/kg",
          "spatial_resolution": 100,
          "statistics": {
            "mean": 12.5,
            "minimum": 2.0,
            "maximum": 45.0,
            "stddev": 8.3
          }
        }
      ]
    },
    "combined": {
      "href": "s3://agri-sdss-data/siigsol/siigsol_all_bands.cog.tif",
      "type": "image/tiff; application=geotiff; profile=cloud-optimized",
      "roles": ["data"],
      "title": "All Soil Properties (6-band composite)",
      "description": "All soil properties in single multi-band GeoTIFF"
    },
    "thumbnail": {
      "href": "s3://agri-sdss-data/siigsol/siigsol_preview.jpg",
      "type": "image/jpeg",
      "roles": ["thumbnail"],
      "title": "Thumbnail preview"
    }
  },
  "links": [
    {
      "rel": "parent",
      "href": "../catalog.json",
      "type": "application/json"
    },
    {
      "rel": "collection",
      "href": "../siigsol-collection/collection.json",
      "type": "application/json"
    },
    {
      "rel": "derived_from",
      "href": "https://www.donneesquebec.ca/recherche/dataset/siigsol-100m-carte-des-proprietes-du-sol",
      "title": "Original data source"
    },
    {
      "rel": "alternate",
      "href": "http://localhost:1/collections/siigsol/items/siigsol-soil-properties-2024",
      "type": "application/json",
      "title": "Item in STAC API"
    }
  ]
}
```

## STAC Item - Time-Series Data

Example for hydrometric station measurements:

```json
{
  "type": "Feature",
  "stac_version": "1.0.0",
  "stac_extensions": [
    "https://stac-extensions.github.io/projection/v1.0.0/schema.json",
    "https://stac-extensions.github.io/timeseries/v1.1.0/schema.json"
  ],
  "id": "hydrometrique-discharge-2024-01",
  "geometry": {
    "type": "Point",
    "coordinates": [-72.583, 47.254]
  },
  "bbox": [-72.583, 47.254, -72.583, 47.254],
  "properties": {
    "datetime": null,
    "start_datetime": "2024-01-01T00:00:00Z",
    "end_datetime": "2024-01-31T23:59:59Z",
    "title": "Hydrometrique Station Discharge - January 2024",
    "description": "Hourly water discharge measurements from hydrometric station 05010100 (Saint-Lawrence River)",
    "platform": "government",
    "instruments": ["water-level-gauge"],
    "data_type": "tabular",
    "dataset:source": "HYDROMETRIQUE",
    "dataset:station_id": "05010100",
    "dataset:station_name": "Saint-Lawrence River at Cardinal",
    "dataset:update_frequency": "hourly",
    "timeseries:interval": "PT1H",
    "proj:epsg": 4326
  },
  "assets": {
    "csv": {
      "href": "s3://agri-sdss-data/hydrometrique/2024-01/station-05010100.csv",
      "type": "text/csv",
      "roles": ["data"],
      "title": "Discharge Data (CSV)",
      "description": "Hourly discharge measurements in CSV format"
    },
    "parquet": {
      "href": "s3://agri-sdss-data/hydrometrique/2024-01/station-05010100.parquet",
      "type": "application/parquet",
      "roles": ["data"],
      "title": "Discharge Data (Parquet)",
      "description": "Optimized columnar format for analytics"
    },
    "geojson": {
      "href": "https://api.example.com/collections/hydrometrique/items.geojson",
      "type": "application/geo+json",
      "roles": ["data"],
      "title": "Point features accessible via Vector API"
    }
  },
  "links": [
    {
      "rel": "parent",
      "href": "../catalog.json",
      "type": "application/json"
    },
    {
      "rel": "collection",
      "href": "../hydrometrique-collection/collection.json",
      "type": "application/json"
    },
    {
      "rel": "prev",
      "href": "hydrometrique-discharge-2023-12-01.json",
      "type": "application/json",
      "title": "Previous month"
    },
    {
      "rel": "next",
      "href": "hydrometrique-discharge-2024-02-01.json",
      "type": "application/json",
      "title": "Next month"
    },
    {
      "rel": "derived_from",
      "href": "https://www.donneesquebec.ca/recherche/dataset/stations-hydrometriques",
      "title": "Original data source"
    }
  ]
}
```

## STAC Collection

A Collection groups related Items:

```json
{
  "stac_version": "1.0.0",
  "stac_extensions": [
    "https://stac-extensions.github.io/projection/v1.0.0/schema.json",
    "https://stac-extensions.github.io/raster/v1.1.0/schema.json"
  ],
  "type": "Collection",
  "id": "siigsol",
  "description": "Quebec soil properties grid at 100m resolution including clay, silt, sand, organic matter, pH, and cation exchange capacity",
  "links": [
    {
      "rel": "root",
      "href": "../../catalog.json",
      "type": "application/json"
    },
    {
      "rel": "parent",
      "href": "../catalog.json",
      "type": "application/json"
    },
    {
      "rel": "item",
      "href": "./siigsol-soil-properties-2024/siigsol-soil-properties-2024.json",
      "type": "application/json"
    },
    {
      "rel": "alternate",
      "href": "http://localhost:8081/collections/siigsol",
      "type": "application/json",
      "title": "Collection in STAC API"
    },
    {
      "rel": "license",
      "href": "https://www.donneesquebec.ca/documents/licence/",
      "title": "Open Government License - Quebec"
    }
  ],
  "extent": {
    "spatial": {
      "bbox": [
        [-79.75, 41.75, -56.0, 51.75]
      ]
    },
    "temporal": {
      "interval": [
        ["2024-01-01T00:00:00Z", "2024-12-31T23:59:59Z"]
      ]
    }
  },
  "license": "OGL-Q",
  "keywords": [
    "soil",
    "properties",
    "grid",
    "100m",
    "quebec",
    "siigsol",
    "clay",
    "organic-matter",
    "ph"
  ],
  "providers": [
    {
      "name": "MAPAQ",
      "description": "Ministère de l'Agriculture, des Pêcheries et de l'Alimentation du Québec",
      "roles": ["producer", "host"],
      "url": "https://www.agriculture.gouv.qc.ca/"
    },
    {
      "name": "agri-sdss",
      "description": "Geospatial Data Platform",
      "roles": ["processor", "host"],
      "url": "https://github.com/jeremie-durand/Agri-SDSS"
    }
  ],
  "summaries": {
    "raster:bands": [
      {
        "name": "clay",
        "title": "Clay Content",
        "unit": "percent",
        "type": "float32"
      },
      {
        "name": "organic_matter",
        "title": "Organic Matter / Carbon",
        "unit": "percent",
        "type": "float32"
      },
      {
        "name": "ph",
        "title": "Soil pH",
        "unit": "pH",
        "type": "float32"
      }
    ],
    "proj:epsg": [4326]
  },
  "assets": {
    "thumbnail": {
      "href": "https://example.org/siigsol-preview.jpg",
      "type": "image/jpeg",
      "title": "Collection preview"
    }
  }
}
```

## Important STAC Concepts

### Geometry vs Bbox

- **geometry**: Actual data footprint (can be irregular polygon)
- **bbox**: Bounding rectangle [minLon, minLat, maxLon, maxLat]

### Datetime Handling

- **Single observation**: Use `"datetime": "2024-01-15T00:00:00Z"`
- **Time-series/range**: Use `"datetime": null` with `"start_datetime"` and `"end_datetime"`

### Link Relationships

| rel | Purpose |
|-----|---------|
| `parent` | Points to parent catalog |
| `collection` | Points to containing collection |
| `item` | Points to items (for collections) |
| `child` | Points to child catalogs |
| `alternate` | Alternative representation (e.g., HTML version) |
| `derived_from` | Source of data |
| `license` | License document |

### Roles in Assets

| Role | Purpose |
|------|---------|
| `data` | Primary data file |
| `metadata` | Metadata document |
| `thumbnail` | Small preview image |
| `visual` | Full-resolution preview |
| `overview` | Reduced resolution for quick access |

## References

- [STAC Specification](https://stacspec.org/)
- [STAC API Specification](https://github.com/radiantearth/stac-api-spec)
- [stactools Documentation](https://stactools.readthedocs.io/)
- [PySTAC Library](https://pystac.readthedocs.io/)
