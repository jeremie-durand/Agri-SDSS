# Contributing to Agri-SDSS

Thank you for your interest in contributing! Agri-SDSS welcomes contributions from researchers, agronomists, data providers, and developers. Issues and pull requests are welcome in **English or French**.

## Ways to Contribute

You don't need to write code to contribute:

| Contribution | Where to start |
| --- | --- |
| Report a bug or request a feature | [Open an issue](https://github.com/jeremie-durand/Agri-SDSS/issues) |
| Integrate a new dataset | [Adding new data guide](data/adding_new_data.md) — step-by-step, from source doc to pipeline ingestion |
| Add or improve an OGC process | [Adding a new OGC process](#adding-a-new-ogc-process) below |
| Improve documentation or FR/EN translations | Edit and open a PR — docs live in `docs/` and each service's folder |
| Improve the map, chatbot, or UI | [frontend/home/README.md](../frontend/home/README.md) and [chatbot/docs/ARCHITECTURE.md](../chatbot/docs/ARCHITECTURE.md) |

## Development Setup

**Prerequisites:** Docker with the Compose plugin, GNU Make, and `openssl` (for password generation). Everything else runs inside containers.

### 1. Fork and clone

```bash
# Fork the repository on GitHub, then:
git clone https://github.com/YOUR_USERNAME/Agri-SDSS.git
cd Agri-SDSS
git remote add upstream https://github.com/jeremie-durand/Agri-SDSS.git
```

### 2. Configure the environment

```bash
cp .env.example .env

# Set the two required database passwords
sed -i.bak -e "s|^POSTGRES_PASS=.*|POSTGRES_PASS=$(openssl rand -hex 24)|" \
           -e "s|^DB_PASS=.*|DB_PASS=$(openssl rand -hex 24)|" .env && rm .env.bak
```

Good to know:

- PostgreSQL is initialized with these credentials on the **first** `docker compose up`. To change them afterwards, use `ALTER ROLE` in the database — or wipe `./data/pg` to re-initialize.
- If you set passwords by hand, use only letters and digits — some services embed them in a connection URL.
- Don't export `DB_PASS`/`POSTGRES_PASS` in your shell: OS environment variables override `.env` in Docker Compose.
- Optional integrations (LLM API key for the chatbot, OpenEO token for climate processes) are documented in `.env.example`.

### 3. Build and start

```bash
make build            # creates the data/ dirs, builds all images (auto-retries once on network failure)
docker compose up -d  # first start initializes the database
```

The first build downloads several GB and compiles GDAL — expect several minutes.

### 4. Verify

```bash
docker compose ps     # every service should reach "healthy" or "running"
make test-all         # full test suite — the same thing CI runs
```

Then open **[https://localhost](https://localhost)** (accept the self-signed certificate warning): you should see the home frontend. The database is reachable directly at `localhost:5439` with the credentials from `.env`.

### 5. Load sample data (optional)

Drop any supported geodata file (GeoJSON, Shapefile, GeoPackage, GeoTIFF, …) in `data/input/`, then:

```bash
docker compose exec gis-pipeline python3 -m gis_pipeline.main
```

Outputs land in PostGIS, GeoParquet (`data/duckdb/`), and the STAC catalog — browsable at [https://localhost/data](https://localhost/data).

### Troubleshooting first runs

| Symptom | Cause and fix |
| --- | --- |
| Build aborts with `Connection broken` | Dropped connection during a large download. `make build` already retries once; if it still fails, run it again — completed layers are cached, so it resumes where it left off. |
| `password authentication failed` in a service's logs | `.env` credentials changed after the database was first initialized, or shell-exported `DB_PASS`/`POSTGRES_PASS` are overriding `.env`. Fix with `ALTER ROLE` in PostgreSQL, or wipe `./data/pg` and restart. |
| `Permission denied` writing under `/data/...` | A `data/` subdirectory was created by Docker as root — happens when the stack starts on a machine where the directory is missing (e.g., after a manual wipe without `make build`). Fix: `sudo chown -R $(id -u):$(id -g) data/duckdb data/output`. |

To get oriented: [ARCHITECTURE.md](ARCHITECTURE.md) has the system diagram and service table, and the [documentation index](README.md) links every guide.

## Reporting Issues

1. **Search existing issues** to avoid duplicates
2. **Create a new issue** with a clear title and description
3. **Include relevant details**: steps to reproduce, expected vs actual behavior, environment (OS, Docker version), sample data or error messages

## Submitting Changes

### 1. Create a Branch

We follow **Git Flow**:

- **`develop`** — main development branch (PRs target here)
- **`main`** — production releases
- **`feature/*`** — new features (from `develop`)
- **`bugfix/*`** — bug fixes (from `develop`)

```bash
git checkout develop
git pull upstream develop
git checkout -b feature/your-feature-name
```

### 2. Make Your Changes

- Follow the [code style](#code-style) below
- Add tests for new functionality (see [testing guidelines](#testing-guidelines))
- Update documentation touched by your change

### 3. Test Your Changes

```bash
# Run all tests
make test-all

# Run a specific service's tests
make test-gis-pipeline
make test-stac-api
make test-vector-api
make test-raster-api
make test-process-api
make test-chatbot

# Single test file (inside container)
docker compose run --rm stac-api pytest stac_api/test/test_foo.py::test_bar -v
```

### 4. Commit

Use conventional-style prefixes:

```bash
git commit -m "feat: add new processing feature"
git commit -m "fix: resolve projection issue in pipeline"
```

| Prefix | Use for |
| --- | --- |
| `feat:` | New feature |
| `fix:` | Bug fix |
| `docs:` | Documentation changes |
| `test:` | Test additions/changes |
| `refacto:` | Code refactoring |
| `chore:` | Maintenance tasks |

### 5. Open a Pull Request

1. Push your branch and open a PR against **`develop`**
2. Describe what changed, why, and any breaking changes
3. Link related issues (e.g., "Closes #123")

**Before requesting review, check:**

- [ ] `make test-all` passes
- [ ] New logic is covered by tests
- [ ] Documentation updated (READMEs, guides, catalog)
- [ ] If you changed CLI arguments: `make generate-args` was run (CI fails if `ARGS.md` is out of sync)

CI will build the service images, verify `ARGS.md` sync, run the full test suite, and run a security scan.

### Code Review Process

- Maintainers review your PR and may request changes
- Once approved, your PR is merged into `develop`

## Adding a New Data Source

The most common contribution — fully documented in the [adding new data guide](data/adding_new_data.md). In short:

1. Document the source in `docs/data/sources/SOURCENAME.md` (template in the guide)
2. Add a row to the [data catalog](data/CATALOG.md) — including its license
3. Drop the files in `data/input/` and run the pipeline
4. Verify PostGIS/STAC/API outputs and add tests

Data must be under an open license (OGL-Q, OGL-Canada, CC-BY, …) — note it in the source doc.

## Adding a New OGC Process

Follow the pattern of the seven existing processes in `process-api/processes/`:

1. `processes/<name>.py` (processor class) + `processes/<name>_metadata.py` (PROCESS_METADATA)
2. Register it in `process-api/config/pygeoapi-config.yaml`
3. Write a spec doc in `process-api/docs/` (see [SOM_PREDICT_SOIL_SPECS.md](../process-api/docs/SOM_PREDICT_SOIL_SPECS.md) for the format)
4. Add the process to the [process-api README](../process-api/README.md) table
5. Add tests with the appropriate markers

## Code Style

- Follow PEP 8; line length 88 characters maximum
- Type hints required for all code
- Document with docstrings; avoid comments
- Use f-strings for formatting
- Keep functions focused and small

## Testing Guidelines

- Tests are marked `@pytest.mark.unit`, `@pytest.mark.mocked`, or `@pytest.mark.integration`
- Unit tests for pure logic; **prefer mocked tests** when external services are involved
- Cover the normal path, an edge case, and the error path
- Ensure tests pass before submitting a PR

## License

Agri-SDSS is [MIT-licensed](../LICENSE). By contributing, you agree that your contributions are licensed under the same terms.

## Getting Help

- Check the [documentation index](README.md)
- Review [existing issues](https://github.com/jeremie-durand/Agri-SDSS/issues)
- Ask questions in issue discussions — in English or French

## Recognition

Contributors are recognized in release notes and project documentation.

Thank you for helping improve Agri-SDSS!
