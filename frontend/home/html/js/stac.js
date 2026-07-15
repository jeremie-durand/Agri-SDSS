import { map, stacState, stacSelectionLayer } from './state.js';
import { normalizeUrl } from './utils.js';
import { clearMetadata, addMetadataSection, addMetadataRow, addMetadataRowsFromObject, renderAssetsMetadata, renderLinksMetadata } from './metadata.js';

const stacStatusEl = document.getElementById("stacStatus");
const stacCurrentEl = document.getElementById("stacCurrent");
const stacListEl = document.getElementById("stacList");

function absoluteStacUrl(href) {
    if (!href) return null;
    try {
        return new URL(href, stacState.currentUrl || stacState.rootUrl || window.location.origin).toString();
    } catch (_) { return null; }
}

export function clearStacSelection() {
    stacSelectionLayer.clearLayers();
}

function renderItemMetadata(feature) {
    const metadataStatusEl = document.getElementById("metadataStatus");
    const metadataBoxEl = document.getElementById("metadataBox");
    if (!feature || feature.type !== "Feature") { clearMetadata(); return; }
    const props = feature.properties || {};
    const assets = feature.assets || {};
    const links = feature.links || [];
    metadataStatusEl.textContent = `Item selectionne: ${feature.id || "sans identifiant"}`;
    metadataBoxEl.innerHTML = "";
    addMetadataSection("Item");
    addMetadataRow("type", feature.type);
    addMetadataRow("id", feature.id);
    addMetadataRow("collection", feature.collection || props.collection);
    addMetadataRow("stac_version", feature.stac_version);
    addMetadataRow("bbox", Array.isArray(feature.bbox) ? feature.bbox.map((v) => Number(v).toFixed(4)).join(", ") : null);
    addMetadataRow("geometry.type", feature.geometry && feature.geometry.type ? feature.geometry.type : null);
    addMetadataRowsFromObject(props, { title: "Properties", maxEntries: 150 });
    renderAssetsMetadata(assets);
    renderLinksMetadata(links);
}

export function fitBbox(bbox) {
    if (!Array.isArray(bbox)) return;
    let minLon, minLat, maxLon, maxLat;
    if (bbox.length >= 6) { minLon = bbox[0]; minLat = bbox[1]; maxLon = bbox[3]; maxLat = bbox[4]; }
    else if (bbox.length >= 4) { minLon = bbox[0]; minLat = bbox[1]; maxLon = bbox[2]; maxLat = bbox[3]; }
    else return;
    const bounds = L.latLngBounds([minLat, minLon], [maxLat, maxLon]);
    const rect = L.rectangle(bounds, { color: "#22d3ee", weight: 2, fillOpacity: 0.06 });
    stacSelectionLayer.addLayer(rect);
    map.fitBounds(bounds, { padding: [20, 20], maxZoom: 12 });
}

export function zoomToStacObject(obj) {
    clearStacSelection();
    renderItemMetadata(obj);
    stacState.selectedItem = (obj && obj.type === "Feature") ? obj : null;
    if (!obj || typeof obj !== "object") return;
    if (obj.type === "Feature" && obj.geometry) {
        const geo = L.geoJSON(obj, { style: { color: "#22d3ee", weight: 2, fillOpacity: 0.15 } });
        stacSelectionLayer.addLayer(geo);
        const bounds = geo.getBounds();
        if (bounds.isValid()) map.fitBounds(bounds, { padding: [20, 20], maxZoom: 12 });
        return;
    }
    if (Array.isArray(obj.bbox)) fitBbox(obj.bbox);
}

export function stacLabel(entry) {
    if (entry.title) return entry.title;
    if (entry.id) return entry.id;
    if (entry.rel) {
        if (entry.rel === "data") return "Collections";
        if (entry.rel === "service-doc") return "Documentation API";
        if (entry.rel === "service-desc") return "Description OpenAPI";
        if (entry.rel === "http://www.opengis.net/def/rel/ogc/1.0/queryables") return "Queryables";
        return `${entry.rel}: ${entry.href || "(sans href)"}`;
    }
    return entry.href || "Ressource";
}

