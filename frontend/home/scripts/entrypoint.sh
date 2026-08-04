#!/bin/sh
set -e

# Substitute environment variables into the HTML template
cp /usr/share/nginx/html/index.html.template /usr/share/nginx/html/index.html

# Generate full nginx server block (single-quoted heredoc prevents shell expansion of $host etc.)
cat > /etc/nginx/conf.d/default.conf << 'NGINX_EOF'
server {
    listen 8080;
    listen [::]:8080;
    server_name localhost;
    resolver 127.0.0.11 valid=5s ipv6=off;
    root /usr/share/nginx/html;

    gzip on;
    gzip_types text/html text/css application/javascript application/json;

    # ── Home pages ────────────────────────────────────────
    location = /           { try_files /map.html =404; }
    location = /map.html   { try_files /map.html =404; }
    location = /services   { try_files /index.html =404; }
    location = /data       { try_files /data.html =404; }
    location = /report-bug { try_files /report-bug.html =404; }
    location = /about      { try_files /about.html =404; }

    # Serve local files first; fall back to stac-browser for webpack lazy chunks
    # (publicPath "/" is baked into the upstream image build, cannot be changed)
    location /js/ {
        try_files $uri @stac_js;
        add_header Cache-Control "no-cache, must-revalidate";
    }
    location @stac_js {
        proxy_pass http://stac-browser:8080;
    }

    location /css/ {
        try_files $uri @stac_css;
    }
    location @stac_css {
        proxy_pass http://stac-browser:8080;
    }

    # ── STAC Browser ──────────────────────────────────────
    # sub_filter rewrites absolute asset paths in HTML so they load correctly
    # under /stac/. Hash routing (set in browser_config.js) prevents nginx from
    # receiving STAC Browser's internal route paths.
    location /stac/ {
        proxy_pass http://stac-browser:8080/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header Accept-Encoding "";
        sub_filter_once off;
        sub_filter 'src="/js/'       'src="/stac/js/';
        sub_filter 'href="/css/'     'href="/stac/css/';
        sub_filter 'src="/config.js"'   'src="/stac/config.js"';
        sub_filter 'src="/sw.js"'       'src="/stac/sw.js"';
        sub_filter '"/mitm.html"'       '"/stac/mitm.html"';
        sub_filter '<body>' '<body><script src="/sdss-nav.js"></script>';
    }
    location /stac/js/       { proxy_pass http://stac-browser:8080/js/; }
    location /stac/css/      { proxy_pass http://stac-browser:8080/css/; }
    location /stac/img/      { proxy_pass http://stac-browser:8080/img/; }
    location /stac/config.js { proxy_pass http://stac-browser:8080/config.js; }
    location /stac/sw.js     { proxy_pass http://stac-browser:8080/sw.js; }
    location /stac/mitm.html { proxy_pass http://stac-browser:8080/mitm.html; }

    # ── Chatbot frontend ──────────────────────────────────
    # Vite build uses relative asset paths (./assets/) so no sub_filter needed
    # for JS/CSS. Only /favicon.svg and /env-config.js are absolute in index.html.
    location /chatbot/ {
        proxy_pass http://chatbot-frontend:3001/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header Accept-Encoding "";
        sub_filter_once off;
        sub_filter 'href="/favicon.svg"'  'href="/chatbot/favicon.svg"';
        sub_filter 'src="/env-config.js"' 'src="/chatbot/env-config.js"';
        sub_filter '<head>'               '<head><script src="/js/chatbot-bridge.js"></script>';
        sub_filter '<body>' '<body><script src="/sdss-nav.js"></script>';
        proxy_hide_header X-Frame-Options;
        add_header X-Frame-Options SAMEORIGIN;
    }
    location /chatbot/assets/     { proxy_pass http://chatbot-frontend:3001/assets/; }
    location /chatbot/favicon.svg { proxy_pass http://chatbot-frontend:3001/favicon.svg; }
    location /chatbot/env-config.js { proxy_pass http://chatbot-frontend:3001/env-config.js; }
    location /chatbot/images/     { proxy_pass http://chatbot-frontend:3001/images/; }
    location /chatbot/maps-config.json {
        proxy_pass http://chatbot-frontend:3001/maps-config.json;
    }
    location /chatbot/pc_collections_metadata.json {
        proxy_pass http://chatbot-frontend:3001/pc_collections_metadata.json;
    }

    # ── Chatbot API routes ────────────────────────────────
    # The React SPA uses window.location.origin as its Axios base URL, so API
    # calls from /chatbot/ arrive at home nginx as root-relative paths.
    location ~ ^/(api|query|chat|unified-chat|enhanced-chat|collections|stac-search|veda|search|intelligent-route|health|debug|maps-config|pc_collections_metadata\.json)(/|$) {
        proxy_pass http://chatbot-backend:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        # CPU-only local Ollama can take >120s for a single completion, and
        # one chat turn can chain several completions in the agent's tool
        # loop (observed ~325s total across 3 completions in production, on
        # top of process/STAC lookups) — 300s was sized for one completion
        # and isn't enough headroom for the full loop.
        proxy_read_timeout 600s;
    }

    # ── SDSS spatial process routes ────────────────────────────
    location /sdss/ {
        proxy_pass http://chatbot-backend:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_read_timeout 600s;
    }

    # ── Local Agri-SDSS API proxies (used by chatbot-bridge.js) ────────────────
    location /stac-api/ {
        proxy_pass http://stac-api:8080/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        add_header Access-Control-Allow-Origin *;
    }
    location /vector-api/ {
        proxy_pass http://vector-api:8080/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header Accept-Encoding "";
        add_header Access-Control-Allow-Origin *;
        proxy_read_timeout 120s;
        sub_filter_once off;
        sub_filter_types text/html;
        sub_filter "url: '/postgis/api'" "url: '/vector-api/postgis/api'";
    }
    location /raster-api/ {
        proxy_pass http://raster-api:8080/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        add_header Access-Control-Allow-Origin *;
    }
    location /process-api/ {
        proxy_pass http://process-api:5000/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        add_header Access-Control-Allow-Origin *;
        proxy_read_timeout 630s;
    }
    # ── Agriculture Canada AAC identify proxy (no CORS headers on origin) ───────
    location /aac-identify/ {
        proxy_pass https://agriculture.canada.ca/imagery-images/rest/services/;
        proxy_set_header Host agriculture.canada.ca;
        proxy_ssl_server_name on;
        add_header Access-Control-Allow-Origin *;
        proxy_read_timeout 30s;
    }

    # Serve nav-inject.js at a stable path that STAC's sub_filter won't rewrite.
    location = /sdss-nav.js {
        alias /usr/share/nginx/html/js/nav-inject.js;
        add_header Cache-Control "no-cache, must-revalidate";
    }

    location / { try_files $uri $uri/ =404; }

    error_page 500 502 503 504 /50x.html;
    location = /50x.html { root /usr/share/nginx/html; }
}
NGINX_EOF

# Patch ports that could not be expanded inside the single-quoted heredoc
sed -i "s|proxy_pass http://stac-api:8080/|proxy_pass http://stac-api:${STAC_API_PORT}/|g" /etc/nginx/conf.d/default.conf
sed -i "s|proxy_pass http://vector-api:8080/|proxy_pass http://vector-api:${VECTOR_API_PORT}/|g" /etc/nginx/conf.d/default.conf
sed -i "s|proxy_pass http://raster-api:8080/|proxy_pass http://raster-api:${RASTER_API_PORT}/|g" /etc/nginx/conf.d/default.conf

exec nginx -g 'daemon off;'
