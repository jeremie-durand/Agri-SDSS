import { map, rasterState } from './state.js';
import { normalizeUrl } from './utils.js';

const rasterApiBaseEl = document.getElementById("rasterApiBase");
const rasterCogUrlEl = document.getElementById("rasterCogUrl");
const rasterRenderModeEl = document.getElementById("rasterRenderMode");
const rasterBandEl = document.getElementById("rasterBand");
const rasterBandREl = document.getElementById("rasterBandR");
const rasterBandGEl = document.getElementById("rasterBandG");
const rasterBandBEl = document.getElementById("rasterBandB");
const rasterColormapEl = document.getElementById("rasterColormap");
const rasterAutoStretchEl = document.getElementById("rasterAutoStretch");
const rasterStatusEl = document.getElementById("rasterStatus");
const rasterListEl = document.getElementById("rasterList");

function normalizeRasterApiBase(value) {
    const normalized = normalizeUrl(value);
    return normalized ? normalized.replace(/\/+$/, "") : null;
}

function resolveRasterUrl(path, queryParams = {}) {
    const base = normalizeRasterApiBase(rasterState.apiBaseUrl);
    if (!base) return null;
    const url = new URL(`${base}/${String(path || "").replace(/^\/+/, "")}`);
    Object.keys(queryParams).forEach((key) => {
        const value = queryParams[key];
        if (value !== undefined && value !== null && value !== "") url.searchParams.set(key, value);
    });
    return url.toString();
}

function getCogDisplayName(cogUrl) {
    try {
        const segments = new URL(cogUrl).pathname.split("/").filter(Boolean);
        return segments.length ? segments[segments.length - 1] : cogUrl;
    } catch (_) { return cogUrl; }
}

function getRasterStyleSettings() {
    const band = Number.parseInt(rasterBandEl.value, 10);
    const bandR = Number.parseInt(rasterBandREl.value, 10);
    const bandG = Number.parseInt(rasterBandGEl.value, 10);
    const bandB = Number.parseInt(rasterBandBEl.value, 10);
    const colormap = (rasterColormapEl.value || "viridis").trim();
    const renderMode = rasterRenderModeEl.value === "rgb" ? "rgb" : "single";
    return {
        renderMode,
        band: Number.isFinite(band) && band > 0 ? band : 1,
        rgbBands: [
            Number.isFinite(bandR) && bandR > 0 ? bandR : 4,
            Number.isFinite(bandG) && bandG > 0 ? bandG : 3,
            Number.isFinite(bandB) && bandB > 0 ? bandB : 2
        ],
        colormap: colormap || "viridis",
        autoStretch: !!rasterAutoStretchEl.checked
    };
}

function getRasterMinMaxFromInfo(infoData) {
    if (!infoData || !Array.isArray(infoData.band_metadata) || !infoData.band_metadata.length) return null;
    const firstBand = infoData.band_metadata[0];
    const metadata = Array.isArray(firstBand) && firstBand.length > 1 ? firstBand[1] : null;
    if (!metadata || typeof metadata !== "object") return null;
    const min = Number(metadata.STATISTICS_MINIMUM);
    const max = Number(metadata.STATISTICS_MAXIMUM);
    if (!Number.isFinite(min) || !Number.isFinite(max) || max <= min) return null;
    return { min, max };
}

function getRasterMinMaxForBand(infoData, bandIndex) {
    if (!infoData || !Array.isArray(infoData.band_metadata)) return null;
    const item = infoData.band_metadata[bandIndex - 1];
    const metadata = Array.isArray(item) && item.length > 1 ? item[1] : null;
    if (!metadata || typeof metadata !== "object") return null;
    const min = Number(metadata.STATISTICS_MINIMUM);
    const max = Number(metadata.STATISTICS_MAXIMUM);
    if (!Number.isFinite(min) || !Number.isFinite(max) || max <= min) return null;
    return { min, max };
}

function buildRasterTileJsonUrl(cogUrl, infoData, style) {
    const base = resolveRasterUrl("cog/WebMercatorQuad/tilejson.json", { url: cogUrl });
    if (!base) return null;
    const url = new URL(base);
    if (style.renderMode === "rgb") {
        style.rgbBands.forEach((band) => url.searchParams.append("bidx", String(band)));
        if (style.autoStretch && infoData) {
            style.rgbBands.forEach((band) => {
                const mm = getRasterMinMaxForBand(infoData, band);
                if (mm) url.searchParams.append("rescale", `${mm.min},${mm.max}`);
            });
        }
    } else {
        url.searchParams.set("bidx", String(style.band));
        url.searchParams.set("colormap_name", style.colormap);
        if (style.autoStretch) {
            const mm = getRasterMinMaxFromInfo(infoData);
            if (mm) url.searchParams.set("rescale", `${mm.min},${mm.max}`);
        }
    }
    return url.toString();
}

