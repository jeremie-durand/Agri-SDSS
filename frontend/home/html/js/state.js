// ── Default API endpoints (must come before state objects that reference them) ─
export const defaultStacEndpoint = `${window.location.origin}/stac-api/`;
export const defaultVectorEndpoint = `${window.location.origin}/vector-api/parquet/collections`;
export const defaultRasterApiBase = `${window.location.origin}/raster-api`;
export const defaultRasterCogUrl = "file:///data/corg_fr_siigsol_cog.tif";
export const defaultVectorCollectionId = "bdppad_v03_an_2025_s_20260504";
export const defaultView = { center: [46.8139, -71.2080], zoom: 6 };

// ── Map instance ──────────────────────────────────────────────────────────────
export const map = L.map("map", { zoomControl: false, worldCopyJump: true })
    .setView(defaultView.center, defaultView.zoom);

export const layers = {
    osm: L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
        attribution: "&copy; OpenStreetMap contributors", maxZoom: 20
    }),
    esri: L.tileLayer(
        "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        { attribution: "Tiles &copy; Esri", maxZoom: 20 }
    ),
    hot: L.tileLayer("https://{s}.tile.openstreetmap.fr/hot/{z}/{x}/{y}.png", {
        attribution: "&copy; OpenStreetMap contributors, HOT", maxZoom: 20
    })
};

L.control.scale({ imperial: false }).addTo(map);

export const stacSelectionLayer = L.featureGroup().addTo(map);
export const vectorSelectionLayer = L.featureGroup().addTo(map);

// ── Shared mutable state ──────────────────────────────────────────────────────
export const stacState = {
    rootUrl: defaultStacEndpoint, currentUrl: null, currentDoc: null, history: [], selectedItem: null
};

export const vectorState = {
    collectionsEndpoint: defaultVectorEndpoint, collections: [], layers: new Map(), visible: new Set()
};

export const rasterState = {
    apiBaseUrl: defaultRasterApiBase, items: [], layers: new Map(), visible: new Set(), offlineLayerId: null
};

export const somContext = { collectionId: null, feature: null, layer: null };
export let somChartInstance = null;
export function setSomChartInstance(v) { somChartInstance = v; }
