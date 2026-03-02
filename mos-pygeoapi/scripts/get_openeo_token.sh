#!/bin/bash
set -e
#
echo "============================================================"
echo "OpenEO Refresh Token Setup (Docker)"
echo "============================================================"
echo ""
echo "This script will:"
echo "  1. Run authentication in Docker"
echo "  2. Show you a URL to open in your browser"
echo "  3. Extract and store the refresh token"
echo "  4. Save it to persistent storage"
echo ""
echo "============================================================"
echo ""
#
# Navigate to project root (2 levels up from pygeoapi/scripts)
cd "$(dirname "$0")/../.."
#
echo "Starting authentication process..."
echo ""
echo "============================================================"
echo "IMPORTANT: Browser Authentication Required"
echo "============================================================"
echo ""
echo "A URL will appear below. You need to:"
echo "  1. Copy the URL"
echo "  2. Open it in your browser"
echo "  3. Log in to Copernicus Data Space"
echo "  4. Return here and wait for completion"
echo ""
echo "============================================================"
echo ""
read -p "Press ENTER when ready to continue..."
echo ""
## Create a temporary file to store the output
TEMP_OUTPUT=$(mktemp)
#
# Run authentication and token extraction in one Docker container
echo "Connecting to OpenEO..."
docker compose run --rm mos-pygeoapi python3 -c "
import openeo
import json
import os
from pathlib import Path
import sys

# Step 1: Authenticate
print('Connecting to OpenEO Copernicus Data Space...', flush=True)
try:
    conn = openeo.connect('openeo.dataspace.copernicus.eu')
    print('Connected successfully!', flush=True)
except Exception as e:
    print(f'Connection failed: {e}', flush=True)
    sys.exit(1)

print('', flush=True)
print('Starting authentication...', flush=True)
print('', flush=True)
print('=' * 60, flush=True)
print('COPY THE URL BELOW AND OPEN IT IN YOUR BROWSER (May take a moment)', flush=True)
print('=' * 60, flush=True)
print('', flush=True)

try:
    # Store refresh token for automatic loading (store_refresh_token=True is default)
    conn.authenticate_oidc(store_refresh_token=True)
    print('', flush=True)
    print('=' * 60, flush=True)
    print('✓ Authentication successful!', flush=True)
    print('=' * 60, flush=True)
except Exception as e:
    print(f'Authentication failed: {e}', flush=True)
    sys.exit(1)

# Step 2: Extract token from stored location
print('', flush=True)
print('Extracting refresh token from persistent storage...', flush=True)

# Check OPENEO_CONFIG_HOME first, then fall back to default location
config_home = os.getenv('OPENEO_CONFIG_HOME')
if config_home:
    token_file = Path(config_home) / 'refresh-tokens.json'
else:
    token_file = Path.home() / '.local/share/openeo-python-client/refresh-tokens.json'
if not token_file.exists():
    print(f'Token file not found at: {token_file}', flush=True)
    sys.exit(1)

try:
    token_content = token_file.read_text()
    tokens = json.loads(token_content)
    
    if not tokens:
        print('No tokens found in file', flush=True)
        sys.exit(1)
    
    # The structure is: {issuer: {client_id: {date, refresh_token}}}
    # Get the first issuer
    issuer_data = list(tokens.values())[0]
    # Get the first client under that issuer
    client_data = list(issuer_data.values())[0]
    # Get the refresh_token
    refresh_token = client_data['refresh_token']
    
    print(f'Token extracted successfully (length: {len(refresh_token)})', flush=True)
    print('EXTRACTION_SUCCESS', flush=True)
    print('TOKEN_START', flush=True)
    print(refresh_token, flush=True)
    print('TOKEN_END', flush=True)
except Exception as e:
    print(f'Token extraction failed: {e}', flush=True)
    import traceback
    traceback.print_exc()
    sys.exit(1)
" 2>&1 | tee "$TEMP_OUTPUT"
#
# Extract token from output and remove ALL whitespace/newlines
if grep -q "EXTRACTION_SUCCESS" "$TEMP_OUTPUT"; then
    TOKEN=$(sed -n '/TOKEN_START/,/TOKEN_END/p' "$TEMP_OUTPUT" | grep -v "TOKEN_START\|TOKEN_END" | tr -d '\n\r\t ' | tr -d '[:space:]')
else
    TOKEN=""
fi
# Clean up
rm -f "$TEMP_OUTPUT"
if [ -z "$TOKEN" ] || [[ "$TOKEN" == ERROR* ]]; then
    echo ""
    echo "✗ Failed to extract token"
    echo ""
    echo "Alternative: Get your token manually from:"
    echo "  1. Go to: https://shapps.dataspace.copernicus.eu/dashboard/"
    echo "  2. Log in with your Copernicus account"
    echo "  3. Click your username → Settings → Get Refresh Token"
    echo "  4. Copy the token and add to .env:"
    echo "     OPENEO_REFRESH_TOKEN=your_token_here"
    echo ""
    exit 1
fi
#
echo ""
echo "============================================================"
echo "SUCCESS! Token extracted (length: ${#TOKEN})"
echo "============================================================"
echo ""
echo "The refresh token is now stored in: ./pygeoapi/config/openeo-config/refresh-tokens.json"
echo "This token will be automatically loaded by the openEO Python client."
echo ""
echo "OPTIONAL: For fallback support, copy this line to your .env file:"
echo ""
echo "OPENEO_REFRESH_TOKEN=$TOKEN"
echo ""
echo "============================================================"
echo ""
echo "Next steps:"
echo ""
echo "  1. The token is already stored and will persist across restarts"
echo ""
echo "  2. (Optional) Copy the line above to .env for fallback support"
echo ""
echo "  3. Reload pygeoapi to apply changes:"
echo "     docker compose down && docker compose up -d"
echo ""
echo "  4. Test the sentinel-fetch process:"
echo "     curl -X POST http://localhost:5000/processes/sentinel-fetch/execution \\"
echo "       -H 'Content-Type: application/json' \\"
echo "       -d '{\"inputs\": {"
echo "         \"farm_id\": 75,"
echo "         \"temporal_extent\": [\"2024-06-01\", \"2024-08-31\"],"
echo "         \"output_products\": [\"ndvi\"]"
echo "       }}'"
echo ""
echo "============================================================"
