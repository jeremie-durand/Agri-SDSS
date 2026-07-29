import { map } from './state.js';
import { openSomModal } from './som.js';
import { showHoverHint, hideHoverHint } from './hover-hint.js';
// import { sendFeatureContext } from './chat.js'; // disabled: farm context auto-population

// window.AAC_CROP_CODES is loaded via <script src="/js/aac-crop-codes.js"> in map.html

const QC_BOUNDS = L.latLngBounds([44.9, -79.9], [63.0, -57.0]);

const AAC_DATASETS = [
    { year: '2025', path: 'inventaire_annuel_des_cultures/2025/ImageServer', notLive: true },
    { year: '2024', path: 'inventaire_annuel_des_cultures/2024/ImageServer' },
    { year: '2023', path: 'inventaire_annuel_des_cultures/2023/ImageServer' },
    { year: '2022', path: 'inventaire_annuel_des_cultures/2022/ImageServer' },
    { year: '2021', path: 'inventaire_annuel_des_cultures/2021/ImageServer' },
    { year: '2020', path: 'inventaire_annuel_des_cultures/2020/ImageServer' },
    { year: '2019', path: 'inventaire_annuel_des_cultures/2019/ImageServer' },
    { year: '2018', path: 'inventaire_annuel_des_cultures/2018/ImageServer' },
    { year: '2017', path: 'inventaire_annuel_des_cultures/2017/ImageServer' },
    { year: '2016', path: 'inventaire_annuel_des_cultures/2016/ImageServer' },
];

const _aacLayers  = new Map();
let _aacActive    = false;
let _activeYear   = null;
let _onActivateCb = null;

export function setAacActivateCallback(cb) { _onActivateCb = cb; }

export function deselectAac() {
    if (!_aacActive) return;
    const layer = _activeYear && _aacLayers.get(_activeYear);
    _aacActive  = false;
    _activeYear = null;
    if (layer && map.hasLayer(layer)) map.removeLayer(layer);
    map.off('click', _onMapClick);
    map.off('mousemove', _onMapHover);
    map.off('mouseout', hideHoverHint);
    _setAacCursor(false);
    hideHoverHint();
    _updateAacUI();
}

function _tL() { return (window.T && window.T[window.lang]) || {}; }

// AAC pixels have no per-feature hover target (raster tiles), so the
// pointer cursor and "click to identify" hint are shown for the whole
// map while a layer is active — mirrors the affordance BDPPAD parcels
// already get for free from Leaflet's .leaflet-interactive styling.
function _setAacCursor(active) {
    map.getContainer().classList.toggle('aac-identify-active', active);
}

function _onMapHover(e) {
    showHoverHint(e.originalEvent.clientX, e.originalEvent.clientY, _tL()['aac-hover-hint'] || 'Click to identify the crop here');
}

function _buildExportImageLayer(dataset) {
    const base = `https://agriculture.canada.ca/imagery-images/rest/services/${dataset.path}/exportImage`;
    return L.GridLayer.extend({
        createTile(coords, done) {
            const img    = document.createElement('img');
            const bounds = this._tileCoordsToBounds(coords);
            const bbox   = [bounds.getWest(), bounds.getSouth(), bounds.getEast(), bounds.getNorth()].join(',');
            // adjustAspectRatio=false: ArcGIS otherwise nudges each tile's requested
            // extent to match the pixel aspect ratio independently per request, which
            // drifts adjacent tiles out of alignment (visible seams while navigating).
            const url    = `${base}?bbox=${bbox}&bboxSR=4326&size=256,256&imageSR=4326&format=png32&transparent=true&adjustAspectRatio=false&f=image`;
            img.onload  = () => done(null, img);
            img.onerror = () => done(null, img);
            img.src = url;
            return img;
        },
    });
}

function _getOrCreateLayer(dataset) {
    if (_aacLayers.has(dataset.year)) return _aacLayers.get(dataset.year);
    const AacLayer = _buildExportImageLayer(dataset);
    const layer = new AacLayer({
        opacity: 0.75,
        bounds: QC_BOUNDS,
        maxZoom: 16,
        minZoom: 4,
        updateInterval: 50,
        keepBuffer: 4,
        attribution: '© Agriculture et Agroalimentaire Canada / Agriculture and Agri-Food Canada',
    });
    _aacLayers.set(dataset.year, layer);
    return layer;
}

async function _identify(dataset, latlng) {
    const identifyUrl = `/aac-identify/${dataset.path}/identify`;
    const params = new URLSearchParams({
        geometry: JSON.stringify({ x: latlng.lng, y: latlng.lat, spatialReference: { wkid: 4326 } }),
        geometryType: 'esriGeometryPoint',
        pixelSize: JSON.stringify({ x: 30, y: 30 }),
        returnGeometry: 'false',
        f: 'json',
    });
    const r = await fetch(`${identifyUrl}?${params}`);
    if (!r.ok) throw new Error('HTTP ' + r.status);
    return r.json();
}

