# stac-browser

STAC catalog explorer UI. Official [radiantearth/stac-browser](https://github.com/radiantearth/stac-browser) image with a MOS-GIS configuration layered on top — browses collections and items from the STAC API and renders COG previews as map tiles via the raster-api.

**Port**: 8085 (direct) | **Requires**: `stac-api` running; `raster-api` for tile previews

Served at `/stac/` through the `home` frontend (single origin, shared nav bar injected — see [frontend/home/README.md](../home/README.md)).

## Start

```bash
docker compose up -d stac-browser
```

## Key behaviours

- **Proxy-based URLs** — the catalog URL points at the nginx proxy (`https://${HOST_URL}/mos-stac/`), not the stac-api port directly; tile previews go through `/mos-raster/`. No CORS configuration needed.
- **Bilingual FR/EN** — `preprocessSTAC` swaps collection titles and descriptions based on the `mos-lang` localStorage key set by the shared nav bar.
- **COG rendering** — `buildTileUrlTemplate` sends COG assets to the raster-api tile endpoint for interactive map display.
- **Config is a startup template** — `config.js` is expanded by `entrypoint.sh` with `envsubst` (`${HOST_URL}`, `${STAC_BROWSER_PORT}`) every time the container starts. Edits made inside a running container are overwritten on restart — always change `config/browser_config.js` and rebuild.

## Configuration

`config/browser_config.js` — catalog URL, locales, tile URL template, bilingual title mapping

| Variable | Description |
| --- | --- |
| `HOST_URL` | Public host name substituted into catalog and tile URLs |
| `STAC_BROWSER_PORT` | Host-side port for direct access |

After changing the config:

```bash
docker compose up -d stac-browser --build
```

## Troubleshooting

```bash
# Collections not loading — check the STAC API and the generated config
curl http://<host>:8081/collections
docker compose exec stac-browser cat /usr/share/nginx/html/config.js

# Tiles not rendering — check the raster-api
docker compose logs raster-api
```

## Docs

→ [Official STAC Browser repository](https://github.com/radiantearth/stac-browser)
→ [Official configuration guide](https://github.com/radiantearth/stac-browser/blob/main/docs/options.md)
→ [STAC specification](https://stacspec.org/)
