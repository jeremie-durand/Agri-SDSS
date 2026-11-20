import { map, somContext } from './state.js';
import { runProcessJob } from './utils.js';

const LS_CLASSES = [
    { label: '0–1', color: [26, 152, 80], range: [0, 26] },
    { label: '1–2', color: [166, 217, 106], range: [26, 51] },
    { label: '2–5', color: [254, 224, 139], range: [51, 128] },
    { label: '5–10', color: [244, 109, 67], range: [128, 255] },
    { label: '>10', color: [165, 0, 38], range: [255, 256] },
];

const TEXT = {
    fr: {
        title: 'Écoulement et LS',
        run: 'Calculer',
        remove: 'Retirer',
        loading: 'Calcul en cours…',
        error: 'Erreur',
        noField: 'Aucune parcelle sélectionnée',
        approximate: 'Contour exact de la parcelle indisponible : le calcul demande le polygone de la parcelle',
        noTiles: 'Aucune tuile LS dans la réponse',
        legend: 'Facteur LS (RUSLE)',
        slope: 'Pente moyenne',
        ls: 'LS moyen',
        sep: ' : ',
    },
    en: {
        title: 'Flow paths and LS',
        run: 'Compute',
        remove: 'Remove',
        loading: 'Computing…',
        error: 'Error',
        noField: 'No field selected',
        approximate: 'Exact field outline unavailable: the computation needs the field polygon',
        noTiles: 'No LS tiles in the response',
        legend: 'LS factor (RUSLE)',
        slope: 'Mean slope',
        ls: 'Mean LS',
        sep: ': ',
    },
};

let overlay = null;
let summary = null;
let statusState = null;
let running = false;
let panelToken = 0;

function t() {
    return TEXT[window.lang] || TEXT.fr;
}

function el(id) {
    return document.getElementById(id);
}

function sameOriginTileJsonUrl(href) {
    const url = new URL(href, window.location.origin);
    const params = url.searchParams;
    params.set('rescale', '0,10');
    params.set('colormap', JSON.stringify(LS_CLASSES.map(c => [c.range, [...c.color, 255]])));
    return `${url.pathname}?${params.toString()}`;
}

function formatNumber(value, digits) {
    if (value == null) return '—';
    return (+value).toLocaleString(window.lang === 'en' ? 'en-CA' : 'fr-CA', {
        minimumFractionDigits: digits, maximumFractionDigits: digits,
    });
}

function renderStatus() {
    const status = el('somFlowpathStatus');
    if (!statusState) {
        status.textContent = '';
        status.className = 'som-field__status';
        return;
    }
    const text = t();
    status.textContent = statusState.error
        ? `${text.error}${text.sep}${statusState.error}`
        : text[statusState.key];
    status.className = statusState.error ? 'som-field__status error' : 'som-field__status';
}

function renderLegend() {
    const legend = el('somFlowpathLegend');
    const remove = el('somFlowpathRemove');
    legend.hidden = !overlay;
    remove.hidden = !overlay;
    remove.disabled = running;
    if (!overlay) return;
    const text = t();
    el('somFlowpathLegendTitle').textContent = text.legend;
    el('somFlowpathClasses').innerHTML = LS_CLASSES.map(c =>
        `<span class="som-flowpath-class"><span class="som-flowpath-swatch" style="background:rgb(${c.color.join(',')})"></span>${c.label}</span>`
    ).join('');
    el('somFlowpathSummary').textContent = summary
        ? `${text.slope}${text.sep}${formatNumber(summary.slope?.mean_percent, 1)} % · ${text.ls}${text.sep}${formatNumber(summary.ls?.mean, 2)}`
        : '';
}

function renderText() {
    const text = t();
    el('somFlowpathTitle').textContent = text.title;
    el('somFlowpathRun').textContent = text.run;
    el('somFlowpathRemove').textContent = text.remove;
    renderStatus();
    renderLegend();
}

export function resetFlowpathPanel() {
    panelToken += 1;
    summary = null;
    statusState = null;
    renderStatus();
    renderLegend();
}

export function removeFlowpathLayer() {
    if (overlay) map.removeLayer(overlay);
    overlay = null;
    summary = null;
    statusState = null;
    renderStatus();
    renderLegend();
}

export async function runFlowpath() {
    const btn = el('somFlowpathRun');
    const feature = somContext.feature;
    if (!feature || !feature.geometry) {
        statusState = { error: t().noField };
        renderStatus();
        return;
    }
    if (feature.approximate) {
        statusState = { error: t().approximate };
        renderStatus();
        return;
    }
    const token = panelToken;
    const isCurrent = () => token === panelToken;
    btn.disabled = true;
    running = true;
    statusState = { key: 'loading' };
    renderStatus();
    renderLegend();
    try {
        const data = await runProcessJob('lidar-flowpath', { inputs: { location_type: 'polygon', polygon: feature.geometry } });
        const href = data.assets && data.assets.ls && data.assets.ls.tilejson;
        if (!href) throw new Error(t().noTiles);
        const response = await fetch(sameOriginTileJsonUrl(href));
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const tilejson = await response.json();
        const tileUrl = tilejson.tiles && tilejson.tiles[0];
        if (!tileUrl) throw new Error(t().noTiles);
        const options = { zIndex: 650, opacity: 0.8, maxZoom: 22 };
        if (Array.isArray(data.bbox) && data.bbox.length === 4) {
            options.bounds = L.latLngBounds([data.bbox[1], data.bbox[0]], [data.bbox[3], data.bbox[2]]);
        }
        if (overlay) map.removeLayer(overlay);
        overlay = L.tileLayer(tileUrl, options).addTo(map);
        summary = isCurrent() ? (data.summary || null) : null;
        if (isCurrent()) statusState = null;
    } catch (e) {
        if (isCurrent()) statusState = { error: e.message };
    } finally {
        running = false;
        btn.disabled = false;
        renderStatus();
        renderLegend();
    }
}

export function initFlowpathSection() {
    el('somFlowpathRun').addEventListener('click', runFlowpath);
    el('somFlowpathRemove').addEventListener('click', removeFlowpathLayer);
    window.addEventListener('sdss-lang-change', renderText);
    const langToggle = el('langToggle');
    if (langToggle) langToggle.addEventListener('click', renderText);
    renderText();
}
