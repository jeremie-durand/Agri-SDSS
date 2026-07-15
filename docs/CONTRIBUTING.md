# Contributing to MOS-GIS

Thank you for your interest in contributing! MOS-GIS welcomes contributions from researchers, agronomists, data providers, and developers. Issues and pull requests are welcome in **English or French**.

## Ways to Contribute

You don't need to write code to contribute:

| Contribution | Where to start |
| --- | --- |
| Report a bug or request a feature | [Open an issue](https://github.com/Mon-Systeme-Fourrager/mos-gis/issues) |
| Integrate a new dataset | [Adding new data guide](data/adding_new_data.md) — step-by-step, from source doc to pipeline ingestion |
| Add or improve an OGC process | [Adding a new OGC process](#adding-a-new-ogc-process) below |
| Improve documentation or FR/EN translations | Edit and open a PR — docs live in `docs/` and each service's folder |
| Improve the map, chatbot, or UI | [frontend/home/README.md](../frontend/home/README.md) and [mos-chatbot/docs/ARCHITECTURE.md](../mos-chatbot/docs/ARCHITECTURE.md) |

## Development Setup

```bash
# Fork the repository on GitHub, then:
git clone https://github.com/YOUR_USERNAME/mos-gis.git
cd mos-gis
git remote add upstream https://github.com/Mon-Systeme-Fourrager/mos-gis.git

# Configure and start the stack
cp .env.example .env
docker compose up -d

# Verify everything works
make test-all
```

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
make test-mos-pygeoapi
make test-mos-chatbot

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

Follow the pattern of the seven existing processes in `mos-pygeoapi/processes/`:

1. `processes/<name>.py` (processor class) + `processes/<name>_metadata.py` (PROCESS_METADATA)
2. Register it in `mos-pygeoapi/config/pygeoapi-config.yaml`
3. Write a spec doc in `mos-pygeoapi/docs/` (see [SOM_PREDICT_SOIL_SPECS.md](../mos-pygeoapi/docs/SOM_PREDICT_SOIL_SPECS.md) for the format)
4. Add the process to the [mos-pygeoapi README](../mos-pygeoapi/README.md) table
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

MOS-GIS is [MIT-licensed](../LICENSE). By contributing, you agree that your contributions are licensed under the same terms.

## Getting Help

- Check the [documentation index](README.md)
- Review [existing issues](https://github.com/Mon-Systeme-Fourrager/mos-gis/issues)
- Ask questions in issue discussions — in English or French

## Recognition

Contributors are recognized in release notes and project documentation.

Thank you for helping improve MOS-GIS!
