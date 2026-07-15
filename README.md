# Agri-SDSS

Geospatial data platform for sustainable agriculture research in Quebec. Automated pipeline from raw geodata to OGC-compliant APIs, a STAC catalog, and an AI assistant.

Currently specialized for Soil Organic Matter (SOM) potential mapping and decision support for Quebec agricultural parcels. The modular architecture based on microservices and Docker makes each service independently reusable. Adapt or replace individual components (pipeline, APIs, frontend, chatbot) for your own geospatial use case.

## Quick start

```bash
git clone https://github.com/Mon-Systeme-Fourrager/agri-sdss.git
cd agri-sdss && cp .env.example .env
docker compose up -d
```

Drop files in `data/input/`, then run the pipeline:

```bash
docker compose exec gis-pipeline python3 -m gis_pipeline.main
```

Data is now available across all APIs and frontends.

## Services

Containerized services cover the full path from raw geodata to public APIs and frontends: the ETL pipeline (`gis-pipeline`), four standards-based APIs (`stac-api`, `vector-api`, `raster-api`, `mos-pygeoapi`), the AI assistant (`mos-chatbot`), the `stac-browser` explorer, the unified `home` frontend, `caddy` for TLS, and the PostGIS `database`. The full service/port table and system diagram are in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Documentation

| | |
| --- | --- |
| [Architecture](docs/ARCHITECTURE.md) | System diagram, data flow, common API commands |
| [Deployment](docs/DEPLOYMENT.md) | Production setup with Caddy TLS |
| [Data catalog](docs/data/CATALOG.md) | Integrated datasets |
| [Contributing](docs/CONTRIBUTING.md) | Branching, commits, PRs |
| [Technical docs](docs/README.md) | Full documentation index |

## Credits & Acknowledgments

This project was originally developed as part of a master's degree at Université de Sherbrooke with a research internship at Mon Système Fourrager, and is an open-source contribution to the [RQRAD's Spatial Decision Support System SOM project](https://rqrad.com/projet/developpement-dun-systeme-daide-a-la-decision-pour-determiner-le-potentiel-daccumulation-de-matiere-organique-du-sol-au-quebec-et-les-pratiques-pour-latteindre/).

### Authors

| Name | Role | Affiliation |
| --- | --- | --- |
| Jérémie Durand | Lead developer & maintainer | [Université de Sherbrooke](https://www.usherbrooke.ca/) & [Mon Système Fourrager](https://msfourrager.com/) |
| Rami Albasha | Reviewer | [Mon Système Fourrager](https://msfourrager.com/) |
| Jules Robichaud-Gagnon | Reviewer | [Mon Système Fourrager](https://msfourrager.com/) |
| Mickaël Germain | Reviewer | [Université de Sherbrooke](https://www.usherbrooke.ca/) |

### Collaborators

| Name | Role | Affiliation |
| --- | --- | --- |
| Maxime Leduc | Project supervisor | [Mon Système Fourrager](https://msfourrager.com/) |
| Yacine Bouroubi | Project supervisor | [Université de Sherbrooke](https://www.usherbrooke.ca/) |

### Built on open-source projects

This platform assembles and extends existing open-source work. See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the full technology stack and links to upstream repositories.

## License

This project is licensed under the [MIT License](LICENSE). Licenses of the open-source components it builds on are inventoried in [docs/THIRD_PARTY_LICENSES.md](docs/THIRD_PARTY_LICENSES.md).
