import { map } from './state.js';

const GRHQ_COLOR = '#38bdf8';

let _layers = [];
let _active = false;
let _collections = null;
let _onActivateCb = null;
let _extent = null;

export function setGrhqActivateCallback(cb) { _onActivateCb = cb; }

export function deselectGrhq() {
    if (!_active) return;
    _active = false;
    _layers.forEach(function(l) { map.removeLayer(l); });
    _layers = [];
    _updateUI();
}

function _tL() { return (window.T && window.T[window.lang]) || {}; }

function _updateUI() {
    var btn = document.getElementById('grhqToggle');
    var statusEl = document.getElementById('grhqStatus');
    if (btn) btn.classList.toggle('active', _active);
    if (statusEl) statusEl.textContent = _active
        ? (_tL()['grhq-active']   || 'Active')
        : (_tL()['grhq-inactive'] || 'Inactive');
}

async function _loadCollections() {
    if (_collections) return _collections;
    try {
        var r = await fetch('/vector-api/postgis/collections?f=json&limit=500');
        if (!r.ok) throw new Error('HTTP ' + r.status);
        var data = await r.json();
        _collections = (data.collections || []).filter(function(c) {
            return c.id && c.id.startsWith('public.grhq_');
        });
        // Compute union extent from all collection bboxes to use for fitBounds
        var minLng = Infinity, minLat = Infinity, maxLng = -Infinity, maxLat = -Infinity;
        _collections.forEach(function(c) {
            var bbox = c.extent && c.extent.spatial && c.extent.spatial.bbox && c.extent.spatial.bbox[0];
            if (bbox && bbox.length >= 4) {
                if (bbox[0] < minLng) minLng = bbox[0];
                if (bbox[1] < minLat) minLat = bbox[1];
                if (bbox[2] > maxLng) maxLng = bbox[2];
                if (bbox[3] > maxLat) maxLat = bbox[3];
            }
        });
        if (minLng !== Infinity) _extent = [[minLat, minLng], [maxLat, maxLng]];
    } catch(e) {
        console.error('[grhq] Failed to fetch collections:', e);
        _collections = [];
    }
    return _collections;
}

async function _toggle() {
    _active = !_active;
    if (_active) {
        if (_onActivateCb) _onActivateCb();
        var btn = document.getElementById('grhqToggle');
        if (btn) btn.disabled = true;
        try {
            await _addLayers();
        } finally {
            if (btn) btn.disabled = false;
        }
    } else {
        _layers.forEach(function(l) { map.removeLayer(l); });
        _layers = [];
    }
    _updateUI();
}

async function _addLayers() {
    var cols = await _loadCollections();
    cols.forEach(function(col) {
        var tileUrl = '/vector-api/postgis/collections/' + encodeURIComponent(col.id) + '/tiles/WebMercatorQuad/{z}/{x}/{y}';
        var layer = L.vectorGrid.protobuf(tileUrl, {
            vectorTileLayerStyles: {
                'default': {
                    color: GRHQ_COLOR,
                    weight: 1.2,
                    fill: true,
                    fillColor: GRHQ_COLOR,
                    fillOpacity: 0.18
                }
            },
            interactive: false,
            // Tiles at zoom < 10 pack the full dataset into one tile (1.5–2 MB) which
            // overloads the browser. Only request tiles when zoomed in enough.
            minZoom: 10,
            maxZoom: 18
        });
        layer.addTo(map);
        _layers.push(layer);
    });
}

export function initGrhqSection() {
    var listEl = document.getElementById('grhqList');
    if (!listEl) return;
    listEl.innerHTML = '';
    var btn = document.createElement('div');
    btn.id = 'grhqToggle';
    btn.className = 'bdppad-item';
    btn.setAttribute('data-i18n', 'grhq-title');
    btn.textContent = _tL()['grhq-title'] || 'GRHQ Water Network';
    btn.addEventListener('click', _toggle);
    listEl.appendChild(btn);
    _updateUI();
}
