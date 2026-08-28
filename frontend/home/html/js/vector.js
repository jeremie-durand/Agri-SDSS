import { map, vectorState, vectorSelectionLayer, somContext } from './state.js';
import { normalizeUrl, getColorForCollection } from './utils.js';
import { openSomModal } from './som.js';
import { showHoverHint, hideHoverHint } from './hover-hint.js';

function _tL() { return (window.T && window.T[window.lang]) || {}; }
// import { sendFeatureContext } from './chat.js'; // disabled: farm context auto-population

const vectorEndpointEl = document.getElementById("vectorEndpoint");
const vectorStatusEl = document.getElementById("vectorStatus");
const vectorListEl = document.getElementById("vectorList");


function absoluteVectorUrl(href, baseUrl) {
    if (!href) return null;
    try { return new URL(href, baseUrl || vectorState.collectionsEndpoint || window.location.origin).toString(); }
    catch (_) { return null; }
}

function getCollectionItemsUrl(collection) {
    if (!collection) return null;
    const links = Array.isArray(collection.links) ? collection.links : [];
    const itemsLink = links.find((l) => l && l.rel === "items" && l.href);
    if (itemsLink) return absoluteVectorUrl(itemsLink.href, vectorState.collectionsEndpoint);
    const selfLink = links.find((l) => l && l.rel === "self" && l.href);
    if (selfLink) {
        const resolved = absoluteVectorUrl(selfLink.href, vectorState.collectionsEndpoint);
        return resolved ? `${resolved.replace(/\/+$/, "")}/items` : null;
    }
    if (!collection.id) return null;
    return `${vectorState.collectionsEndpoint.replace(/\/+$/, "")}/${encodeURIComponent(collection.id)}/items`;
}

async function fetchCollectionFeatures(itemsUrl) {
    const merged = [];
    let nextUrl = itemsUrl;
    const maxFeatures = 10000;
    while (nextUrl && merged.length < maxFeatures) {
        const pagedUrl = new URL(nextUrl, window.location.origin);
        if (!pagedUrl.searchParams.has("f")) pagedUrl.searchParams.set("f", "json");
        pagedUrl.searchParams.set("limit", "2000");
        const response = await fetch(pagedUrl.toString(), { headers: { Accept: "application/geo+json,application/json" } });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const data = await response.json();
        const features = Array.isArray(data.features) ? data.features : [];
        merged.push(...features);
        const links = Array.isArray(data.links) ? data.links : [];
        const nextLink = links.find((l) => l && l.rel === "next" && l.href);
        nextUrl = nextLink ? absoluteVectorUrl(nextLink.href, pagedUrl.toString()) : null;
    }
    return { type: "FeatureCollection", features: merged.slice(0, maxFeatures) };
}

function buildVectorLayer(collectionId, featureCollection) {
    const color = getColorForCollection(collectionId);
    return L.geoJSON(featureCollection, {
        style: { color, weight: 1.6, fillColor: color, fillOpacity: 0.14 },
        pointToLayer: (_feature, latlng) => L.circleMarker(latlng, { radius: 5, color, weight: 1.4, fillColor: color, fillOpacity: 0.7 }),
        onEachFeature: (feature, layer) => {
            layer.on('click', function() {
                var center = null;
                try {
                    if (layer.getBounds) { var b = layer.getBounds(); center = { lat: b.getCenter().lat, lon: b.getCenter().lng }; }
                    else if (layer.getLatLng) { var ll = layer.getLatLng(); center = { lat: ll.lat, lon: ll.lng }; }
                } catch (_) {}
                // sendFeatureContext(collectionId, feature, center);
                openSomModal(collectionId, feature, layer);
            });
        }
    });
}

