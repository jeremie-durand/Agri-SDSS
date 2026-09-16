# Agri-SDSS

Geospatial data platform for sustainable agriculture research in Quebec. Automated pipeline from raw geodata to OGC-compliant APIs, a STAC catalog, and an AI assistant.

Currently specialized for Soil Organic Matter (SOM) potential mapping and decision support for Quebec agricultural parcels. The modular architecture based on microservices and Docker makes each service independently reusable. Adapt or replace individual components (pipeline, APIs, frontend, chatbot) for your own geospatial use case.

## Quick start

```bash
git clone https://github.com/jeremie-durand/Agri-SDSS.git
cd Agri-SDSS && cp .env.example .env
```

```bash
# Set the two required database passwords
sed -i.bak -e "s|^POSTGRES_PASS=.*|POSTGRES_PASS=$(openssl rand -hex 24)|" \
           -e "s|^DB_PASS=.*|DB_PASS=$(openssl rand -hex 24)|" .env && rm .env.bak
```

```bash
# Build the app
make build
```

`make build` downloads several GB on first run and retries automatically if the connection drops mid-download. May take several minutes.

```bash
# Start the app
docker compose up -d
```

The platform is now available at **[https://localhost](https://localhost)** — accept the browser's certificate warning (local self-signed TLS). The home page links to the interactive map, the STAC catalog browser, the AI assistant, and the APIs.

### Load the demo data

A small BDPPAD extract (~14,500 FADQ farm parcels, Montérégie 2025) ships in
the repo so the map has data out of the box:

```bash
cp data/demo/bdppad/bdppad_demo_an_2025.gpkg data/input/
docker compose exec gis-pipeline python3 -m gis_pipeline.main
```

Reload the page, or run `docker compose restart vector-api` to see the result: Parcels now appear on the interactive map — open the **BDPPAD**  panel and select **2025**.

### Adding more data

Drop files in `data/input/`, then run the pipeline:

```bash
docker compose exec gis-pipeline python3 -m gis_pipeline.main
```

Data is now available across all APIs and frontends. See **[https://localhost/data](https://localhost/data)**.

## Services

Containerized services cover the full path from raw geodata to public APIs and frontends: the ETL pipeline (`gis-pipeline`), four standards-based APIs (`stac-api`, `vector-api`, `raster-api`, `process-api`), the AI assistant (`chatbot`), the `stac-browser` explorer, the unified `home` frontend, `caddy` for TLS, and the PostGIS `database`.

## Documentation

| | |
| --- | --- |
| [Architecture](docs/ARCHITECTURE.md) | System diagram, data flow, common API commands |
| [Deployment](docs/DEPLOYMENT.md) | Production setup with Caddy TLS |
| [Data catalog](docs/data/CATALOG.md) | Integrated datasets |
| [Contributing](docs/CONTRIBUTING.md) | Branching, commits, PRs |
| [Internationalization](docs/I18N.md) | FR/EN error messages and how to request a language |
| [Technical docs](docs/README.md) | Full documentation index |

## Credits & Acknowledgments

This project was originally developed as part of a master's degree at Université de Sherbrooke with a research internship at Mon Système Fourrager, and is an open-source contribution to the [RQRAD's Spatial Decision Support System SOM project](https://rqrad.com/projet/developpement-dun-systeme-daide-a-la-decision-pour-determiner-le-potentiel-daccumulation-de-matiere-organique-du-sol-au-quebec-et-les-pratiques-pour-latteindre/).

### Authors

| Name | Role | Affiliation |
| --- | --- | --- |
| Jérémie Durand | Lead developer & maintainer | [Université de Sherbrooke](https://www.usherbrooke.ca/) & [Mon Système Fourrager](https://msfourrager.com/) |
| Rami Albasha | Reviewer | [Mon Système Fourrager](https://msfourrager.com/) |
| Jules Robichaud-Gagnon | Reviewer | [Mon Système Fourrager](https://msfourrager.com/) |
| Mickaël Germain | Reviewer & Project supervisor | [Université de Sherbrooke](https://www.usherbrooke.ca/) |
| Maxime Leduc | Project supervisor | [Mon Système Fourrager](https://msfourrager.com/) |
| Yacine Bouroubi | Project supervisor | [Université de Sherbrooke](https://www.usherbrooke.ca/) |

### Contributors

- Hamed Etezadi — author of the mos-predict SOM prediction model, integrated into the process-api.

Thanks to everyone who contributes code, issues, or reviews. All contributors are listed automatically on the [contributors graph](https://github.com/jeremie-durand/Agri-SDSS/graphs/contributors).

### Built on open-source projects

This project was inspired by [eoAPI](https://github.com/developmentseed/eoAPI) by [Development Seed](https://developmentseed.org/), whose STAC + raster + vector API architecture served as the starting point for this platform. This project assembles and extends existing open-source work — see [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the full technology stack and links to upstream repositories.

## License

This project is licensed under the [MIT License](LICENSE). Licenses of the open-source components it builds on are inventoried in [docs/THIRD_PARTY_LICENSES.md](docs/THIRD_PARTY_LICENSES.md).