function createRasterLayerFromTileJson(tileJson, layerId) {
    const tiles = Array.isArray(tileJson && tileJson.tiles) ? tileJson.tiles : [];
    if (!tiles.length || !tiles[0]) return null;
    return {
        layer: L.tileLayer(tiles[0], { maxZoom: 22, opacity: 0.78, attribution: "Raster API" }),
        kind: "tile",
        bbox: Array.isArray(tileJson && tileJson.bounds) ? tileJson.bounds : null,
        id: layerId
    };
}

export async function setRasterLayerVisible(layerId, shouldShow, zoomToLayer = false) {
    const layerEntry = rasterState.items.find((item) => item.id === layerId);
    if (!layerEntry) { rasterStatusEl.textContent = "Raster: couche introuvable."; return; }
    const existing = rasterState.layers.get(layerId);
    if (!existing) { rasterStatusEl.textContent = "Raster: couche introuvable en memoire."; return; }
    if (!shouldShow) {
        if (map.hasLayer(existing.layer)) map.removeLayer(existing.layer);
        rasterState.visible.delete(layerId);
        return;
    }
    existing.layer.addTo(map);
    rasterState.visible.add(layerId);
    if (zoomToLayer && Array.isArray(layerEntry.bbox)) {
        let minLon, minLat, maxLon, maxLat;
        if (layerEntry.bbox.length >= 6) { minLon = layerEntry.bbox[0]; minLat = layerEntry.bbox[1]; maxLon = layerEntry.bbox[3]; maxLat = layerEntry.bbox[4]; }
        else if (layerEntry.bbox.length >= 4) { minLon = layerEntry.bbox[0]; minLat = layerEntry.bbox[1]; maxLon = layerEntry.bbox[2]; maxLat = layerEntry.bbox[3]; }
        if ([minLon, minLat, maxLon, maxLat].every((v) => Number.isFinite(v))) {
            map.fitBounds(L.latLngBounds([minLat, minLon], [maxLat, maxLon]), { padding: [20, 20], maxZoom: 13 });
        }
    }
}

export function renderRasterCollectionsList() {
    rasterListEl.innerHTML = "";
    if (!rasterState.items.length) {
        const empty = document.createElement("p");
        empty.className = "legend";
        empty.textContent = "Aucune couche raster ajoutee.";
        rasterListEl.appendChild(empty);
        return;
    }
    rasterState.items.forEach((item) => {
        const row = document.createElement("div");
        row.className = "vector-row";
        const label = document.createElement("label");
        label.className = "vector-label";
        const checkbox = document.createElement("input");
        checkbox.type = "checkbox";
        checkbox.checked = rasterState.visible.has(item.id);
        checkbox.addEventListener("change", async () => {
            try { await setRasterLayerVisible(item.id, checkbox.checked, checkbox.checked); }
            catch (error) { rasterStatusEl.textContent = `Raster: erreur (${error.message}).`; checkbox.checked = false; }
        });
        const title = document.createElement("span");
        title.className = "vector-title";
        title.textContent = item.title || item.id;
        label.appendChild(checkbox);
        label.appendChild(title);
        const zoomBtn = document.createElement("button");
        zoomBtn.type = "button";
        zoomBtn.className = "btn";
        zoomBtn.textContent = "Zoom";
        zoomBtn.style.padding = "0.28rem 0.5rem";
        zoomBtn.style.fontSize = "0.7rem";
        zoomBtn.addEventListener("click", async () => {
            try { checkbox.checked = true; await setRasterLayerVisible(item.id, true, true); }
            catch (error) { rasterStatusEl.textContent = `Raster: erreur (${error.message}).`; }
        });
        row.appendChild(label);
        row.appendChild(zoomBtn);
        rasterListEl.appendChild(row);
    });
}