function buildVectorTileLayer(collectionId, color) {
    const postgisId = 'public.' + collectionId;
    const tileUrl = '/vector-api/postgis/collections/' + encodeURIComponent(postgisId) + '/tiles/WebMercatorQuad/{z}/{x}/{y}?limit={limit}';
    const vtLayer = L.vectorGrid.protobuf(tileUrl, {
        maxRequests: 4,
        updateInterval: 50,
        maxNativeZoom: 15,
        limit: 500,
        vectorTileLayerStyles: { 'default': { color, weight: 1.6, fill: true, fillColor: color, fillOpacity: 0.14 } },
        interactive: true,
        getFeatureId: function(f) { return f.properties.idanpar || f.properties.idpar || f.properties.gid; }
    });
    // Below z9 a tile spans a whole region/the whole province and can hold 100k+
    // parcels — no per-tile limit shows "every" parcel there without multi-MB
    // tiles, so that range keeps the default. z9-z11ish is where a flat limit=500
    // was silently dropping most parcels (unordered SQL LIMIT, no ORDER BY) while
    // still being small enough that tipg's own 10000-per-tile ceiling covers it.
    const _getVectorTile = vtLayer._getVectorTilePromise.bind(vtLayer);
    vtLayer._getVectorTilePromise = function(coords) {
        this.options.limit = coords.z >= 9 ? 10000 : 500;
        return _getVectorTile(coords);
    };
    vtLayer.on('click', function(e) {
        L.DomEvent.stopPropagation(e);
        const center = { lat: e.latlng.lat, lon: e.latlng.lng };
        const props = e.layer.properties || {};
        const featureId = props.idanpar || props.idpar || props.gid || null;

        // Parcel bounds from tile layer (used for form extent + COG statistics geometry)
        let parcelBounds = null;
        try { parcelBounds = e.layer.getBounds && e.layer.getBounds(); } catch(_) {}
        if (!parcelBounds) parcelBounds = L.latLng(e.latlng).toBounds(500);

        const parcelGeom = { type: 'Polygon', coordinates: [[[parcelBounds.getWest(), parcelBounds.getSouth()], [parcelBounds.getEast(), parcelBounds.getSouth()], [parcelBounds.getEast(), parcelBounds.getNorth()], [parcelBounds.getWest(), parcelBounds.getNorth()], [parcelBounds.getWest(), parcelBounds.getSouth()]]] };
        const feature = { id: featureId, properties: props, type: 'Feature', geometry: parcelGeom };
        const layer = { getBounds: function() { return parcelBounds; } };

        // sendFeatureContext(collectionId, feature, center);
        openSomModal(collectionId, feature, layer);

        // Background: fetch exact parcel geometry from Parquet and silently update somContext
        const searchPad = 0.0002;
        const clickBbox = [e.latlng.lng - searchPad, e.latlng.lat - searchPad, e.latlng.lng + searchPad, e.latlng.lat + searchPad].join(',');
        const snap = feature;
        fetch('/vector-api/parquet/collections/' + collectionId + '/items?bbox=' + clickBbox + '&limit=10&f=json')
            .then(function(r) { return r.ok ? r.json() : null; })
            .then(function(fc) {
                var areaEl = document.getElementById('somArea');
                var areaStatus = document.getElementById('somAreaStatus');
                if (!fc) {
                    if (areaStatus) areaStatus.textContent = '';
                    return;
                }
                const pt = turf.point([e.latlng.lng, e.latlng.lat]);
                const match = (fc.features || []).find(function(f) {
                    try { return turf.booleanPointInPolygon(pt, f); } catch(_) { return false; }
                }) || (fc.features || [])[0];
                if (match && somContext.feature === snap) {
                    somContext.feature = match;
                    // sendFeatureContext(collectionId, match, center);
                    if (areaEl && !areaEl.value.trim()) {
                        var mp = match.properties || {};
                        var ha = mp.superficie_ha != null ? mp.superficie_ha
                            : mp.area_ha != null ? mp.area_ha
                            : mp.hectares != null ? mp.hectares
                            : mp.suphec != null ? mp.suphec
                            : mp.sup != null ? mp.sup / 10000
                            : null;
                        if (ha == null && match.geometry) {
                            try { ha = turf.area(match) / 10000; } catch(_) {}
                        }
                        if (ha != null) areaEl.value = (+ha).toFixed(1);
                    }
                }
                if (areaStatus) areaStatus.textContent = '';
            })
            .catch(function() {
                var areaStatus = document.getElementById('somAreaStatus');
                if (areaStatus) areaStatus.textContent = '';
            });
    });
    vtLayer.on('mouseover', function(e) {
        showHoverHint(e.originalEvent.clientX, e.originalEvent.clientY, _tL()['bdppad-hover-hint'] || 'Click to explore this parcel');
    });
    vtLayer.on('mousemove', function(e) {
        showHoverHint(e.originalEvent.clientX, e.originalEvent.clientY, _tL()['bdppad-hover-hint'] || 'Click to explore this parcel');
    });
    vtLayer.on('mouseout', hideHoverHint);
    vtLayer._isTileLayer = true;
    return vtLayer;
}

