import { config } from './config.js';

// ── Default API endpoints (must come before state objects that reference them) ─
export const defaultStacEndpoint = `${window.location.origin}/stac-api/`;
export const defaultRasterApiBase = `${window.location.origin}/raster-api`;
export const defaultView = { center: config.mapCenter, zoom: config.mapZoom };

export const MAX_MAP_ZOOM = 19;
// Esri World Imagery answers level 19 with "Map data not yet available" placeholders over parts of rural Quebec.
const ESRI_MAX_NATIVE_ZOOM = 18;

// ── Map instance ──────────────────────────────────────────────────────────────
export const map = L.map("map", {
    zoomControl: false,
    worldCopyJump: true,
    maxZoom: MAX_MAP_ZOOM,
    zoomSnap: 0.25,
    zoomDelta: 0.5,
    wheelPxPerZoomLevel: 120
})
    .setView(defaultView.center, defaultView.zoom);

export const layers = {
    osm: L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
        attribution: "&copy; OpenStreetMap contributors", maxZoom: MAX_MAP_ZOOM, maxNativeZoom: MAX_MAP_ZOOM
    }),
    esri: L.tileLayer(
        "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        { attribution: "Tiles &copy; Esri", maxZoom: MAX_MAP_ZOOM, maxNativeZoom: ESRI_MAX_NATIVE_ZOOM }
    ),
    hot: L.tileLayer("https://{s}.tile.openstreetmap.fr/hot/{z}/{x}/{y}.png", {
        attribution: "&copy; OpenStreetMap contributors, HOT", maxZoom: MAX_MAP_ZOOM, maxNativeZoom: MAX_MAP_ZOOM
    })
};

L.control.scale({ imperial: false }).addTo(map);

export const stacSelectionLayer = L.featureGroup().addTo(map);

// ── Shared mutable state ──────────────────────────────────────────────────────
export const stacState = {
    rootUrl: defaultStacEndpoint, currentUrl: null, currentDoc: null, history: [], selectedItem: null
};

export const vectorState = {
    collections: [], layers: new Map()
};

export const rasterState = {
    apiBaseUrl: defaultRasterApiBase, items: [], layers: new Map(), visible: new Set(), offlineLayerId: null
};

export const somContext = { collectionId: null, feature: null, layer: null };
export let somChartInstance = null;
export function setSomChartInstance(v) { somChartInstance = v; }
