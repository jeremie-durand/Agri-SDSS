#!/bin/bash
set -e
#
echo "Waiting for database to be ready..."
/usr/local/bin/wait-for-it.sh ${POSTGRES_HOST}:${POSTGRES_PORT} --timeout=120 --strict -- echo "Database is ready."
#
echo "GIS Pipeline container is ready."
echo "Run pipeline with: docker compose exec gis-pipeline python3 -m gis_pipeline.main [ARGS]"
exec "$@"