function _setVectorStatus(msg) { if (vectorStatusEl) vectorStatusEl.textContent = msg; }

export async function setVectorCollectionVisible(collectionId, shouldShow, zoomToLayer = false, skipTileProbe = false) {
    const collection = vectorState.collections.find((item) => item.id === collectionId);
    if (!collection) { _setVectorStatus(_tL()['vector-collection-missing'] || 'Vector : collection introuvable.'); return; }

    if (!shouldShow) {
        const existingLayer = vectorState.layers.get(collectionId);
        if (existingLayer) map.removeLayer(existingLayer);
        vectorState.visible.delete(collectionId);
        return;
    }

    let layer = vectorState.layers.get(collectionId);
    if (!layer) {
        _setVectorStatus(`${_tL()['vector-loading-collection'] || 'Vector : chargement'} ${collectionId}…`);
        const itemsUrl = getCollectionItemsUrl(collection);
        if (!itemsUrl) { _setVectorStatus(`${_tL()['vector-items-url-missing'] || 'Vector : URL items introuvable pour'} ${collectionId}.`); return; }

        const postgisId = 'public.' + collectionId;
        const tileJsonUrl = '/vector-api/postgis/collections/' + encodeURIComponent(postgisId) + '/tiles/WebMercatorQuad/tilejson.json';
        let useTiles = skipTileProbe;
        if (!useTiles) {
            try { const probe = await fetch(tileJsonUrl); useTiles = probe.ok; } catch(_) {}
        }

        const color = getColorForCollection(collectionId);
        if (useTiles) {
            layer = buildVectorTileLayer(collectionId, color);
            _setVectorStatus(`Vector: ${collectionId} (${_tL()['vector-mvt'] || 'tuiles MVT'}).`);
        } else {
            const featureCollection = await fetchCollectionFeatures(itemsUrl);
            layer = buildVectorLayer(collectionId, featureCollection);
            _setVectorStatus(`Vector: ${collectionId} ${_tL()['vector-loaded'] || 'chargé'} (${featureCollection.features.length} ${_tL()['vector-features'] || 'entité(s)'}).`);
        }
        vectorState.layers.set(collectionId, layer);
    }

    if (layer._isTileLayer) { layer.addTo(map); }
    else { layer.addTo(vectorSelectionLayer); }
    vectorState.visible.add(collectionId);

    if (zoomToLayer) {
        if (typeof layer.getBounds === "function") {
            const bounds = layer.getBounds();
            if (bounds && bounds.isValid()) map.fitBounds(bounds, { padding: [20, 20], maxZoom: 13 });
        } else {
            const collectionBbox = collection && collection.extent && collection.extent.spatial
                && Array.isArray(collection.extent.spatial.bbox) && Array.isArray(collection.extent.spatial.bbox[0])
                ? collection.extent.spatial.bbox[0] : null;
            if (collectionBbox) {
                let minLon, minLat, maxLon, maxLat;
                if (collectionBbox.length >= 6) { minLon = collectionBbox[0]; minLat = collectionBbox[1]; maxLon = collectionBbox[3]; maxLat = collectionBbox[4]; }
                else if (collectionBbox.length >= 4) { minLon = collectionBbox[0]; minLat = collectionBbox[1]; maxLon = collectionBbox[2]; maxLat = collectionBbox[3]; }
                if ([minLon, minLat, maxLon, maxLat].every((v) => Number.isFinite(v))) {
                    map.fitBounds(L.latLngBounds([minLat, minLon], [maxLat, maxLon]), { padding: [20, 20], maxZoom: 13 });
                }
            }
        }
    }
}

