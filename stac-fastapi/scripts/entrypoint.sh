#!/bin/bash
#
echo "Starting STAC FastAPI..."
echo "Environment variables:"
echo "POSTGRES_HOST: $POSTGRES_HOST"
echo "POSTGRES_USER: $POSTGRES_USER"
echo "POSTGRES_DBNAME: $POSTGRES_DBNAME"
#
echo "Waiting for database to be ready..."
/usr/local/bin/wait-for-it.sh ${POSTGRES_HOST}:${POSTGRES_PORT} --timeout=120 --strict -- echo "Database is ready."
#
echo "Starting FastAPI uvicorn server..."
exec uvicorn stac_fastapi.pgstac.app:app \
    --host ${HOST} \
    --port 8080 \
    --workers ${WEB_CONCURRENCY:-1} \
    --log-level info