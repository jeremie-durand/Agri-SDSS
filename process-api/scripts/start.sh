#!/bin/bash
set -e
#
echo "Initializing pygeoapi..."
#
# Check if config file exists
if [ ! -f "${PYGEOAPI_CONFIG}" ]; then
    echo "Config file not found: ${PYGEOAPI_CONFIG}"
    exit 1
fi
#
# Resolve environment variables in config template
envsubst '${HOST_PROTOCOL} ${HOST_URL}' \
    < "${PYGEOAPI_CONFIG}" > /tmp/pygeoapi-config-resolved.yaml
export PYGEOAPI_CONFIG=/tmp/pygeoapi-config-resolved.yaml
#
# Create openapi directory
mkdir -p "$(dirname "${PYGEOAPI_OPENAPI}")"
#
echo "Generating OpenAPI document with Python..."
python /app/generate_openapi.py
#
# Verify file exists
if [ ! -f "${PYGEOAPI_OPENAPI}" ]; then
    echo "OpenAPI file was not created"
    exit 1
fi
#
FILE_SIZE=$(stat -c%s "${PYGEOAPI_OPENAPI}")
echo "OpenAPI file ready (${FILE_SIZE} bytes)"
#
# Export environment variables
export PYGEOAPI_CONFIG
export PYGEOAPI_OPENAPI
#
echo "Validating environment configuration..."
python -c "
import sys
sys.path.insert(0, '/app')
from processes.config import ApiConfig, DatabaseConfig, FarmConfig, StorageConfig
try:
    DatabaseConfig()
    ApiConfig()
    FarmConfig()
    StorageConfig()
    print('Environment configuration: OK')
except Exception as e:
    print(f'ERROR: invalid environment configuration: {e}', file=sys.stderr)
    sys.exit(1)
"
#
echo "Starting pygeoapi server..."
exec gunicorn processes.wsgi:APP \
    --bind 0.0.0.0:5000 \
    --workers ${WEB_CONCURRENCY:-1} \
    --timeout ${GUNICORN_TIMEOUT:-600} \
    --access-logfile - \
    --access-logformat 'INFO:     %(h)s - "%(r)s" %(s)s' \
    --log-level info