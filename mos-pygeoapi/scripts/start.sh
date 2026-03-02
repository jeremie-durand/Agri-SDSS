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
echo "Starting pygeoapi server..."
exec pygeoapi serve