async function _onMapClick(e) {
    if (!_aacActive || !_activeYear) return;
    const statusEl = document.getElementById('aacStatus');
    const dataset = AAC_DATASETS.find((d) => d.year === _activeYear);
    if (!dataset) return;

    if (statusEl) statusEl.textContent = _tL()['aac-identify-loading'] || 'Identification…';
    try {
        const data   = await _identify(dataset, e.latlng);
        const rawVal = data && data.value != null ? String(data.value) : null;
        if (!rawVal || rawVal === 'NoData' || rawVal === 'null' || rawVal === '') throw new Error('nodata');
        const entry      = window.AAC_CROP_CODES && window.AAC_CROP_CODES[parseInt(rawVal, 10)];
        const groProCode = (entry && entry.gropro) || 'AUT';
        const _b = L.latLng(e.latlng).toBounds(500);
        const geometry   = { type: 'Polygon', coordinates: [[[_b.getWest(), _b.getSouth()], [_b.getEast(), _b.getSouth()], [_b.getEast(), _b.getNorth()], [_b.getWest(), _b.getNorth()], [_b.getWest(), _b.getSouth()]]] };
        const feature    = { properties: { GROPRO: groProCode, aac_code: rawVal }, type: 'Feature', geometry };
        const mockLayer  = { getBounds: () => _b };
        if (statusEl) statusEl.textContent = _tL()['aac-active'] || 'Couche active';
        // sendFeatureContext('aac_' + _activeYear, feature, { lat: e.latlng.lat, lon: e.latlng.lng });
        openSomModal('aac_' + _activeYear, feature, mockLayer);
    } catch (_e) {
        if (statusEl) statusEl.textContent = _tL()['aac-identify-error'] || 'Aucune donnée à cet emplacement.';
    }
}

function _activateAac(dataset) {
    if (_onActivateCb) _onActivateCb();
    if (_activeYear && _activeYear !== dataset.year) {
        const prev = _aacLayers.get(_activeYear);
        if (prev && map.hasLayer(prev)) map.removeLayer(prev);
    }
    _aacActive  = true;
    _activeYear = dataset.year;
    _getOrCreateLayer(dataset).addTo(map);
    map.on('click', _onMapClick);
    map.on('mousemove', _onMapHover);
    map.on('mouseout', hideHoverHint);
    _setAacCursor(true);
    _updateAacUI();
}

function _deactivateAac() {
    const layer = _aacLayers.get(_activeYear);
    _aacActive  = false;
    _activeYear = null;
    if (layer && map.hasLayer(layer)) map.removeLayer(layer);
    map.off('click', _onMapClick);
    map.off('mousemove', _onMapHover);
    map.off('mouseout', hideHoverHint);
    _setAacCursor(false);
    hideHoverHint();
    _updateAacUI();
}

function _updateAacUI() {
    const listEl    = document.getElementById('aacList');
    const statusEl  = document.getElementById('aacStatus');
    const noticeEl  = document.getElementById('aacNotLiveNotice');
    if (!listEl) return;
    listEl.querySelectorAll('.bdppad-item').forEach((el) => {
        el.classList.toggle('active', el.dataset.year === _activeYear);
    });
    if (statusEl && statusEl.textContent === (_tL()['aac-identify-loading'] || 'Identification…')) return;
    if (statusEl) statusEl.textContent = _aacActive
        ? (_tL()['aac-active']   || 'Couche active')
        : (_tL()['aac-inactive'] || 'Couche inactive');
    if (noticeEl) {
        const activeDataset = _activeYear && AAC_DATASETS.find((d) => d.year === _activeYear);
        const show = !!(activeDataset && activeDataset.notLive);
        noticeEl.hidden = !show;
        if (show) noticeEl.textContent = _tL()['aac-not-live'] || 'Note : La couche 2025 n\'est pas encore disponible.';
    }
}

export function initAacSection() {
    const listEl = document.getElementById('aacList');
    if (!listEl) return;
    AAC_DATASETS.forEach((dataset) => {
        const item = document.createElement('div');
        item.className    = 'bdppad-item';
        item.dataset.year = dataset.year;
        item.textContent  = dataset.year;
        item.addEventListener('click', () => {
            if (_activeYear === dataset.year) _deactivateAac();
            else _activateAac(dataset);
        });
        listEl.appendChild(item);
    });
    _updateAacUI();
}
