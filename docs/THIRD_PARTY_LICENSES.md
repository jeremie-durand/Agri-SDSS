# Third-Party Licenses

License inventory of the external open-source software MOS-GIS builds on, and what each license means for releasing this project under the [MIT License](../LICENSE) — including commercial use.

> **Disclaimer**: this is a good-faith engineering summary, not legal advice.

## Summary

**MOS-GIS can be released under MIT and used commercially.** Every component is either permissively licensed (MIT / BSD / Apache-2.0 / PostgreSQL / PSF) or a copyleft component used in a way that imposes no obligations on MOS-GIS code (see [Copyleft components](#copyleft-components)). No component requires MOS-GIS itself to adopt a copyleft license.

## Core services & container images

| Tool | Role in MOS-GIS | License |
| --- | --- | --- |
| [PostgreSQL](https://www.postgresql.org/about/licence/) | Database | PostgreSQL License (permissive) |
| [PostGIS](https://postgis.net/) | Spatial database extension | GPL-2.0-or-later ⚠️ |
| [pgSTAC](https://github.com/stac-utils/pgstac) | STAC database schema (`database` image) | MIT |
| [stac-fastapi / stac-fastapi-pgstac](https://github.com/stac-utils/stac-fastapi) | `stac-api` | MIT |
| [TiTiler](https://github.com/developmentseed/titiler) | `raster-api` | MIT |
| [TiPg](https://github.com/developmentseed/tipg) | `vector-api` (PostGIS backend) | MIT |
| [PyGeoAPI](https://github.com/geopython/pygeoapi) | `mos-pygeoapi` (OGC Processes) | MIT |
| [DuckDB](https://github.com/duckdb/duckdb) | GeoParquet analytics | MIT |
| [GDAL](https://github.com/OSGeo/gdal) | Raster processing (`gdalwarp`, COG) | MIT |
| [STAC Browser](https://github.com/radiantearth/stac-browser) | `stac-browser` catalog UI | Apache-2.0 |
| [OpenGeo-AI-Assistant](https://github.com/jeremie-durand/OpenGeo-AI-Assistant) | `mos-chatbot` upstream | MIT (incl. Microsoft Earth Copilot portions, also MIT) |
| [Ollama](https://github.com/ollama/ollama) | Optional local LLM runtime | MIT |
| [Caddy](https://github.com/caddyserver/caddy) | TLS entry point | Apache-2.0 |
| [caddy-ratelimit](https://github.com/mholt/caddy-ratelimit) | Rate-limiting Caddy plugin | Apache-2.0 |
| [nginx](https://nginx.org/LICENSE) | `home` + frontend web server | BSD-2-Clause |
| [Python](https://docs.python.org/3/license.html) | Backend runtime | PSF-2.0 |
| [Node.js](https://github.com/nodejs/node/blob/main/LICENSE) | Frontend build toolchain | MIT |

Container base images (`alpine`, `python-slim`/Debian, `node-alpine`) bundle OS packages under their own licenses; this is standard Docker practice and imposes no obligations on MOS-GIS code.

## Python libraries

| Library | Used by | License |
| --- | --- | --- |
| FastAPI / Starlette | APIs | MIT / BSD-3-Clause |
| SQLAlchemy / GeoAlchemy2 | gis-pipeline | MIT |
| psycopg (3) | PostGIS access | LGPL-3.0 ⚠️ |
| asyncpg | stac-api | Apache-2.0 |
| GeoPandas / pandas / NumPy / SciPy | gis-pipeline, processes | BSD-3-Clause |
| Shapely / Fiona / Rasterio | gis-pipeline | BSD-3-Clause |
| pyproj | CRS handling | MIT |
| scikit-learn | som-predict-soil (RandomForest) | BSD-3-Clause |
| matplotlib | som backend (Agg only) | Matplotlib License (PSF-based, permissive) |
| xarray / rioxarray | climate processes | Apache-2.0 |
| cftime / pydap | OPeNDAP access | MIT |
| openeo | sentinel-fetch | Apache-2.0 |
| pystac | STAC objects | Apache-2.0 |
| stac-pydantic / pydantic | validation | MIT |
| pyarrow | GeoParquet | Apache-2.0 |
| duckdb (Python) | vector-api, processes | MIT |
| requests / httpx | HTTP clients | Apache-2.0 / BSD-3-Clause |
| structlog | gis-pipeline logging | MIT / Apache-2.0 (dual) |
| uvicorn / gunicorn | ASGI servers | BSD-3-Clause / MIT |
| PyYAML | configuration | MIT |
| pygeoif | pygeoapi dependency | LGPL ⚠️ |
| certifi | TLS CA bundle | MPL-2.0 ⚠️ |

## Frontend libraries

| Library | Used by | License |
| --- | --- | --- |
| [Leaflet](https://github.com/Leaflet/Leaflet) | home map | BSD-2-Clause |
| [React](https://github.com/facebook/react) + [Vite](https://github.com/vitejs/vite) | mos-chatbot-frontend | MIT |
| [Vue.js](https://github.com/vuejs/core) | stac-browser | MIT |

## Development & CI tools (not distributed)

| Tool | Role | License |
| --- | --- | --- |
| pytest | Test framework | MIT |
| responses | HTTP mocking | Apache-2.0 |
| hadolint | Dockerfile linting (CI) | GPL-3.0 ⚠️ (dev-tool only) |

## Copyleft components

These are the components whose licenses *could* be "invasive" — and why none of them affect MOS-GIS:

- **PostGIS (GPL-2.0-or-later)** — runs as part of the database *server*. MOS-GIS talks to it over SQL connections; it does not link against or embed PostGIS code. GPL obligations apply to PostGIS itself (and would apply if you modified and distributed PostGIS), not to applications that query it. This is the universally accepted reading — countless commercial products use PostGIS this way.
- **psycopg 3 (LGPL-3.0)** — used as an unmodified library. The LGPL allows proprietary and commercially licensed applications to *use* the library freely; obligations only arise if you modify psycopg itself and distribute the modification.
- **pygeoif (LGPL)** — transitive dependency of PyGeoAPI, same reasoning as psycopg: unmodified library use, no obligations.
- **certifi (MPL-2.0)** — file-level copyleft covering only certifi's own files; using it unmodified imposes nothing.
- **hadolint (GPL-3.0)** — a CI lint tool. It is never distributed with MOS-GIS, so its license is irrelevant to users of the platform.

**Attribution requirements**: the permissive licenses (MIT, BSD, Apache-2.0) require preserving copyright notices when *redistributing the components themselves*. Since MOS-GIS pulls them as Docker images and package dependencies (which carry their own notices), no additional action is needed. Apache-2.0 components (Caddy, STAC Browser, openeo, …) additionally require stating significant modifications — MOS-GIS configures but does not modify them.

## Data licenses

Licenses for the *datasets* the platform integrates (OGL-Q, OGL-Canada, …) are a separate concern from software licenses — see the License column in the [data catalog](data/CATALOG.md) and the per-source docs it links.
