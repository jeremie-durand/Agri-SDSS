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

## Requirements
- Docker

## Follow this steps for local deployment on Docker

### 1. Set environment variables
- Copy env.example and rename it `.env`, keep it at the same root.
- Set the variables as needed
- Note: The script `pg-init/001_create_postgres_role.sql` automatically creates a PostgreSQL role used by Docker, so no need to modify database credentials.

### 2. Adding data locally (Optional)
Before anything, you need to uncomment the variables *VECTOR_TABLES*, *RASTER_URL_PREFIX*, *RASTER_WINDOWS_PATH*, *RASTER_VOLUME_PATH* and *RASTER_PATH* in the `.env` file.
Then, uncomment lines 116, 127, 128, and 129 in the `docker-compose.yml` file.

**Raster data**
- Choose one or more GeoTIFF images
- Place them in a local directory and copy the full path in RASTER_WINDOWS_PATH in `.env`
- Open a new Terminal and run this cmd using the same Windows path (change *A_WINDOWS_PATH*):
```sh
cd eoapi-template
scripts//convert_path.sh "A_WINDOWS_PATH"
```
It will give you the mounted path that Linux (Docker) uses for the windows path, copy and past into *RASTER_VOLUME_PATH* in .env

- Serve the folder via nginx (change *MOUNTED_PATH_LINUX*):
```sh
docker run --rm -it -p 8001:80 -v MOUNTED_PATH_LINUX:/usr/share/nginx/html:ro nginx
```

**Vector data**
- Choose one or more vector dataset (Shapefile, GeoJSON, GeoPackage, etc.)
- Create new tables in the PostGIS database and ensure correct SRID (easy with PostGIS Bundle using `.env` credentials)
- Connect via pgAdmin or other PostgreSQL tool (server: docker-pgstac)
- Verify new tables exist under public schema
- Add the table names to the *VECTOR_TABLES* variable in `.env`

### 3. Build and Run Docker
Open new terminal and run: 
```sh
cd eoapi-template
docker compose up --build
```

### 4. Run Python pipeline
**This step runs the geoprocessing pipeline. If no new data has been added, you can skip it.**
- Open Python environment in a new terminal :
```sh
cd eoapi-template
docker compose exec gdal-python sh
```

- Verify that all scripts are there :
```sh
ls
```
   [main.py](./test/main.py)
   [config.py](./test/config.py)
   [mapping.py](./test/mapping.py)
   [logging_setup.py](./test/logging_setup.py)
   [init_postgis.py](./test/init_postgis.py)
   [processing_stac.py](./test/processing_stac.py)
   [geoprocessing_pipeline.py](./test/geoprocessing_pipeline.py)

- Run script : (this may take a few minutes)
```sh
python3 main.py
```

- Check POST requests responses :
   status: 200 -> STAC validation and POST requests successful
   Any error -> Check logs

### 5. Endpoints
| Service          | URL Examples (or check url in Docker) |
| ---------------- | ------------------------------------------------------------------------ |
| **STAC API**     | `http://localhost:8081` <br> `.../collections/my-collection/items`       |
| **Raster API**   | `http://localhost:8082` <br> `.../cog/info?url=...COG_NAME.tif`          |
| **Vector API**   | `http://localhost:8083` <br> `.../collections/public.VECTOR_TABLE/items` |
| **STAC Browser** | `http://localhost:8085` <br> `/collections/my-collection/items`          |

## Notes
This is a minimal demo and is not production-ready.

Future versions will include: better validation, better testing, improved automation logic, supports of other data types like web services, etc.