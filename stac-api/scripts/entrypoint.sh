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
# Apply pgstac schema grants to the app role (idempotent — safe on every start).
# Uses admin credentials (PGSTAC_ADMIN_USER/PGSTAC_ADMIN_PASS) so the API itself
# can run as the least-privilege app role (PGUSER/PGPASSWORD).
echo "Applying pgstac grants to ${PGUSER}..."
psql "postgresql://${PGSTAC_ADMIN_USER}:${PGSTAC_ADMIN_PASS}@${PGHOST}:${PGPORT}/${PGDATABASE}" \
    -c "GRANT USAGE ON SCHEMA pgstac TO \"${PGUSER}\";" \
    -c "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA pgstac TO \"${PGUSER}\";" \
    -c "GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA pgstac TO \"${PGUSER}\";" \
    -c "GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA pgstac TO \"${PGUSER}\";" \
    && echo "pgstac grants applied." \
    || echo "Warning: could not apply pgstac grants — API may fail to start if role lacks access."
#
echo "Starting FastAPI uvicorn server..."
MAX_RETRIES=5
RETRY_DELAY=5
_TERMINATED=0
for i in $(seq 1 $MAX_RETRIES); do
    uvicorn stac_api.app:app \
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