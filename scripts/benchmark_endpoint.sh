#!/bin/sh
# Time repeated requests to one platform endpoint with curl, as an end user
# would see them, and report mean, median, SD and a 95 % confidence interval.
#
# Protocol (manuscript, Section 4.2): run from the client machine against the
# public deployment; warm = consecutive identical requests (n = 100); cold =
# cache cleared and service restarted before every request (n = 10). The cold
# step runs on the server, so pass it as a command, usually over ssh.
#
# 95 % CI = mean ± z·SD/√n with z = 1.96 when n ≥ 30, and Student's t with
# n − 1 degrees of freedom below that. Only successful (2xx) requests count.
#
# Usage:
#   scripts/benchmark_endpoint.sh -u URL [-d BODY | -f BODY_FILE] [-n N]
#       [-c COLD_CMD] [-r READY_URL] [-o OUT_CSV] [-l LABEL] [-k]
#
#   -u  URL to time (POST when a body is given, GET otherwise)
#   -d  JSON request body, -f  file holding it
#   -n  number of timed requests (default 10)
#   -c  shell command run before every request (cold mode); the script then
#       waits until READY_URL answers 2xx before timing
#   -r  readiness URL polled after COLD_CMD (default: URL's /process-api/
#       root when URL contains /process-api/, else URL itself with GET)
#   -o  CSV that receives one row per request (appended)
#   -l  label written in the CSV (default: warm or cold)
#   -k  accept a self-signed certificate (local deployment)
#
# Examples (production, from the client machine). Quote every URL that holds
# '&'. Replace <...> with the collection, tile or bbox to time.
#
#   # vector-api: one MVT tile of the BDPPAD layer, warm
#   scripts/benchmark_endpoint.sh -n 100 -l mvt-warm -o bench.csv \
#     -u "https://<host>/vector-api/postgis/collections/public.<bdppad_table>/tiles/WebMercatorQuad/<z>/<x>/<y>"
#
#   # vector-api: the same query on the PostGIS (TiPg) and DuckDB back ends
#   scripts/benchmark_endpoint.sh -n 100 -l catalog-postgis -o bench.csv \
#     -u "https://<host>/vector-api/postgis/collections?f=json"
#   scripts/benchmark_endpoint.sh -n 100 -l catalog-duckdb -o bench.csv \
#     -u "https://<host>/vector-api/parquet/collections?f=json"
#   scripts/benchmark_endpoint.sh -n 100 -l bbox-postgis -o bench.csv \
#     -u "https://<host>/vector-api/postgis/collections/public.<bdppad_table>/items?bbox=<w>,<s>,<e>,<n>&limit=1"
#   scripts/benchmark_endpoint.sh -n 100 -l bbox-duckdb -o bench.csv \
#     -u "https://<host>/vector-api/parquet/collections/<bdppad_table>/items?bbox=<w>,<s>,<e>,<n>&limit=1"
#
#   # raster-api: statistics of a province-wide COG, as the SOM form asks them
#   scripts/benchmark_endpoint.sh -n 100 -l cog-stats -o bench.csv \
#     -u "https://<host>/raster-api/cog/statistics?url=file:///data/corg_fr_siigsol_cog.tif&nodata=nan&bidx=1"
#
#   # stac-api: catalog browsing and an item search
#   scripts/benchmark_endpoint.sh -n 100 -l stac-collections -o bench.csv \
#     -u "https://<host>/stac-api/collections"
#   scripts/benchmark_endpoint.sh -n 100 -l stac-search -o bench.csv \
#     -u "https://<host>/stac-api/search" -d '{"collections":["lidar_quebec"],"limit":10}'
#
#   # som-predict-soil, warm
#   scripts/benchmark_endpoint.sh -n 100 -l som-warm -o bench.csv \
#     -u https://<host>/process-api/processes/som-predict-soil/execution \
#     -d '{"inputs":{"field_ids":[195],"scenarios":["S3_spec_soil_topo_clim"]}}'
#
#   # som-predict-soil, cold: delete the trained model and restart
#   scripts/benchmark_endpoint.sh -n 10 -l som-cold -o bench.csv \
#     -c "ssh <vps> 'cd ~/Agri-SDSS && rm -f data/duckdb/som_models/som_model_S3_spec_soil_topo_clim.joblib && docker compose restart process-api'" \
#     -u https://<host>/process-api/processes/som-predict-soil/execution \
#     -d '{"inputs":{"field_ids":[195],"scenarios":["S3_spec_soil_topo_clim"]}}'
#
#   # sentinel-fetch, cold: delete that parcel's masked COGs and STAC marker
#   scripts/benchmark_endpoint.sh -n 10 -l sentinel-cold -o bench.csv \
#     -c "ssh <vps> 'cd ~/Agri-SDSS && rm -f data/output/raster_cog/sentinel2_<id>_scl_* && docker compose restart process-api'" \
#     -u https://<host>/process-api/processes/sentinel-fetch/execution \
#     -f sentinel_body.json
set -eu

