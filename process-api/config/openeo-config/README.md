# OpenEO Authentication Token Storage

This directory stores the OpenEO refresh tokens for persistent authentication across container restarts.

## Files

- `refresh-tokens.json` - Contains refresh tokens for OpenEO authentication (auto-generated, **DO NOT commit**)

## How It Works

The [openEO](https://open-eo.github.io/openeo-python-client/) Python client library automatically manages refresh tokens:

1. **Initial Setup**: Run `./process-api/scripts/get_openeo_token.sh` to authenticate and store your token
2. **Automatic Loading**: The token is automatically loaded from this directory when needed
3. **Persistent Storage**: Tokens persist across Docker container restarts via volume mount

## Configuration

The location is configured via the `OPENEO_CONFIG_HOME` environment variable in `docker-compose.yml`:

```yaml
environment:
  - OPENEO_CONFIG_HOME=/app/config/openeo-config
volumes:
  - ./process-api/config/openeo-config:/app/config/openeo-config
```

## Token Location Priority

The openEO client looks for tokens in this order:

1. `$OPENEO_CONFIG_HOME/refresh-tokens.json` (this directory)
2. `~/.local/share/openeo-python-client/refresh-tokens.json` (Linux default)
3. `%APPDATA%/openeo-python-client/refresh-tokens.json` (Windows default)

## Fallback Authentication

If automatic token loading from `refresh-tokens.json` fails, the system falls back to the `OPENEO_REFRESH_TOKEN` environment variable.

**Important**: This environment variable is **NOT automatically created** by the setup script. It must be manually configured in your `.env` file as a backup authentication method:

```bash
# In .env file
OPENEO_REFRESH_TOKEN=your_refresh_token_value_here
```

To obtain the token value for manual configuration:

1. Run `./process-api/scripts/get_openeo_token.sh`
2. Copy the token from the generated `refresh-tokens.json` file
3. Paste it into your `.env` file

This fallback is useful when:

- Volume mounts are not working correctly
- Running outside Docker without persistent storage
- Debugging authentication issues

## Security Notes

- **NEVER** commit `refresh-tokens.json` to version control
- The `.gitignore` file excludes this file by default
- If compromised, re-run the setup script to obtain a new token

## Troubleshooting

If authentication fails:

1. Check that `refresh-tokens.json` exists in this directory
2. Verify file permissions allow read access
3. Re-run `./process-api/scripts/get_openeo_token.sh` to obtain a fresh token
4. Check Docker volume mounts in `docker-compose.yml`

## Official Documentation

For more information, see the [openEO Python Client Authentication Guide](https://open-eo.github.io/openeo-python-client/auth.html).
