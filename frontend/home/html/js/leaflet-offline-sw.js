/*
 * Simple service worker for the Leaflet map.
 *
 * Purpose:
 * - Cache Raster API (XYZ) tiles during prefetch
 *   and during normal navigation.
 * - Serve these tiles from the cache when the network
 *   is not available anymore, to enable a basic offline mode.
 */

const TILE_CACHE_NAME = "agri-sdss-raster-tiles-v2";
const PREV_CACHE_NAMES = ["agri-sdss-raster-tiles-v1"];

self.addEventListener("install", () => {
    self.skipWaiting();
});

self.addEventListener("activate", (event) => {
    // Delete stale caches from previous SW versions.
    event.waitUntil(
        Promise.all(PREV_CACHE_NAMES.map((name) => caches.delete(name)))
    );
    // Do NOT call clients.claim() — avoids triggering controllerchange
    // on active pages, which can cause reload loops on SW updates.
});

self.addEventListener("fetch", (event) => {
    const request = event.request;
    const url = new URL(request.url);

    // Only cache Raster API tiles (/raster-api/). Explicitly exclude /vector-api/
    // so MVT vector tiles always bypass this SW and go directly to nginx.
    const isRasterTile = url.pathname.startsWith("/raster-api/")
        && (url.pathname.includes("/tiles/") || url.pathname.includes("/cog/tiles/"));
    if (!isRasterTile || request.method !== "GET") {
        return;
    }

    event.respondWith(
        caches.open(TILE_CACHE_NAME).then(async (cache) => {
            const cached = await cache.match(request);
            if (cached) {
                return cached;
            }

            try {
                const response = await fetch(request);
                if (response.ok) {
                    // Clone before caching so we don't consume the main response.
                    cache.put(request, response.clone());
                }
                return response;
            } catch (_error) {
                return cached || Response.error();
            }
        })
    );
});