export async function loadRasterCollections() {
    const apiBase = normalizeRasterApiBase(rasterApiBaseEl.value);
    if (!apiBase) { rasterStatusEl.textContent = "Raster: base URL invalide."; return; }
    const cogUrl = normalizeUrl(rasterCogUrlEl.value);
    if (!cogUrl) { rasterStatusEl.textContent = "Raster: URL COG invalide."; return; }
    const style = getRasterStyleSettings();
    const styleKey = `${style.renderMode}|${style.band}|${style.rgbBands.join("-")}|${style.colormap}|${style.autoStretch ? 1 : 0}`;
    const layerId = cogUrl;
    const existingItem = rasterState.items.find((item) => item.id === layerId);
    if (rasterState.layers.has(layerId) && existingItem && existingItem.styleKey === styleKey) {
        await setRasterLayerVisible(layerId, true, true);
        renderRasterCollectionsList();
        rasterStatusEl.textContent = `Raster: couche deja ajoutee (${getCogDisplayName(cogUrl)}).`;
        return;
    }
    if (rasterState.layers.has(layerId)) {
        const current = rasterState.layers.get(layerId);
        if (current && current.layer && map.hasLayer(current.layer)) map.removeLayer(current.layer);
        rasterState.layers.delete(layerId);
        rasterState.visible.delete(layerId);
        rasterState.items = rasterState.items.filter((item) => item.id !== layerId);
    }
    rasterStatusEl.textContent = "Raster: chargement de la couche...";
    rasterState.apiBaseUrl = apiBase;
    try {
        const infoUrl = resolveRasterUrl("cog/info", { url: cogUrl });
        const tileJsonUrl = buildRasterTileJsonUrl(cogUrl, null, style);
        if (!infoUrl || !tileJsonUrl) throw new Error("Impossible de construire les URLs Raster API.");
        const [infoResponse, tileJsonResponse] = await Promise.all([
            fetch(infoUrl, { headers: { Accept: "application/json" } }),
            fetch(tileJsonUrl, { headers: { Accept: "application/json" } })
        ]);
        if (!infoResponse.ok) throw new Error(`info HTTP ${infoResponse.status}`);
        if (!tileJsonResponse.ok) throw new Error(`tilejson HTTP ${tileJsonResponse.status}`);
        const infoData = await infoResponse.json();
        if (style.renderMode === "rgb") {
            const count = Number(infoData.count);
            if (!Number.isFinite(count) || count < 3) throw new Error("COG mono-bande: le mode RGB n'est pas disponible pour ce fichier.");
        }
        const styledTileJsonUrl = buildRasterTileJsonUrl(cogUrl, infoData, style);
        if (!styledTileJsonUrl) throw new Error("Impossible de construire les URLs Raster API.");
        const styledTileResponse = await fetch(styledTileJsonUrl, { headers: { Accept: "application/json" } });
        if (!styledTileResponse.ok) throw new Error(`tilejson HTTP ${styledTileResponse.status}`);
        const tileJsonData = await tileJsonResponse.json();
        const styledTileJsonData = await styledTileResponse.json();
        const layerEntry = createRasterLayerFromTileJson(tileJsonData, layerId);
        const styledLayerEntry = createRasterLayerFromTileJson(styledTileJsonData, layerId);
        if (!layerEntry || !styledLayerEntry) throw new Error("TileJSON invalide (aucune tuile).");
        const bbox = Array.isArray(infoData.bounds) ? infoData.bounds : layerEntry.bbox;
        rasterState.items.push({ id: layerId, title: getCogDisplayName(cogUrl), cogUrl, bbox, styleKey });
        rasterState.layers.set(layerId, styledLayerEntry);
        rasterState.offlineLayerId = layerId;
        await setRasterLayerVisible(layerId, true, true);
        renderRasterCollectionsList();
        if (style.renderMode === "rgb") {
            rasterStatusEl.textContent = `Raster: couche ajoutee (${getCogDisplayName(cogUrl)}), RGB ${style.rgbBands.join("/")}.`;
        } else {
            rasterStatusEl.textContent = `Raster: couche ajoutee (${getCogDisplayName(cogUrl)}), bande ${style.band}, palette ${style.colormap}.`;
        }
    } catch (error) {
        rasterStatusEl.textContent = `Raster: erreur de chargement (${error.message}).`;
    }
}

export async function prefetchOfflineTilesForCurrentDataset() {
    const layerId = rasterState.offlineLayerId;
    if (!layerId) { rasterStatusEl.textContent = "Raster: aucune couche raster selectionnee pour le mode hors-ligne."; return; }
    const entry = rasterState.layers.get(layerId);
    if (!entry || !entry.layer || typeof entry.layer.getTileUrl !== "function") {
        rasterStatusEl.textContent = "Raster: couche raster invalide pour le cache hors-ligne."; return;
    }
    const tileLayer = entry.layer;
    const bounds = map.getBounds();
    const currentZoom = map.getZoom();
    const minZoom = Math.max(0, Math.floor(currentZoom));
    const maxZoom = 18;
    try {
        rasterStatusEl.textContent = "Raster: prechargement des tuiles hors-ligne...";
        const tileSize = tileLayer.getTileSize ? tileLayer.getTileSize() : L.point(256, 256);
        const fetchPromises = [];
        for (let z = minZoom; z <= maxZoom; z++) {
            const nwPoint = map.project(bounds.getNorthWest(), z);
            const sePoint = map.project(bounds.getSouthEast(), z);
            const xMin = Math.floor(nwPoint.x / tileSize.x), xMax = Math.floor(sePoint.x / tileSize.x);
            const yMin = Math.floor(nwPoint.y / tileSize.y), yMax = Math.floor(sePoint.y / tileSize.y);
            for (let x = xMin; x <= xMax; x++) {
                for (let y = yMin; y <= yMax; y++) {
                    fetchPromises.push(fetch(tileLayer.getTileUrl({ x, y, z })).catch(() => null));
                }
            }
        }
        await Promise.all(fetchPromises);
        rasterStatusEl.textContent = "Raster: tuiles hors-ligne prechargees pour la zone actuelle (si le service worker est actif).";
    } catch (error) {
        rasterStatusEl.textContent = `Raster: erreur pendant le prechargement hors-ligne (${error.message}).`;
    }
}
