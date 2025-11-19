![License](https://img.shields.io/badge/license-TBD-lightgrey)
![Project Status](https://img.shields.io/badge/status-en%20développement-yellow)
![Platform](https://img.shields.io/badge/platform-linux--windows-lightgrey)
![Python](https://img.shields.io/badge/python-3.11-blue)
![Docker](https://img.shields.io/badge/docker-ready-blue)
![PostgreSQL](https://img.shields.io/badge/postgresql-blue)

# Geospatial Data API (mos-gis)
A geospatial data API centralizes access to GIS data from multiple sources and formats, providing a standardized interface. It allows users to query, filter and retrieve data efficiently without handling raw data or performing preprocessing steps. By exposing data through an API, it enables automation, interoperbility and ease of integration with frontend tools. This approach ensures that new spatial data can be added seamlessly, processed consistently and made available to downstream applications in a reproductible and scalable manner.

A geoprocessing pipeline has been developed to automate the extraction, preprocessing, ingestion and diffusion of GIS data from various sources and formats. This pipeline supports the addition of new data by automating the processing steps tailored to each data type. The data are published in a custom API based on [eoAPI](https://github.com/developmentseed/eoAPI), an open-source, modular and cloud-native architecture designed to make large-scale Earth Observation data accessible, discoverable and interoperable. It enables quick deployment of a standards API for exploring geospatial raster and vector data, leveraging powerful open-source tools and modern web standards.

**eoAPI** is built from a collection of interoperable services:
- [pgSTAC](https://github.com/stac-utils/pgstac) -> PostgreSQL extension for managing and querying STAC metadata.
- [stac-fastapi](https://github.com/stac-utils/stac-fastapi) -> A FastAPI-based implementation of the STAC API.
- [TiTiler-pgSTAC](https://github.com/stac-utils/titiler-pgstac) -> Tile server to dynamically render Cloud Optimized GeoTIFFs using STAC items.
- [TiPg](https://github.com/developmentseed/tipg) -> OGC-compliant vector tile server for PostGIS data.

On the frontend, it uses [STAC Browser](https://github.com/radiantearth/stac-browser), which connects to the API for some simple UI components.

This project is part of a larger research project and forms the basis of the backend for the platform described [here](https://rqrad.com/projet/developpement-dun-systeme-daide-a-la-decision-pour-determiner-le-potentiel-daccumulation-de-matiere-organique-du-sol-au-quebec-et-les-pratiques-pour-latteindre/).
This backend includes the plateform architecture, a geoprocessing pipeline and a geospatial API.

Currently, only the local version is availaible.

## Geospatials Standards & Formats natively supported by eoAPI
- [STAC (SpatioTemporel Asset Catalog)](https://stacspec.org/en)
- [COG (Cloud Optimized GeoTIFF)](https://cogeo.org/)
- [OGC API - Tiles](https://www.ogc.org/standards/ogcapi-tiles/)
- [OGC API - Features](https://www.ogc.org/standards/ogcapi-features/)

## Custom features and additions
A new endpoint "/processes" has been added to the API using [pygeoapi](https://pygeoapi.io/). It enables publishing processes via [OGC API - Processes](https://ogcapi.ogc.org/processes/) standard. Processes are algorithms that take inputs, perform calculations, and produce outputs. For example: A terrain analysis process could take a DEM as input and produce a slope map as output. This endpoint uses openapi specifications and is dynamically created when it is built. 

[DuckDB](https://github.com/duckdb/duckdb) has been integrated as a high-performance, in-process SQL analytics engine within the API. DuckDB enables fast querying and transformation of large tabular datasets (such as Parquet or CSV files) directly on disk, without the need for a separate database server. With DuckDB, users can run complex SQL queries, compute spatial operations, and generate new datasets on the fly, all within the local environment and with minimal setup. This integration brings powerful analytics capabilities to the API, complementing the traditional database and cloud-based approaches.

**NOTE:** DuckDB uses Parquet or GeoParquet files. They are built for vector data, such as GeoJSON. This is not for raster data.

## Planned Features / Future Work
**Improvements in pipeline vector data:**
   - Add support for points and lines
   - Refacto logic
   - Update unit testing

**Improvements in pipeline raster data:**
   - Improve raster harmonization and processing
   - Refacto logic
   - Update unit testing
   - Debug GDAL cog overviews creation

**Improvements in pipeline STAC processing:**
   - Refacto logic
   - Update unit testing

**New features in pipeline:**
- Earth Observation data integration
- Add specific usage processes that uses OGC API Processes

**New features in API:**
- Documention for API using tools like Swagger UI
- Proxy services integration for legacy OGC standards

**Frontend:**
- VEDA UI integration

# Requirements
- Docker

**NOTE:** Dependencies for each service are automaticaly installed in independent containers.

# Local Deployment with Docker
Follow these steps to set up the project locally using Docker.

## 1. Set Environment Variables
Copy **env.example** and rename it to **.env** in the project root.

Public variables for the pipeline are located in **stac-fastapi/config.yaml** file. These are the ones that can be modified.

**NOTE:** The script **scripts/001_create_postgres_role.sql** automatically creates the PostgreSQL role used by Docker. You do not need to modify database credentials.

## 2. Build and Run Docker
Open a new terminal and run: 
```bash
docker compose up --build
```
This will build the images and start the services.

## 3. Add Data Locally
- Select data (they can be rasters, vectors or both).
- Place them in the repo **/data/input/**. If **INPUT_DATA_PATH** has been modified, placed them in the corresponding path instead.

**NOTE:** Data can be placed in nested folder within the repo, for exemple **/data/input/rasters** or /**data/input/vectors**.

## 4. Python Pipeline
### About
This pipeline automates the extraction, preprocessing, ingestion and publication of GIS data into the Geospatial Data API. It is designed to handle multiple data types and formats, applying the necessary transformations and metadata enrihment automatically. Running the pipeline ensures that new dataset are processed consistently and made avaible in the API. This automation reduces manual work, enforces reproductibility and enables inegration with frontend tools.

### Running the Pipeline
1. Open a new terminal and run:
```bash
docker compose exec stac-fastapi python3 pipeline/main.py
```

The pipeline accepts several arguments for customization. \
You can override default settings using command-line arguments. \
See the full, automatically generated [ARGS.md](stac-fastapi/pipeline/docs/ARGS.md) for details, including `--help` output.

To generate a new ARGS.md (for updated arguments), run:
```bash
docker compose exec stac-fastapi python3 pipeline/docs/generate_args_md.py
```

**NOTE:** If not provided, the default arguments from stac-fastapi/config.yaml will be used.

## 5. Run processes
Information about running processes in HTTP requests are avaible in the [docs](/pygeoapi/docs/processes_endpoint.md)

## 6. Endpoints
The API exposes several services.  
See the automatically generated [ENDPOINTS.md](stac-fastapi/pipeline/docs/ENDPOINTS.md) for full URLs and example paths.

To generate a new ENDPOINTS.md (for updated API urls), run:
```bash
docker compose exec stac-fastapi python3 pipeline/docs/generate_endpoints_md.py
```

More information in the [docs](docs/api_services.md)

## 7. Testing
- Open a new terminal and run:
```bash
docker compose exec stac-fastapi pytest
```
- To run a specific test script :
```bash
pytest
```
- Run a specific test script: `test_name_of_file.py`
All test scripts are located in the /tests/ folder and start with test_.
Replace test_name_of_file.py with the desired test file:
```bash
pytest pytest test/directory/test_name_of_file.py
```
**NOTE:** Replace **test_name_of_file.py** with the desired test file.
