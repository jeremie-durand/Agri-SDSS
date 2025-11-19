#!/bin/sh
set -e
#
# --- Dynamic generation of config.js from official script ---
# https://github.com/radiantearth/stac-browser/blob/main/docker/docker-entrypoint.sh
#
safe_echo() {
    if [ -z "$1" ]; then
        echo -n "null"
    elif printf '%s\n' "$1" | grep -qE '\n.+\n$'; then
        echo -n "\`$1\`"
    else
        echo -n "'$1'"
    fi
}
#
bool() {
    case "$1" in
        true | TRUE | yes | t | True) echo -n true ;;
        false | FALSE | no | n | False) echo -n false ;;
        *) echo "Err: Unknown boolean value \"$1\"" >&2; exit 1 ;;
    esac
}
#
array() {
    if [ -z "$1" ]; then
        echo -n "[]"
    else
        case "$2" in
            string) echo -n "['$(echo "$1" | sed "s/,/', '/g")']" ;;
            *) echo -n "[$1]" ;;
        esac
    fi
}
#
object() {
    if [ -z "$1" ]; then
        echo -n "null"
    else
        echo -n "$1"
    fi
}
#
config_schema=$(cat /etc/nginx/conf.d/config.schema.json)
#
env -0 | cut -f1 -d= | tr '\0' '\n' | grep "^SB_" | {
    echo "window.STAC_BROWSER_CONFIG = {"
    while IFS='=' read -r name; do
        argname="${name#SB_}"
        value="$(eval "echo \"\$$name\"")"
        argtype="$(echo "$config_schema" | jq -r ".properties.$argname.type[0]")"
        arraytype="$(echo "$config_schema" | jq -r ".properties.$argname.items.type[0]")"
        echo -n "  $argname: "
        case "$argtype" in
            string) safe_echo "$value" ;;
            boolean) bool "$value" ;;
            integer | number | object) object "$value" ;;
            array) array "$value" "$arraytype" ;;
            *) safe_echo "$value" ;;
        esac
        echo ","
    done
    echo "}"
} > /usr/share/nginx/html/config.js
#
# --- Parting nginx with custom port ---
sed -i "s/listen .*/listen 8080;/" /etc/nginx/conf.d/default.conf
sed -i "s/listen \[::\]:.*/listen [::]:8080;/" /etc/nginx/conf.d/default.conf
#
# --- Start nginx in foreground mode ---
exec nginx -g 'daemon off;'