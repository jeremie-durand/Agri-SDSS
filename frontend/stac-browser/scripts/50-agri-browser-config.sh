#!/bin/sh
set -e

# Runs after upstream's 40-stac-browser-entrypoint.sh, which rewrites
# runtime-config.js from SB_* variables on every start. Our config holds
# functions that SB_* variables cannot express, so it replaces that file.
envsubst '${HOST_URL} ${STAC_BROWSER_PORT}' \
    < /opt/agri/browser_config.js \
    > /usr/share/nginx/html/runtime-config.js.tmp
mv -f /usr/share/nginx/html/runtime-config.js.tmp /usr/share/nginx/html/runtime-config.js
