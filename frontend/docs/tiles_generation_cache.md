# XYZ Tiles generation and visualization in Leaflet with a Service Worker
Here is the workflow logic to cache XYZ Tiles in Leaflet using the dedicated Service Worker `leaflet-offline-sw.js`.
There is also a summary of all the cache level available in infrastructure and a summary of tile generation

## Online
```mermaid
sequenceDiagram
    autonumber
    participant User
    participant Leaflet
    participant TileServer as TileServer (TiTiler)
    participant BrowserCache as Browser HTTP Cache
    participant SW as Service Worker (leaflet-offline-sw.js)
    participant TileCache as Cache Storage (agri-sdss-raster-tiles-v1)

    User ->> Leaflet: Load map (map.html)
    Leaflet ->> SW: Request Raster API tile

    Note over Leaflet,SW: The Service Worker intercepts Raster API tile requests whose path contains `/tiles/` or `/cog/tiles/`.

    SW ->> TileServer: Forward tile request (XYZ)
    TileServer ->> TileServer: Generate tile from COG
    TileServer -->> SW: Return PNG tile
    SW ->> TileCache: Put tile response in `agri-sdss-raster-tiles-v1`
    SW -->> Leaflet: Return network response
    Leaflet ->> BrowserCache: Store tile (standard HTTP cache)
```

## Offline
```mermaid
sequenceDiagram
    autonumber
    participant User
        participant Leaflet
        participant SW as Service Worker (leaflet-offline-sw.js)
        participant TileCache as Cache Storage (agri-sdss-raster-tiles-v1)

        User ->> Leaflet: Pan / zoom map
        Leaflet ->> SW: Request Raster API tile (XYZ)

        Note over Leaflet,SW: Offline mode is handled by the Service Worker, not by the Leaflet-offline plugin.

        SW ->> TileCache: Look up tile in cache
        alt Tile found in Cache Storage
            TileCache -->> SW: Return cached tile
            SW -->> Leaflet: Serve offline tile
        else Tile not found (first visit or cache miss)
            SW ->> SW: Fallback to network (if available)
            Note over SW,Leaflet: When offline and the tile is not cached, the request fails as usual.
        end
```

## Cache Level

| Cache Level      | Location                                | What It Stores                               | Main Purpose                                                    | Retention Duration         |
| ---------------- | --------------------------------------- | -------------------------------------------- | --------------------------------------------------------------- | -------------------------- |
| **Client Cache** | Browser HTTP Cache + Cache Storage (SW) | Tiles downloaded by Leaflet / Service Worker | Speed up rendering + support offline mode for Raster API tiles  | Very long (days to months) |

## Tiles generation
The system generates raster tiles filtered to a single farm, but vector boundaries remain separate.
In practice, farm tiles are exposed via the Raster API as dataset-specific XYZ endpoints, but tiles are generated efficiently using precomputed masks (not one full dataset per farm).

1. Store farm boundaries (run once)
- Each farm's boundaries are stored in PostGIS or GeoParquet.
- These boundaries are linked to a farm ID.

2. Pre-generate raster masks (run once) 
- For each farm, a binary raster mask is created once at the resolution of the STAC assets.
- Masks are stored as COGs, ready to filter raster data per farm. (~MBs per farm)

3. Tile requests are farm-specific (run when requested)
- Each request URL includes a farm-specific dataset identifier, typically following the Raster API pattern `/tiles/{dataset}/{z}/{x}/{y}.png` or an equivalent COG-based endpoint such as `/cog/tiles/WebMercatorQuad/{z}/{x}/{y}.png?url=...`.
- The backend TileServer reads the mask for that farm and applies it to the raster tile.
- The resulting tile only contains data for the farmer’s parcel.

4. Tile visualisation in frontend
- Vector boundaries overlay the masked raster.
