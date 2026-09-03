#!/bin/sh
set -e

# Substitute runtime environment variables into the browser config.
# The Dockerfile copies browser_config.js to /usr/share/nginx/html/config.js
# as a template; we expand it in-place here.
envsubst '${HOST_URL} ${STAC_BROWSER_PORT}' \
    < /usr/share/nginx/html/config.js \
    > /tmp/config.js
mv /tmp/config.js /usr/share/nginx/html/config.js

# Configure nginx port
sed -i "s/listen .*/listen 8080;/" /etc/nginx/conf.d/default.conf
sed -i "s/listen \[::\]:.*/listen [::]:8080;/" /etc/nginx/conf.d/default.conf

exec nginx -g 'daemon off;'
