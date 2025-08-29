![License](https://img.shields.io/badge/license-TBD-lightgrey)
![Project Status](https://img.shields.io/badge/status-en%20développement-yellow)
![Platform](https://img.shields.io/badge/platform-linux--windows-lightgrey)
![Python](https://img.shields.io/badge/python-3.11-blue)
![Docker](https://img.shields.io/badge/docker-ready-blue)
![PostgreSQL](https://img.shields.io/badge/postgresql-blue)

# mos-gis
A geoprocessing pipeline is being developed to automate the extraction, preprocessing, ingestion and diffusion of GIS data from various sources and formats. This pipeline supports the addition of new data by automating the processes steps tailored to each data type. The data are being publish in a custom API based on [eoAPI](https://github.com/developmentseed/eoAPI). 

This version is an initial proof-of-concept that aims to demonstrate the tools and services involved. Some logic and key features are still missing and will be added in future iterations. On the frontend, it uses [eoAPI-template](https://github.com/developmentseed/eoapi-template) and [STAC Browser](https://github.com/radiantearth/stac-browser) for UI components.

This project is part of a larger research project and forms the basis of the backend for the platform described here: https://rqrad.com/projet/developpement-dun-systeme-daide-a-la-decision-pour-determiner-le-potentiel-daccumulation-de-matiere-organique-du-sol-au-quebec-et-les-pratiques-pour-latteindre/
This backend includes the plateform architecture, a geoprocessing pipeline and a geospatial API.

Currently, only the local version is availaible.

## Subsections
- [local deployment of API](./eoapi-template/README.md)  
- [Docs for geoprocessing pipeline, architecture and API](./docs/)  

## Tools used in API
| Tool            | Purpose                                                     |
|-----------------|-------------------------------------------------------------|
| **eoAPI**       | Backend framework exposing STAC-compliant metadata services |
| **Docker**      | Containerization for local deployment                       |
| **PostgreSQL + PostGIS** | Spatial database to store and query vector data   |
| **pgSTAC**      | PostgreSQL schema for STAC compliance                       |
| **STAC Browser**| UI frontend to navigate and inspect STAC metadata           |
| **TiTiler**     | Lightweight dynamic tile server to serve Cloud-Optimized GeoTIFFs (COGs)|
| **TiPg**        | Tile server for serving vector tiles directly from PostgreSQL/PostGIS   |
| **FastAPI**     | Web framework used to build performant, standards-based API endpoints   |
| **GDAL**        | Geospatial Data Abstraction Library used for data conversion, reprojection, and preprocessing |
| **uvicorn**     | ASGI server used to run FastAPI apps  |
| **Python 3.11** | Primary scripting language for building and running the processing pipeline      |
| **nginx**       | Lightweight HTTP server used to serve local raster files in the demo      |
| **pygeoapi**    | Python server implementation for OGC API standards      |
| **openAPI**     | Specifications that provide a formal standard for HTTP APIs     |
| **DuckDB**      | In-process SQL database optimized for fast analytics on large files (Parquet, CSV, etc.)   |  

## Contribution
| Name | Role |
|------|------|
| Jérémie Durand    | Developer |
| Rami Albasha    | Reviewer / Supervisor |
| Mickaël Germain    | Supervisor |

## Licence
TBD
