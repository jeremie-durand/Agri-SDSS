# OpenEO Authentication Setup Guide

This guide shows you how to set up authentication for accessing Sentinel-2 data through OpenEO.

## Why Do I Need This?

The `sentinel-fetch` process uses OpenEO Copernicus Data Space backend to fetch and process Sentinel-2 satellite imagery. This requires authentication with a refresh token.

## One-Time Setup

### Step 1: Get a Copernicus Account

If you don't have one already:
1. Go to https://dataspace.copernicus.eu/
2. Click "Register"
3. Create your free account

### Step 2: Run the Token Setup Script

From your project root directory:

```bash
./mos-pygeoapi/scripts/get_openeo_token.sh
```

**What this does:**
1. Shows you a URL to open in your browser
2. You log in with your Copernicus credentials
3. The script extracts your refresh token

### Step 3: Reload pygeoapi

**Important**: `docker compose restart` does NOT reload `.env` variables. You must use:

```bash
docker compose down && docker compose up
```

### Step 4: Test It

```bash
curl -X POST "http://localhost:5000/processes/sentinel-fetch/execution" \
  -H "Content-Type: application/json" \
  -d '{
    "inputs": {
      "farm_id": 75,
      "temporal_extent": ["2024-06-01", "2024-08-31"],
      "output_products": ["ndvi"],
      "aggregation_method": "max",
      "cloud_cover_max": 15
    }
  }'
```

**Done!** You're all set.

## Troubleshooting

### Error: "Failed to retrieve access token... invalid_grant"
- Your refresh token expired (tokens last ~30 days)
- Run the setup script again to get a new token

### Script hangs after entering URL
- Make sure you actually opened the URL in your browser
- Make sure you completed the login process
- Check that you returned to the terminal

### "Permission denied" when running script
```bash
chmod +x mos-pygeoapi/scripts/get_openeo_token.sh
./mos-pygeoapi/scripts/get_openeo_token.sh
```

## How Often Do I Need to Do This?

**Once!** The refresh token is automatically stored in `./mos-pygeoapi/config/openeo-config/refresh-tokens.json` and persists across:
- Docker restarts
- Container rebuilds
- System reboots

You only need to refresh it if:
- The token expires (~30 days typically, but can be longer)
- Authentication fails and the token is not found in any of the fallback locations (see [priority order](../config/openeo-config/README.md#token-location-priority))
