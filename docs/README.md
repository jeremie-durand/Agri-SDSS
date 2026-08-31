# Documentation

Central index for Agri-SDSS documentation. Service-specific deep-dives live next to their code in each service's `docs/` folder.

## General

| Document | Description |
| --- | --- |
| [Architecture](ARCHITECTURE.md) | System diagram, data flow, service table, common API commands |
| [Deployment](DEPLOYMENT.md) | Production setup — Linux, Docker, Caddy TLS, DB restore |
| [Contributing](CONTRIBUTING.md) | Branching strategy, commit conventions, PR process |
| [Internationalization](I18N.md) | FR/EN error messages, how to request a language, gettext workflow |
| [Third-party licenses](THIRD_PARTY_LICENSES.md) | License inventory of external tools, copyleft implications |

## Services

| Service | Docs |
| --- | --- |
| `gis-pipeline` | [gis-pipeline/README.md](../gis-pipeline/README.md) |
| `stac-api` | [stac-api/README.md](../stac-api/README.md) |
| `vector-api` | [vector-api/README.md](../vector-api/README.md) |
| `raster-api` | [raster-api/README.md](../raster-api/README.md) |
| `process-api` | [process-api/README.md](../process-api/README.md) |
| `chatbot` | [chatbot/README.md](../chatbot/README.md) |
| `frontend` | [frontend/README.md](../frontend/README.md) |
| `caddy` | [caddy/README.md](../caddy/README.md) |

## Data

| Document | Description |
| --- | --- |
| [Data catalog](data/CATALOG.md) | Integrated datasets and their sources |
| [Adding new data](data/adding_new_data.md) | Step-by-step guide |
| [PostGIS schema](data/postgis_schema.md) | Table layouts created by the pipeline |
| [Database integration](data/database_integration.md) | Connecting the PostGIS DB to an existing PostgreSQL database |

## Design & product

| Document | Description |
| --- | --- |
| [Design system](DESIGN.md) | Color palette, typography, component rules |
| [Product brief](PRODUCT.md) | Users, purpose, brand, accessibility |
