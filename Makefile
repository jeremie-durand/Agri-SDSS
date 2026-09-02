build:
	mkdir -p data/input data/duckdb/duckdb_extensions data/output/raster_cog
	docker compose build || docker compose build

test-all: test-i18n test-gis-pipeline test-stac-api test-vector-api test-raster-api test-process-api test-chatbot
	docker compose up -d --force-recreate --wait vector-api raster-api process-api
	docker compose restart home

test-gis-pipeline:
	docker compose run --build --rm gis-pipeline pytest gis_pipeline/test/ -v

generate-args:
	docker compose run --build --rm --no-deps \
		-v $(CURDIR)/gis-pipeline/docs:/app/docs \
		gis-pipeline python3 -m gis_pipeline.generate_args_md

test-stac-api:
	docker compose run --build --rm stac-api pytest stac_api/test/ -v

test-vector-api:
	docker compose run --build --rm vector-api pytest vector_api/test/ -v

test-raster-api:
	docker compose run --build --rm raster-api pytest raster_api/test/ -v

test-process-api:
	docker compose run --build --rm process-api pytest process_api/test/ -v

test-chatbot:
	docker compose run --build --rm chatbot-backend pytest chatbot/test/ -v

test-i18n:
	docker compose run --build --rm --no-deps process-api pytest agri_i18n/test/ -v

# --- i18n catalog authoring -------------------------------------------------
# Runs inside process-api, whose image already carries Babel as a pygeoapi
# dependency, so no host toolchain is needed. Always invoke from the repo root.
I18N_RUN = docker compose run --rm --no-deps -T -v $(CURDIR):/repo -w /repo process-api

# Rescan the source for _() calls. The .pot is a local intermediate consumed by
# i18n-update and is gitignored; the .po catalogs are the versioned artifact.
i18n-extract:
	$(I18N_RUN) pybabel extract -F agri_i18n/babel.cfg --omit-header \
		-o agri_i18n/messages.pot .

# Merge new msgids into the per-language catalogs, keeping old msgids as
# comments. New or changed entries land as fuzzy for a translator to confirm.
i18n-update: i18n-extract
	$(I18N_RUN) pybabel update -i agri_i18n/messages.pot -d agri_i18n/locales \
		-D messages --previous

i18n-compile:
	$(I18N_RUN) pybabel compile -d agri_i18n/locales -D messages --statistics

# CI gate: no dynamic msgids, catalogs cover the source, every msgstr filled.
i18n-check:
	$(I18N_RUN) python -m agri_i18n.check

test-caddy:
	@echo "Hot-reloading Caddy with test config (3 exec/5s, 5 browse/5s)..."
	docker cp caddy/Caddyfile.test $$(docker compose ps -q caddy):/tmp/Caddyfile.test
	docker compose exec caddy caddy reload --config /tmp/Caddyfile.test --adapter caddyfile
	@echo "Running rate limiting integration tests..."
	docker run --rm \
		--network eoapi-network \
		-v $(CURDIR)/caddy/test:/test:ro \
		-e CADDY_BASE_URL=https://caddy \
		-e RATE_LIMIT_PYGEOAPI_EXEC_EVENTS=3 \
		-e RATE_LIMIT_PYGEOAPI_BROWSE_EVENTS=5 \
		python:3.11-slim \
		sh -c "pip install pytest requests urllib3 -q && pytest /test/ -v -m integration -p no:cacheprovider"
	@echo "Restoring production Caddyfile..."
	docker compose exec caddy caddy reload --config /etc/caddy/Caddyfile --adapter caddyfile

.PHONY: build lint-dockerfiles lint-md scan-secrets test-caddy generate-args \
	test-i18n i18n-extract i18n-update i18n-compile i18n-check

# Ignored rules, and why (hadolint exits non-zero on any warning, so each must be
# listed explicitly rather than blanket-suppressed
HADOLINT_IGNORES := --ignore DL3008 --ignore DL3013 --ignore DL3018 \
	--ignore DL3006 --ignore DL3007 --ignore DL3025 --ignore DL3066

lint-dockerfiles:
	docker run --rm -i hadolint/hadolint hadolint $(HADOLINT_IGNORES) - < chatbot/Dockerfile.chatbot-backend
	docker run --rm -i hadolint/hadolint hadolint $(HADOLINT_IGNORES) - < chatbot/Dockerfile.chatbot-frontend

lint-md:
	pre-commit run markdownlint-cli2 --all-files

scan-secrets:
	trivy fs --scanners secret .