URL=""
BODY=""
N=10
COLD_CMD=""
READY_URL=""
OUT=""
LABEL=""
INSECURE=""
READY_TIMEOUT_S=300
REQUEST_TIMEOUT_S=700

usage() {
    sed -n '2,/^set -eu/p' "$0" | sed '$d' | sed 's/^# \{0,1\}//'
    exit "${1:-0}"
}

while getopts "u:d:f:n:c:r:o:l:kh" opt; do
    case "$opt" in
        u) URL="$OPTARG" ;;
        d) BODY="$OPTARG" ;;
        f) BODY="$(cat "$OPTARG")" ;;
        n) N="$OPTARG" ;;
        c) COLD_CMD="$OPTARG" ;;
        r) READY_URL="$OPTARG" ;;
        o) OUT="$OPTARG" ;;
        l) LABEL="$OPTARG" ;;
        k) INSECURE="-k" ;;
        h) usage 0 ;;
        *) usage 1 ;;
    esac
done
[ -n "$URL" ] || usage 1

if [ -z "$LABEL" ]; then
    if [ -n "$COLD_CMD" ]; then LABEL="cold"; else LABEL="warm"; fi
fi
if [ -z "$READY_URL" ]; then
    case "$URL" in
        */process-api/*) READY_URL="${URL%%/process-api/*}/process-api/" ;;
        *) READY_URL="$URL" ;;
    esac
fi

TIMES="$(mktemp)"
trap 'rm -f "$TIMES"' EXIT

wait_until_ready() {
    waited=0
    while :; do
        code="$(curl -s $INSECURE -o /dev/null -w '%{http_code}' --max-time 10 "$READY_URL" || true)"
        case "$code" in 2*) return 0 ;; esac
        if [ "$waited" -ge "$READY_TIMEOUT_S" ]; then
            echo "Service not ready after ${READY_TIMEOUT_S} s: $READY_URL" >&2
            exit 1
        fi
        sleep 2
        waited=$((waited + 2))
    done
}

timed_request() {
    if [ -n "$BODY" ]; then
        curl -s $INSECURE -o /dev/null -w '%{http_code} %{time_total}' \
            --max-time "$REQUEST_TIMEOUT_S" \
            -H 'Content-Type: application/json' -X POST --data "$BODY" "$URL" || true
    else
        curl -s $INSECURE -o /dev/null -w '%{http_code} %{time_total}' \
            --max-time "$REQUEST_TIMEOUT_S" "$URL" || true
    fi
}

if [ -n "$OUT" ] && [ ! -s "$OUT" ]; then
    echo "label,run,utc,http_code,time_ms" > "$OUT"
fi

i=1
while [ "$i" -le "$N" ]; do
    if [ -n "$COLD_CMD" ]; then
        sh -c "$COLD_CMD"
        wait_until_ready
    fi
    result="$(timed_request)"
    code="${result%% *}"
    ms="$(echo "${result#* }" | awk '{ printf "%.1f", $1 * 1000 }')"
    utc="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    echo "[$LABEL $i/$N] HTTP $code ${ms} ms"
    [ -n "$OUT" ] && echo "$LABEL,$i,$utc,$code,$ms" >> "$OUT"
    case "$code" in 2*) echo "$ms" >> "$TIMES" ;; esac
    i=$((i + 1))
done

sort -n "$TIMES" | awk -v label="$LABEL" -v requested="$N" '
    # Two-sided 95 % Student t quantiles for df = 1..29.
    BEGIN {
        split("12.706 4.303 3.182 2.776 2.571 2.447 2.365 2.306 2.262 2.228 " \
              "2.201 2.179 2.160 2.145 2.131 2.120 2.110 2.101 2.093 2.086 " \
              "2.080 2.074 2.069 2.064 2.060 2.056 2.052 2.048 2.045", t, " ")
    }
    { x[NR] = $1; sum += $1 }
    END {
        n = NR
        printf "%s: %d/%d successful\n", label, n, requested
        if (n == 0) exit 1
        mean = sum / n
        median = (n % 2) ? x[(n + 1) / 2] : (x[n / 2] + x[n / 2 + 1]) / 2
        for (i = 1; i <= n; i++) ss += (x[i] - mean) ^ 2
        sd = (n > 1) ? sqrt(ss / (n - 1)) : 0
        if (n >= 30) { q = 1.96; dist = "z" } else if (n > 1) { q = t[n - 1]; dist = "t" } else { q = 0; dist = "-" }
        half = q * sd / sqrt(n)
        printf "mean %.1f ms | median %.1f ms | SD %.1f ms | 95%% CI [%.1f, %.1f] (%s, n = %d)\n", \
            mean, median, sd, mean - half, mean + half, dist, n
    }'