export function renderVectorCollectionsList() {
    vectorListEl.innerHTML = "";
    if (!vectorState.collections.length) {
        const empty = document.createElement("p");
        empty.className = "legend";
        empty.textContent = _tL()['vector-none'] || "Aucune collection vectorielle.";
        vectorListEl.appendChild(empty);
        return;
    }
    vectorState.collections.forEach((collection) => {
        const row = document.createElement("div");
        row.className = "vector-row";
        const label = document.createElement("label");
        label.className = "vector-label";
        const checkbox = document.createElement("input");
        checkbox.type = "checkbox";
        checkbox.checked = vectorState.visible.has(collection.id);
        checkbox.addEventListener("change", async () => {
            try { await setVectorCollectionVisible(collection.id, checkbox.checked, checkbox.checked); }
            catch (error) { vectorStatusEl.textContent = `Vector: ${_tL()['vector-error'] || 'erreur'} (${error.message}).`; checkbox.checked = false; }
        });
        const title = document.createElement("span");
        title.className = "vector-title";
        title.textContent = collection.title || collection.id;
        label.appendChild(checkbox);
        label.appendChild(title);
        const zoomBtn = document.createElement("button");
        zoomBtn.type = "button";
        zoomBtn.className = "btn";
        zoomBtn.textContent = "Zoom";
        zoomBtn.style.padding = "0.28rem 0.5rem";
        zoomBtn.style.fontSize = "0.7rem";
        zoomBtn.addEventListener("click", async () => {
            try { checkbox.checked = true; await setVectorCollectionVisible(collection.id, true, true); }
            catch (error) { vectorStatusEl.textContent = `Vector: ${_tL()['vector-error'] || 'erreur'} (${error.message}).`; }
        });
        row.appendChild(label);
        row.appendChild(zoomBtn);
        vectorListEl.appendChild(row);
    });
}

export async function loadVectorCollections() {
    const endpoint = normalizeUrl(vectorEndpointEl.value);
    if (!endpoint) { vectorStatusEl.textContent = _tL()['vector-endpoint-invalid'] || "Vector : endpoint invalide."; return; }
    vectorStatusEl.textContent = _tL()['vector-loading'] || "Vector : chargement des collections…";
    vectorState.collectionsEndpoint = endpoint;
    vectorState.layers.forEach((layer) => { if (map.hasLayer(layer)) map.removeLayer(layer); });
    vectorState.visible.clear();
    try {
        const url = new URL(endpoint);
        if (!url.searchParams.has("f")) url.searchParams.set("f", "json");
        const response = await fetch(url.toString(), { headers: { Accept: "application/json,application/geo+json" } });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const data = await response.json();
        vectorState.collections = Array.isArray(data.collections) ? data.collections : [];
        vectorStatusEl.textContent = `Vector: ${vectorState.collections.length} ${_tL()['vector-detected'] || 'collection(s) détectée(s).'}`;
        renderVectorCollectionsList();
    } catch (error) {
        _setVectorStatus(`Vector: ${_tL()['vector-load-error'] || 'erreur de chargement'} (${error.message}).`);
    }
}

// ── BDPPAD section ────────────────────────────────────────────────────────────

const bdppadStatusEl = document.getElementById('bdppadStatus');
const bdppadListEl   = document.getElementById('bdppadList');
let _bdppadActiveId  = null;
let _bdppadActivateCb = null;

export function setBdppadActivateCallback(cb) { _bdppadActivateCb = cb; }

function _extractYear(id) {
    var m = id.match(/_an_(\d{4})/);
    if (m) return m[1];
    m = id.match(/[_-](20\d{2})[_-]/);
    if (m) return m[1];
    m = id.match(/(20\d{2})/);
    return m ? m[1] : id;
}

function _updateBdppadUI() {
    if (!bdppadListEl) return;
    bdppadListEl.querySelectorAll('.bdppad-item').forEach(function(el) {
        el.classList.toggle('active', el.dataset.cid === _bdppadActiveId);
    });
}

function _selectBdppadCollection(id) {
    if (_bdppadActivateCb) _bdppadActivateCb();
    if (_bdppadActiveId && _bdppadActiveId !== id) {
        setVectorCollectionVisible(_bdppadActiveId, false);
    }
    _bdppadActiveId = id;
    setVectorCollectionVisible(id, true, false, true); // skipTileProbe: BDPPAD always PostGIS
    _updateBdppadUI();
}

export function deselectBdppadCollection() {
    if (_bdppadActiveId) setVectorCollectionVisible(_bdppadActiveId, false);
    _bdppadActiveId = null;
    _updateBdppadUI();
}

