import { map, vectorState, somContext } from './state.js';
import { getColorForCollection, apiFetch } from './utils.js';
import { openSomModal } from './som.js';
import { showHoverHint, hideHoverHint } from './hover-hint.js';
import { config } from './config.js';

function _tL() { return (window.T && window.T[window.lang]) || {}; }
// import { sendFeatureContext } from './chat.js'; // disabled: farm context auto-population

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
        const feature = { id: featureId, properties: props, type: 'Feature', geometry: parcelGeom, approximate: true };
        const layer = { getBounds: function() { return parcelBounds; } };

        // sendFeatureContext(collectionId, feature, center);
        openSomModal(collectionId, feature, layer);

        // Background: fetch exact parcel geometry from Parquet and silently update somContext
        const searchPad = 0.0002;
        const clickBbox = [e.latlng.lng - searchPad, e.latlng.lat - searchPad, e.latlng.lng + searchPad, e.latlng.lat + searchPad].join(',');
        const snap = feature;
        apiFetch('/vector-api/parquet/collections/' + collectionId + '/items?bbox=' + clickBbox + '&limit=10&f=json')
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
    return vtLayer;
}

export function setVectorCollectionVisible(collectionId, shouldShow) {
    const collection = vectorState.collections.find((item) => item.id === collectionId);
    if (!collection) return;

    if (!shouldShow) {
        const existingLayer = vectorState.layers.get(collectionId);
        if (existingLayer) map.removeLayer(existingLayer);
        return;
    }

    let layer = vectorState.layers.get(collectionId);
    if (!layer) {
        layer = buildVectorTileLayer(collectionId, getColorForCollection(collectionId));
        vectorState.layers.set(collectionId, layer);
    }
    layer.addTo(map);
}

// ── BDPPAD section ────────────────────────────────────────────────────────────

const bdppadStatusEl = document.getElementById('bdppadStatus');
const bdppadListEl   = document.getElementById('bdppadList');
let _bdppadActiveId  = null;
let _bdppadActivateCb = null;

export function setBdppadActivateCallback(cb) { _bdppadActivateCb = cb; }

let _bdppadStatus = null;

function _setBdppadStatus(key, count, detail) {
    _bdppadStatus = { key, count, detail };
    _renderBdppadStatus();
}

function _renderBdppadStatus() {
    if (!bdppadStatusEl || !_bdppadStatus) return;
    const { key, count, detail } = _bdppadStatus;
    const t = _tL();
    if (key === 'bdppad-available') {
        bdppadStatusEl.textContent = count + ' ' + (t[key] || 'jeu(x) disponible(s)');
    } else if (key === 'bdppad-error') {
        bdppadStatusEl.textContent = (t[key] || 'Erreur : ') + detail;
    } else {
        bdppadStatusEl.textContent = t[key] || 'Aucun jeu BDPPAD trouvé.';
    }
}

window.addEventListener('sdss-lang-change', _renderBdppadStatus);

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
    setVectorCollectionVisible(id, true);
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
        p.setAttribute('data-i18n', 'bdppad-none');
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
        const others = vectorState.collections.filter(function(c) {
            return !c.id.startsWith(config.primaryCollectionPrefix);
        });
        vectorState.collections = others.concat(bdppads);
        _renderBdppadList(bdppads);
        _setBdppadStatus('bdppad-available', bdppads.length);
        _selectBdppadCollection(bdppads[0].id);
        _refreshBdppadList(); // silent background refresh, no await
        return;
    }

    // Phase 2 — first load: show "Chargement…" then fetch list and select most recent year
    if (bdppadListEl) {
        bdppadListEl.innerHTML = '';
        const loadingHint = document.createElement('p');
        loadingHint.className = 'legend';
        loadingHint.setAttribute('data-i18n', 'bdppad-loading');
        loadingHint.textContent = tL()['bdppad-loading'] || 'Chargement…';
        bdppadListEl.appendChild(loadingHint);
    }
    try {
        await _refreshBdppadList();
    } catch(e) {
        _setBdppadStatus('bdppad-error', 0, e.message);
    }
}

async function _refreshBdppadList() {
    const r = await apiFetch('/vector-api/postgis/collections?f=json&limit=500');
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

    const others = vectorState.collections.filter(function(c) {
        return !c.id.startsWith(config.primaryCollectionPrefix);
    });
    vectorState.collections = others.concat(bdppads);

    const prevActiveId = _bdppadActiveId;
    _renderBdppadList(bdppads);
    if (bdppads.length) _setBdppadStatus('bdppad-available', bdppads.length);
    else _setBdppadStatus('bdppad-none');

    const autoId = bdppads.length ? bdppads[0].id : null;
    if (autoId && autoId !== prevActiveId) {
        _selectBdppadCollection(autoId);
    } else {
        _updateBdppadUI();
    }
}
