![Python](https://img.shields.io/badge/python-3.11-blue)
![Docker](https://img.shields.io/badge/docker-ready-blue)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-v15.6-blue)

# eoAPI-template
**eoAPI** is an open-source, modular and cloud-native architecture designed to make large-scale Earth Observation data accessible, discoverable and interoperable. It enables quick deployment of a standards API for exploring geospatial raster and vector data, leveraging powerful open-source tools and modern web standards.

**eoAPI** is built from a collection of interoperable services:
- [pgSTAC](https://github.com/stac-utils/pgstac) – PostgreSQL extension for managing and querying STAC metadata.
- [stac-fastapi](https://github.com/stac-utils/stac-fastapi) – A FastAPI-based implementation of the STAC API.
- [TiTiler-pgSTAC](https://github.com/stac-utils/titiler-pgstac) - Tile server to dynamically render Cloud Optimized GeoTIFFs using STAC items.
- [TiPg](https://github.com/developmentseed/tipg) – OGC-compliant vector tile server for PostGIS data.

### Standards & Formats natively supported by **eoAPI**
- [STAC (SpatioTemporel Asset Catalog)](https://stacspec.org/en)
- [COG (Cloud Optimized GeoTIFF)](https://cogeo.org/)
- [OGC API - Tiles](https://www.ogc.org/standards/ogcapi-tiles/)
- [OGC API - Features](https://www.ogc.org/standards/ogcapi-features/)

### Custom features and additions
A new endpoint "/processes" has been added to the API using [pygeoapi](https://pygeoapi.io/). It enables publishing processes via [OGC API - Processes](https://ogcapi.ogc.org/processes/) standard. Processes are algorithms that take inputs, perform calculations, and produce outputs. For example: A terrain analysis process could take a DEM as input and produce a slope map as output. This endpoint uses openapi specifications and is dynamically created with "config/pygeoapi-config.yml' when is built. 

[DuckDB](https://github.com/duckdb/duckdb) has been integrated as a high-performance, in-process SQL analytics engine within the API. DuckDB enables fast querying and transformation of large tabular datasets (such as Parquet or CSV files) directly on disk, without the need for a separate database server. With DuckDB, users can run complex SQL queries, compute spatial operations, and generate new datasets on the fly, all within the local environment and with minimal setup. This integration brings powerful analytics capabilities to the API, complementing the traditional database and cloud-based approaches. With this, a new endpoint "/duckdb" has been added to the API powered by [Flask](https://github.com/pallets/flask) that enable fast and powerful SQL queries on geoparquet data. **NOTE:** DuckDB uses Parquet or GeoParquet files. They are built for vector data, such as GeoJSON. This is not for raster data.

### Requirements
- Docker

# Local Deployment with Docker
Follow these steps to set up the project locally using Docker.

## 1. Set Environment Variables
- Copy env.example and rename it to .env in the project root.
- Update variables as needed.
   *Important*:
      VECTOR_TABLES → add your vector table names (for PostGIS / DuckDB queries)
      RASTER_VOLUME_PATH → set the path to your raster data folder
   Note: The SQL script pg-init/001_create_postgres_role.sql automatically creates the PostgreSQL role used by Docker. You do not need to modify database credentials.

## 2. Add Data Locally (Optional)
### Raster Data (Windows Only)
- Select one or more GeoTIFF images and place them in a local folder.
- Copy the full folder path.
- Convert Windows path to Linux path for Docker:
```bash
cd eoapi-template
scripts/convert_path.sh "A_WINDOWS_PATH"
```
- Copy the output Linux path and paste it into RASTER_VOLUME_PATH in .env.
- Serve the folder via Nginx (Replace MOUNTED_PATH_LINUX with the converted Linux path):
```bash
docker run --rm -it -p 8001:80 -v MOUNTED_PATH_LINUX:/usr/share/nginx/html:ro nginx
```

### Raster Data (Linux and MacOS)
- Select one or more GeoTIFF images and place them in a local folder.
- Copy the full folder path (absolute path, e.g. /home/user/data/raster).
- Set the path in your .env file under RASTER_VOLUME_PATH.
- Serve the folder via Nginx (Replace MOUNTED_PATH_LINUX with the path):
```bash
docker run --rm -it -p 8001:80 -v MOUNTED_PATH_LINUX:/usr/share/nginx/html:ro nginx
```

### Vector Data
- Select vector datasets (Shapefile, GeoJSON, GeoPackage, etc.).
- Create new tables in PostGIS and ensure correct CRS.
- Connect to PostgreSQL using pgAdmin or another tool (server: docker-pgstac).
- Verify that tables exist under the public schema.
- Add table names to VECTOR_TABLES in .env.

### 3. Build and Run Docker
Open new terminal and run: 
```bash
cd eoapi-template
docker compose up --build
```
This will build the images and start the services.

### 4. Run Python pipeline
   Skip this step if no new data has been added.
- Open a terminal and enter the Python environment:
```bash
cd eoapi-template
docker compose exec gdal-python bash
```

- Verify that all pipeline scripts are there :
```bash
cd demo
ls
cd ..
```
Key scripts include:
   [main.py](./demo/main.py)  
   [config.py](./demo/config.py)  
   [util.py](./demo/util.py)  
   [mapping.py](./demo/mapping.py)  
   [logging_setup.py](./demo/logging_setup.py)  
   [init_postgis.py](./demo/init_postgis.py)  
   [duckdb_utils](./demo/duckdb_utils.py)
   [input_data.py](./demo/input_data.py)  
   [processing_stac.py](./demo/processing_stac.py)  
   [geoprocessing_pipeline.py](./demo/geoprocessing_pipeline.py)  

- Run the main script (this may take a few minutes):
```bash
python3 -m demo.main
```
- Verify POST requet reponses:
   status: 200 -> STAC validation and POST requests successful
   Any error -> Check logs for details

### 5. Run processes
Information about running processes in HTTP requests are avaible in the [docs](/docs/api/processes.txt)

### 6. Run DuckDB query
Information about running DuckDB queries in HTTP requests are avaible in the [docs](/docs/api/duckdb.txt)

### 7. Endpoints
| Service          | URL Examples (or check url in Docker) |
| ---------------- | ------------------------------------------------------------------------ |  
| **STAC API**     | `http://localhost:8081` <br> `.../collections/my-collection/items`       |  
| **Raster API**   | `http://localhost:8082` <br> `.../cog/info?url=...COG_NAME.tif`          |  
| **Vector API**   | `http://localhost:8083` <br> `.../collections/public.VECTOR_TABLE/items` |  
| **STAC Browser** | `http://localhost:8085` <br> `/collections/my-collection/items`          |  
| **pygeoapi**     | `http://localhost:5000` <br> `/processes/PROCESS-NAME`                   |  
| **DuckDB**       | `http://localhost:8084` <br> `/QUERY-NAME`                               |  

### 8. Testing
- Open the Python environment inside the Docker container :
```bash
cd eoapi-template
docker compose exec gdal-python bash
```
- Run all tests (API endpoints and geoprocessing pipeline scripts):
```bash
pytest
```
- Run a specific test script: `test_name_of_file.py`
All test scripts are located in the /tests/ folder and start with test_.
Replace test_name_of_file.py with the desired test file:
```bash
pytest tests/test_name_of_file.py
```
