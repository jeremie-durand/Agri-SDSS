test-all: test-gis-pipeline test-stac-api test-vector-api test-raster-api test-mos-pygeoapi test-mos-chatbot
	docker compose up -d --force-recreate --wait vector-api raster-api mos-pygeoapi
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

test-mos-pygeoapi:
	docker compose run --build --rm mos-pygeoapi pytest mos_pygeoapi/test/ -v

test-mos-chatbot:
	docker compose run --build --rm mos-chatbot-backend pytest mos_chatbot/test/ -v

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

.PHONY: lint-dockerfiles scan-secrets test-caddy generate-args

lint-dockerfiles:
	docker run --rm -i hadolint/hadolint hadolint --ignore DL3008 --ignore DL3013 --ignore DL3018 - < mos-chatbot/Dockerfile.mos-chatbot-backend
	docker run --rm -i hadolint/hadolint hadolint --ignore DL3008 --ignore DL3013 --ignore DL3018 - < mos-chatbot/Dockerfile.mos-chatbot-frontend

scan-secrets:
	trivy fs --scanners secret .