export function renderStacList(doc) {
    stacListEl.innerHTML = "";
    if (!doc || typeof doc !== "object") { stacCurrentEl.textContent = ""; clearMetadata(); return; }
    if (doc.type === "Feature") renderItemMetadata(doc);
    else clearMetadata();

    stacCurrentEl.textContent = `Actuel: ${doc.type || "document"} - ${doc.title || doc.id || "Sans titre"}`;

    const entries = [];
    const links = Array.isArray(doc.links) ? doc.links : [];
    const isFeatureDocument = doc.type === "Feature";
    const hasCollections = Array.isArray(doc.collections) && doc.collections.length > 0;
    const hasFeatures = Array.isArray(doc.features) && doc.features.length > 0;
    const hasConcreteResources = hasCollections || hasFeatures;
    const isRootCatalog = doc.type === "Catalog";
    const allowedRels = new Set(["child","children","collection","item","items","self","root","parent","next","prev","data","search","conformance","service-doc","service-desc","http://www.opengis.net/def/rel/ogc/1.0/queryables"]);

    links.forEach((link) => {
        if (!link || !link.href || !link.rel) return;
        if (isFeatureDocument) return;
        if (isRootCatalog && link.rel !== "data") return;
        if (hasConcreteResources && ["self","root","parent","collection","item","items","child","children","next","prev","data"].includes(link.rel)) return;
        if (allowedRels.has(link.rel)) entries.push({ kind: "link", rel: link.rel, title: link.title || null, href: link.href });
    });

    if (Array.isArray(doc.collections)) {
        doc.collections.forEach((collection) => {
            if (!collection) return;
            const selfLink = Array.isArray(collection.links) ? collection.links.find((l) => l.rel === "self" && l.href) : null;
            const itemsLink = Array.isArray(collection.links) ? collection.links.find((l) => l.rel === "items" && l.href) : null;
            entries.push({
                kind: "collection",
                title: collection.title || collection.id || "Collection",
                id: collection.id,
                href: itemsLink ? itemsLink.href : (selfLink ? selfLink.href : null),
                data: collection
            });
        });
    }

    if (Array.isArray(doc.features)) {
        doc.features.slice(0, 100).forEach((feature) => {
            if (!feature) return;
            const selfLink = Array.isArray(feature.links) ? feature.links.find((l) => l.rel === "self" && l.href) : null;
            entries.push({ kind: "feature", title: feature.id || "Item", id: feature.id, href: selfLink ? selfLink.href : null, data: feature });
        });
    }

    if (!entries.length) {
        const empty = document.createElement("p");
        empty.className = "legend";
        empty.textContent = "Aucune ressource navigable detectee.";
        stacListEl.appendChild(empty);
        return;
    }

    const countInfo = document.createElement("p");
    countInfo.className = "legend";
    countInfo.textContent = `${entries.length} ressource(s) disponible(s).`;
    stacListEl.appendChild(countInfo);

    entries.forEach((entry) => {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "stac-item";
        button.textContent = stacLabel(entry);
        button.addEventListener("click", async () => {
            if (entry.data) zoomToStacObject(entry.data);
            const targetUrl = absoluteStacUrl(entry.href);
            if (targetUrl) await loadStacDocument(targetUrl, true);
        });
        stacListEl.appendChild(button);
    });
}

export async function loadStacDocument(url, pushHistory) {
    const targetUrl = normalizeUrl(url);
    if (!targetUrl) { stacStatusEl.textContent = "STAC: URL invalide."; return; }
    stacStatusEl.textContent = "STAC: chargement...";
    try {
        const response = await fetch(targetUrl, { headers: { Accept: "application/geo+json,application/json" } });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const documentData = await response.json();
        if (pushHistory && stacState.currentUrl) stacState.history.push(stacState.currentUrl);
        stacState.currentUrl = targetUrl;
        stacState.currentDoc = documentData;
        renderStacList(documentData);
        stacStatusEl.textContent = `STAC: connecte (${response.status}).`;
    } catch (error) {
        stacStatusEl.textContent = `STAC: erreur de connexion (${error.message}).`;
    }
}
