#!/bin/bash
#
echo "Starting STAC FastAPI..."
echo "Environment variables:"
echo "PGHOST: $PGHOST"
echo "PGUSER: $PGUSER"
echo "PGDATABASE: $PGDATABASE"
#
echo "Waiting for database to be ready..."
/usr/local/bin/wait-for-it.sh ${PGHOST}:${PGPORT} --timeout=120 --strict -- echo "Database is ready."
#
# Give the app role its pgstac access through pgstac_ingest (idempotent — safe on
# every start; see apply_pgstac_grants.sql). Uses admin credentials
# (PGSTAC_ADMIN_USER/PGSTAC_ADMIN_PASS) so the API itself can run as the
# least-privilege app role (PGUSER/PGPASSWORD).
echo "Applying pgstac grants to ${PGUSER}..."
psql "postgresql://${PGSTAC_ADMIN_USER}:${PGSTAC_ADMIN_PASS}@${PGHOST}:${PGPORT}/${PGDATABASE}" \
    -X -q -v ON_ERROR_STOP=1 --single-transaction -v app_role="${PGUSER}" \
    -f /app/scripts/apply_pgstac_grants.sql \
    && echo "pgstac grants applied." \
    || echo "Warning: could not apply pgstac grants — API may fail to start if role lacks access."
#
echo "Starting FastAPI uvicorn server..."
MAX_RETRIES=5
RETRY_DELAY=5
_TERMINATED=0
for i in $(seq 1 $MAX_RETRIES); do
    uvicorn stac_api.app:create_app --factory \
        --host ${HOST} \
        --port ${STAC_API_PORT} \
        --workers ${WEB_CONCURRENCY:-1} \
        --log-level info \
        --root-path ${APP_ROOT_PATH:-} &
    PID=$!
    trap '_TERMINATED=1; kill -TERM $PID' SIGTERM
    wait $PID
    EXIT_CODE=$?
    trap - SIGTERM
    [ $_TERMINATED -eq 1 ] && exit 143
    [ $EXIT_CODE -eq 0 ] && break
    if [ $i -lt $MAX_RETRIES ]; then
        echo "STAC API startup failed (attempt $i/$MAX_RETRIES, exit $EXIT_CODE). Retrying in ${RETRY_DELAY}s..."
        sleep $RETRY_DELAY
    fi
done
exit $EXIT_CODE