function _renderBdppadList(collections) {
    if (!bdppadListEl) return;
    bdppadListEl.innerHTML = '';
    if (!collections.length) {
        const p = document.createElement('p');
        p.className = 'legend';
        p.textContent = _tL()['bdppad-none'] || 'Aucun jeu BDPPAD disponible.';
        bdppadListEl.appendChild(p);
        return;
    }
    collections.forEach(function(coll) {
        const item = document.createElement('div');
        item.className = 'bdppad-item';
        item.dataset.cid = coll.id;
        item.textContent = _extractYear(coll.id);
        item.addEventListener('click', function() {
            if (_bdppadActiveId === coll.id) {
                deselectBdppadCollection();
            } else {
                _selectBdppadCollection(coll.id);
            }
        });
        bdppadListEl.appendChild(item);
    });
}

const _BDPPAD_CACHE_KEY = 'sdss_bdppad_postgis_v1';

export async function loadBdppadCollections() {
    const tL = function() { return (window.T && window.T[window.lang]) || (window.T && window.T.fr) || {}; };

    // Phase 1 — cache hit: show full list instantly, refresh silently in background
    let bdppads;
    try {
        const cached = sessionStorage.getItem(_BDPPAD_CACHE_KEY);
        if (cached) bdppads = JSON.parse(cached);
    } catch(_) {}

    if (bdppads && bdppads.length) {
        vectorState.collectionsEndpoint = '/vector-api/parquet/collections';
        const others = vectorState.collections.filter(function(c) { return !c.id.startsWith('bdppad'); });
        vectorState.collections = others.concat(bdppads);
        _renderBdppadList(bdppads);
        if (bdppadStatusEl) bdppadStatusEl.textContent =
            bdppads.length + ' ' + (tL()['bdppad-available'] || 'jeu(x) disponible(s)');
        _selectBdppadCollection(bdppads[0].id);
        _refreshBdppadList(); // silent background refresh, no await
        return;
    }

    // Phase 2 — first load: show "Chargement…" then fetch list and select most recent year
    vectorState.collectionsEndpoint = '/vector-api/parquet/collections';
    if (bdppadListEl) {
        bdppadListEl.innerHTML = '';
        const loadingHint = document.createElement('p');
        loadingHint.className = 'legend';
        loadingHint.textContent = tL()['bdppad-loading'] || 'Chargement…';
        bdppadListEl.appendChild(loadingHint);
    }
    try {
        await _refreshBdppadList();
    } catch(e) {
        if (bdppadStatusEl) bdppadStatusEl.textContent = (tL()['bdppad-error'] || 'Erreur : ') + e.message;
    }
}

async function _refreshBdppadList() {
    const tL = function() { return (window.T && window.T[window.lang]) || (window.T && window.T.fr) || {}; };
    const r = await fetch('/vector-api/postgis/collections?f=json&limit=500');
    if (!r.ok) throw new Error('HTTP ' + r.status);
    const data = await r.json();
    const all = Array.isArray(data.collections) ? data.collections : [];
    const bdppads = all
        .filter(function(c) { return c.id && c.id.startsWith('public.bdppad'); })
        .map(function(c) {
            return { id: c.id.replace(/^public\./, ''), title: c.title, extent: c.extent, links: [] };
        });
    bdppads.sort(function(a, b) { return _extractYear(b.id).localeCompare(_extractYear(a.id)); });
    try { sessionStorage.setItem(_BDPPAD_CACHE_KEY, JSON.stringify(bdppads)); } catch(_) {}

    vectorState.collectionsEndpoint = '/vector-api/parquet/collections';
    const others = vectorState.collections.filter(function(c) { return !c.id.startsWith('bdppad'); });
    vectorState.collections = others.concat(bdppads);

    const prevActiveId = _bdppadActiveId;
    _renderBdppadList(bdppads);
    if (bdppadStatusEl) bdppadStatusEl.textContent = bdppads.length
        ? bdppads.length + ' ' + (tL()['bdppad-available'] || 'jeu(x) disponible(s)')
        : (tL()['bdppad-none'] || 'Aucun jeu BDPPAD trouvé.');

    const autoId = bdppads.length ? bdppads[0].id : null;
    if (autoId && autoId !== prevActiveId) {
        _selectBdppadCollection(autoId);
    } else {
        _updateBdppadUI();
    }
}
