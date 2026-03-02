#!/bin/bash
# wait for the database
/usr/local/bin/wait-for-it.sh -t 120 -h $POSTGRES_HOST -p $POSTGRES_PORT -- echo "Database is ready"
#
# execute the command passed to the docker service
# Uses custom app that combines TiPg (PostGIS) + Parquet router (DuckDB)
exec gunicorn -k uvicorn.workers.UvicornWorker vector_api.app:app --bind ${HOST}:8080