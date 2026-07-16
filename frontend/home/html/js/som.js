import { somContext, somChartInstance, setSomChartInstance, vectorState, layers } from './state.js';
import { bboxAreaHa } from './utils.js';

function _geomBbox(geom) {
    const coords = [];
    const collect = c => Array.isArray(c[0]) ? c.forEach(collect) : coords.push(c);
    collect(geom.coordinates);
    const lngs = coords.map(c => c[0]);
    const lats = coords.map(c => c[1]);
    return [Math.min(...lngs), Math.min(...lats), Math.max(...lngs), Math.max(...lats)];
}

// ── SOM Predict tab state ─────────────────────────────────────────────────
var somPredictFieldIds = [];
var somPredictChartInstance = null;
var somPredictLastFc = null;
var somPredictUnit = 'gkg';
var _somProgressTimer = null;

// Stages: realistic timing based on actual backend pipeline duration.
// Delays are time to spend at each stage before auto-advancing.
var _PREDICT_STAGES = [
    { pct: 8,  key: 'som-stage-loading',  ms: 2500  },
    { pct: 26, key: 'som-stage-lasso',    ms: 12000 },
    { pct: 53, key: 'som-stage-ranking',  ms: 18000 },
    { pct: 80, key: 'som-stage-rf',       ms: 25000 },
    { pct: 92, key: 'som-stage-building', ms: 999999 },
];

function somProgressStart() {
    if (_somProgressTimer) { clearTimeout(_somProgressTimer); _somProgressTimer = null; }
    var progEl  = document.getElementById('somPredictProgress');
    var barEl   = document.getElementById('somProgressBar');
    var stageEl = document.getElementById('somProgressStage');
    barEl.style.background = '';
    barEl.style.width = '0%';
    progEl.hidden = false;
    var tl = (window.T && window.T[window.lang]) || (window.T && window.T['en']) || {};
    var i = 0;
    function advance() {
        if (i >= _PREDICT_STAGES.length) return;
        var s = _PREDICT_STAGES[i++];
        barEl.style.width = s.pct + '%';
        stageEl.textContent = tl[s.key] || s.key;
        _somProgressTimer = setTimeout(advance, s.ms);
    }
    advance();
}

function somProgressDone(success) {
    if (_somProgressTimer) { clearTimeout(_somProgressTimer); _somProgressTimer = null; }
    var progEl  = document.getElementById('somPredictProgress');
    var barEl   = document.getElementById('somProgressBar');
    var stageEl = document.getElementById('somProgressStage');
    if (success) {
        barEl.style.width = '100%';
        stageEl.textContent = '';
        setTimeout(function() { progEl.hidden = true; barEl.style.width = '0%'; }, 600);
    } else {
        barEl.style.background = '#f87171';
        stageEl.textContent = '';
        setTimeout(function() { progEl.hidden = true; barEl.style.width = '0%'; barEl.style.background = ''; }, 1200);
    }
}

function somSwitchTab(tab) {
    var isPoc = tab === 'poc';
    document.getElementById('somPanelPoc').hidden = !isPoc;
    document.getElementById('somPanelPredict').hidden = isPoc;
    document.getElementById('somTabPoc').classList.toggle('som-tab--active', isPoc);
    document.getElementById('somTabPoc').setAttribute('aria-selected', String(isPoc));
    document.getElementById('somTabPredict').classList.toggle('som-tab--active', !isPoc);
    document.getElementById('somTabPredict').setAttribute('aria-selected', String(!isPoc));
    // Show Run + status only on PoC tab; hide Export PDF when leaving PoC
    document.getElementById('somRun').hidden = !isPoc;
    document.getElementById('somRunStatus').hidden = !isPoc;
    if (!isPoc) document.getElementById('somExportPdf').hidden = true;
}

function somPredictReset() {
    somPredictFieldIds = [];
    somPredictLastFc = null;
    somPredictUnit = 'gkg';
    document.getElementById('somPredictFieldInfo').textContent = '—';
    var st = document.getElementById('somPredictFieldStatus');
    st.textContent = '';
    st.className = 'som-field__status';
    document.getElementById('somPredictResults').hidden = true;
    document.getElementById('somPredictRun').disabled = true;
    var rs = document.getElementById('somPredictRunStatus');
    rs.textContent = '';
    rs.className = 'som-run__status';
    var gkgBtn = document.getElementById('somUnitGkg');
    var pctBtn = document.getElementById('somUnitPct');
    if (gkgBtn) gkgBtn.classList.add('som-unit-btn--active');
    if (pctBtn) pctBtn.classList.remove('som-unit-btn--active');
    if (_somProgressTimer) { clearTimeout(_somProgressTimer); _somProgressTimer = null; }
    var progEl = document.getElementById('somPredictProgress');
    if (progEl) progEl.hidden = true;
    var barEl = document.getElementById('somProgressBar');
    if (barEl) { barEl.style.width = '0%'; barEl.style.background = ''; }
    if (somPredictChartInstance) { somPredictChartInstance.destroy(); somPredictChartInstance = null; }
}

async function somPredictFindField() {
    var tLang = T[lang] || T['en'];
    var st = document.getElementById('somPredictFieldStatus');
    st.className = 'som-field__status';
    st.textContent = tLang['som-loading'] || 'Searching…';

    try {
        var geom = somContext.feature && somContext.feature.geometry;
        if (!geom) {
            var b = somContext.layer && somContext.layer.getBounds ? somContext.layer.getBounds() : null;
            if (!b) throw new Error('No geometry available');
            geom = { type: 'Point',
                     coordinates: [(b.getWest() + b.getEast()) / 2, (b.getSouth() + b.getNorth()) / 2] };
        }

        var r = await fetch('/vector-api/som-field-match', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ geometry: geom })
        });
        if (!r.ok) throw new Error('HTTP ' + r.status);
        var data = await r.json();
        var matches = data.matches || [];

        var geeMatches = matches.filter(function(m) { return m.has_gee_data; });
        somPredictFieldIds = geeMatches.map(function(m) { return m.gid; });

        if (geeMatches.length > 0) {
            var label = geeMatches.length === 1
                ? (tLang['som-predict-field-gee'] || 'Field #') + geeMatches[0].gid +
                  (tLang['som-predict-field-gee-suffix'] || ' — GEE training data available')
                : geeMatches.length + (tLang['som-predict-field-gee-multi'] || ' GEE fields found');
            document.getElementById('somPredictFieldInfo').textContent = label;
            st.textContent = '';
            document.getElementById('somPredictRun').disabled = false;
        } else if (matches.length > 0) {
            document.getElementById('somPredictFieldInfo').textContent =
                (tLang['som-predict-field-no-gee'] || 'Field #') + matches[0].gid +
                (tLang['som-predict-field-no-gee-suffix'] || ' — No GEE training data');
            st.textContent = tLang['som-predict-no-field'] || 'No GEE training data found for this farm';
            st.className = 'som-field__status error';
        } else {
            document.getElementById('somPredictFieldInfo').textContent = '—';
            st.textContent = tLang['som-predict-no-field'] || 'No GEE training data found for this farm';
            st.className = 'som-field__status error';
        }
    } catch(e) {
        st.textContent = (tLang['som-error'] || 'Error') + ': ' + e.message;
        st.className = 'som-field__status error';
    }
}

export async function somPredictRun() {
    if (somPredictFieldIds.length === 0) return;
    var btn = document.getElementById('somPredictRun');
    var status = document.getElementById('somPredictRunStatus');
    var tLang = T[lang] || T['en'];
    btn.disabled = true;
    status.textContent = '';
    status.className = 'som-run__status';
    somProgressStart();
    try {
        var r = await fetch('/process-api/processes/som-predict-soil/execution?f=json', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ inputs: { field_ids: somPredictFieldIds, scenarios: ['S3_spec_soil_topo_clim'] } })
        });
        if (!r.ok) throw new Error('HTTP ' + r.status);
        var data = await r.json();
        // Response: { id: 'result', value: <FeatureCollection> }
        var fc = data.value || data;
        somProgressDone(true);
        somPredictDisplayResults(fc);
        status.textContent = tLang['som-run-ok'] || 'Complete';
        status.className = 'som-run__status ok';
    } catch(e) {
        somProgressDone(false);
        status.textContent = (tLang['som-run-error'] || 'Error') + ': ' + e.message;
        status.className = 'som-run__status error';
        btn.disabled = false;
    }
}

function somPredictDisplayResults(fc) {
    somPredictLastFc = fc;
    var features = ((fc && fc.features) || []).filter(function(f) {
        return f.properties && f.properties.scenario === 'S3_spec_soil_topo_clim';
    });
    var fieldSummary = (fc && fc.field_summary) || [];
    document.getElementById('somPredictResults').hidden = false;

    // ── 1-image guard ──
    var maxImages = fieldSummary.reduce(function(mx, m) {
        return Math.max(mx, m.n_images_used || 0);
    }, 0);
    var lowData = maxImages <= 1;
    var errEl   = document.getElementById('somPredictError');
    var chartSec = document.getElementById('somPredictChartSection');
    var metricsSec = document.getElementById('somPredictMetricsSection');
    var unitToggle = document.getElementById('somUnitToggle');
    errEl.hidden   = !lowData;
    chartSec.hidden = lowData;
    metricsSec.hidden = lowData;
    unitToggle.hidden = lowData;
    if (lowData) {
        document.querySelectorAll('#somPredictError [data-i18n]').forEach(function(el) {
            var k = el.getAttribute('data-i18n');
            if (window.T && window.T[window.lang] && window.T[window.lang][k] !== undefined) {
                el.innerHTML = window.T[window.lang][k];
            }
        });
        return;
    }

    var factor   = (somPredictUnit === 'pct') ? 0.1 : 1.0;
    var unitLabel = (somPredictUnit === 'pct') ? 'SOM (%)' : 'SOM (g/kg)';
    var unitSuffix = (somPredictUnit === 'pct') ? ' %' : ' g/kg';

    // ── Trend chart: avg predicted & measured SOM per year, with min/max band ──
    var yearData = {};
    features.forEach(function(f) {
        var p = f.properties;
        if (!p) return;
        var year = (p.Image_ID || '').split('_')[0] || 'unknown';
        if (!yearData[year]) yearData[year] = { pred: [], meas: [] };
        if (p.y_pred_lin != null) yearData[year].pred.push(p.y_pred_lin * factor);
        if (p.y_true_lin != null) yearData[year].meas.push(p.y_true_lin * factor);
    });
    var years = Object.keys(yearData).sort();
    function avg(arr) { return arr.length ? arr.reduce(function(a,b){return a+b;},0)/arr.length : null; }
    var avgPred = years.map(function(y){ return avg(yearData[y].pred); });
    var minPred = years.map(function(y){ var a=yearData[y].pred; return a.length?Math.min.apply(null,a):null; });
    var maxPred = years.map(function(y){ var a=yearData[y].pred; return a.length?Math.max.apply(null,a):null; });
    var avgMeas = years.map(function(y){ return avg(yearData[y].meas); });

    if (somPredictChartInstance) { somPredictChartInstance.destroy(); somPredictChartInstance = null; }
    somPredictChartInstance = new Chart(document.getElementById('somPredictChart'), {
        type: 'line',
        data: {
            labels: years,
            datasets: [
                {
                    label: '_max',
                    data: maxPred,
                    borderColor: 'transparent',
                    backgroundColor: 'rgba(34,211,238,0.12)',
                    fill: '+1',
                    pointRadius: 0,
                    tension: 0.3
                },
                {
                    label: '_min',
                    data: minPred,
                    borderColor: 'transparent',
                    backgroundColor: 'rgba(34,211,238,0.12)',
                    fill: false,
                    pointRadius: 0,
                    tension: 0.3
                },
                {
                    label: 'Predicted SOM (avg)',
                    data: avgPred,
                    borderColor: '#22d3ee',
                    backgroundColor: '#22d3ee',
                    fill: false,
                    pointRadius: 5,
                    pointHoverRadius: 7,
                    tension: 0.3,
                    borderWidth: 2
                },
                {
                    label: 'Measured SOM (avg)',
                    data: avgMeas,
                    borderColor: '#f59e0b',
                    backgroundColor: '#f59e0b',
                    borderDash: [5, 4],
                    fill: false,
                    pointRadius: 5,
                    pointHoverRadius: 7,
                    tension: 0.3,
                    borderWidth: 2
                }
            ]
        },
        options: {
            responsive: true, maintainAspectRatio: false,
            plugins: {
                legend: {
                    labels: {
                        color: '#9bb6d2', font: { size: 11 },
                        filter: function(item) { return item.text[0] !== '_'; }
                    }
                },
                tooltip: {
                    callbacks: {
                        label: function(ctx) {
                            if (ctx.dataset.label[0] === '_') return null;
                            return ctx.dataset.label + ': ' + (ctx.parsed.y != null ? ctx.parsed.y.toFixed(2) + unitSuffix : '—');
                        }
                    }
                }
            },
            scales: {
                x: { title: { display: true, text: 'Year', color: '#9bb6d2', font: { size: 11 } },
                     ticks: { color: '#9bb6d2', font: { size: 10 } }, grid: { color: '#294766' } },
                y: { title: { display: true, text: unitLabel, color: '#9bb6d2', font: { size: 11 } },
                     ticks: { color: '#9bb6d2', font: { size: 10 } }, grid: { color: '#294766' } }
            }
        }
    });

    // ── Metrics table ──
    var tbody = document.querySelector('#somPredictMetrics tbody');
    tbody.innerHTML = '';
    fieldSummary.forEach(function(m) {
        var rmse = m.RMSE_lin != null ? (+m.RMSE_lin * factor).toFixed(3) : '—';
        var mae  = m.MAE_lin  != null ? (+m.MAE_lin  * factor).toFixed(3) : '—';
        var tr = document.createElement('tr');
        tr.innerHTML =
            '<td>' + (m.R2_lin != null ? (+m.R2_lin).toFixed(2) + (m.r2_source === 'val' ? ' <span title="Validation R² (single test field)">*</span>' : '') : '—') + '</td>' +
            '<td>' + rmse + '</td>' +
            '<td>' + mae  + '</td>' +
            '<td>' + (m.n_images_used != null ? m.n_images_used : m.n_fields != null ? m.n_fields : '—') + '</td>';
        tbody.appendChild(tr);
    });

    // ── Farmer interpretation ──
    var r2 = fieldSummary.length > 0 ? fieldSummary[0].R2_lin : null;
    var interp = document.getElementById('somPredictInterpretation');
    if (r2 != null) {
        var r2pct = Math.round(r2 * 100);
        var qualityKey;
        if      (r2 >= 0.75) qualityKey = 'som-interp-excellent';
        else if (r2 >= 0.50) qualityKey = 'som-interp-good';
        else if (r2 >= 0.25) qualityKey = 'som-interp-moderate';
        else                  qualityKey = 'som-interp-weak';
        var tl = (window.T && window.T[window.lang]) || (window.T && window.T['en']) || {};
        var suffix = (tl['som-interp-body'] || '').replace('{r2pct}', r2pct);
        var valNote = fieldSummary[0].r2_source === 'val' ? ' ' + (tl['som-interp-val-note'] || '') : '';
        interp.textContent = (tl[qualityKey] || '') + suffix + valNote;
        interp.hidden = false;
    } else {
        interp.hidden = true;
    }
}

export function openSomModal(collectionId, feature, layer) {
    somContext.collectionId = collectionId;
    somContext.feature = feature;
    somContext.layer = layer;

    var b = layer.getBounds ? layer.getBounds() : null;
    document.getElementById('somExtent').value = b
        ? [b.getWest(), b.getSouth(), b.getEast(), b.getNorth()].map(function(v) { return v.toFixed(4); }).join(', ')
        : '';

    var sel = document.getElementById('somCulture');
    sel.innerHTML = '';
    var props = (feature && feature.properties) || {};
    var featureCode = props['GROPRO'] || props['gropro'] || 'AUT';
    Object.keys(GROPRO_LABELS).forEach(function(code) {
        var opt = document.createElement('option');
        opt.value = code;
        opt.textContent = code + ' — ' + GROPRO_LABELS[code];
        if (code === featureCode) opt.selected = true;
        sel.appendChild(opt);
    });

    ['somCorg', 'somPh', 'somSable', 'somLimon', 'somArgile', 'somCec',
     'somScenes', 'somElevation', 'somPrecip', 'somArea', 'somPedo', 'somWater'].forEach(function(id) {
        document.getElementById(id).value = '';
    });
    ['somCultureStatus', 'somCorgStatus', 'somPhStatus', 'somSableStatus', 'somLimonStatus', 'somArgileStatus', 'somCecStatus',
     'somScenesStatus', 'somElevationStatus', 'somPrecipStatus', 'somAreaStatus', 'somPedoStatus', 'somWaterStatus'].forEach(function(id) {
        var el = document.getElementById(id);
        el.textContent = '';
        el.className = 'som-field__status';
    });

    // Auto-fill area: check feature properties first, fall back to bbox, then refine via API
    var areaEl = document.getElementById('somArea');
    var directHa = props.superficie_ha != null ? props.superficie_ha
        : props.area_ha != null ? props.area_ha
        : props.hectares != null ? props.hectares
        : props.suphec != null ? props.suphec
        : props.sup != null ? props.sup / 10000
        : null;
    if (directHa != null) {
        areaEl.value = (+directHa).toFixed(1);
    } else {
        var areaStatusEl = document.getElementById('somAreaStatus');
        var tL = T[lang] || T['en'];
        areaStatusEl.textContent = tL['som-loading'];
    }

    // Clear any leftover validation error states and attach live-clear listeners
    ['somCulture', 'somCorg', 'somPh', 'somSable', 'somLimon', 'somArgile', 'somCec', 'somArea', 'somPedo', 'somWater'].forEach(function(id) {
        var el = document.getElementById(id);
        el.closest('.som-field').classList.remove('som-field--error');
        if (el._somValListener) el.removeEventListener('input', el._somValListener);
        el._somValListener = function() {
            if (el.value.trim()) el.closest('.som-field').classList.remove('som-field--error');
        };
        el.addEventListener('input', el._somValListener);
    });

    document.getElementById('somExportPdf').hidden = true;
    document.getElementById('somAacNotice').hidden = !collectionId.startsWith('aac');

    // Tab init: wire click listeners once, then switch to PoC tab and kick off predict lookup
    var tabPoc = document.getElementById('somTabPoc');
    var tabPredict = document.getElementById('somTabPredict');
    if (!tabPoc._somTabWired) {
        tabPoc.addEventListener('click', function() { somSwitchTab('poc'); });
        tabPredict.addEventListener('click', function() { somSwitchTab('predict'); });
        tabPoc._somTabWired = true;
        // Wire unit toggle once
        ['somUnitGkg', 'somUnitPct'].forEach(function(id) {
            var btn = document.getElementById(id);
            if (!btn) return;
            btn.addEventListener('click', function() {
                somPredictUnit = (id === 'somUnitPct') ? 'pct' : 'gkg';
                document.getElementById('somUnitGkg').classList.toggle('som-unit-btn--active', somPredictUnit === 'gkg');
                document.getElementById('somUnitPct').classList.toggle('som-unit-btn--active', somPredictUnit === 'pct');
                if (somPredictLastFc) somPredictDisplayResults(somPredictLastFc);
            });
        });
    }
    somSwitchTab('poc');
    somPredictReset();
    somPredictFindField();

    document.getElementById('somModal').hidden = false;
}

export function closeSomModal() {
    document.getElementById('somModal').hidden = true;
    document.getElementById('somResults').hidden = true;
    document.getElementById('somExportPdf').hidden = true;
    var st = document.getElementById('somRunStatus');
    st.textContent = '';
    st.className = 'som-run__status';
    if (somChartInstance) { somChartInstance.destroy(); setSomChartInstance(null); }
    somPredictReset();
}

function somValidateFields() {
    var valid = true;
    ['somCulture', 'somCorg', 'somPh', 'somSable', 'somLimon', 'somArgile', 'somCec', 'somArea', 'somPedo', 'somWater'].forEach(function(id) {
        var el = document.getElementById(id);
        var container = el.closest('.som-field');
        if (!el.value.trim()) {
            container.classList.add('som-field--error');
            valid = false;
        } else {
            container.classList.remove('som-field--error');
        }
    });
    return valid;
}

function _lon2tile(lon, z) { return Math.floor((lon + 180) / 360 * Math.pow(2, z)); }
function _lat2tile(lat, z) {
    return Math.floor((1 - Math.log(Math.tan(lat * Math.PI / 180) + 1 / Math.cos(lat * Math.PI / 180)) / Math.PI) / 2 * Math.pow(2, z));
}
function _tile2lon(x, z) { return x / Math.pow(2, z) * 360 - 180; }
function _tile2lat(y, z) {
    var n = Math.PI - 2 * Math.PI * y / Math.pow(2, z);
    return 180 / Math.PI * Math.atan(0.5 * (Math.exp(n) - Math.exp(-n)));
}
function _pickZoom(minLon, minLat, maxLon, maxLat, maxTiles) {
    for (var z = 17; z >= 8; z--) {
        var x0 = _lon2tile(minLon, z), x1 = _lon2tile(maxLon, z);
        var y0 = _lat2tile(maxLat, z), y1 = _lat2tile(minLat, z);
        if ((x1 - x0 + 1) * (y1 - y0 + 1) <= maxTiles) return z;
    }
    return 8;
}
function _loadTileImage(url) {
    return new Promise(function(resolve) {
        var img = new Image();
        img.crossOrigin = 'anonymous';
        img.onload  = function() { resolve(img); };
        img.onerror = function() { resolve(null); };
        img.src = url;
    });
}
function _tileUrl(template, z, x, y, subdomains) {
    var sd = subdomains && subdomains.length ? subdomains : ['a', 'b', 'c'];
    var s = sd[(x + y) % sd.length];
    return template.replace('{z}', z).replace('{x}', x).replace('{y}', y).replace('{s}', s);
}

async function somRenderPolygonCanvas(geometry, width, height) {
    var canvas = document.createElement('canvas');
    canvas.width = width;
    canvas.height = height;
    var ctx = canvas.getContext('2d');

    ctx.fillStyle = '#101f33';
    ctx.fillRect(0, 0, width, height);

    var rings = [];
    if (geometry.type === 'Polygon') {
        rings = geometry.coordinates;
    } else if (geometry.type === 'MultiPolygon') {
        geometry.coordinates.forEach(function(poly) {
            poly.forEach(function(ring) { rings.push(ring); });
        });
    }
    if (!rings.length) return canvas;

    var allCoords = [];
    rings.forEach(function(ring) { ring.forEach(function(pt) { allCoords.push(pt); }); });
    var minX = allCoords.reduce(function(m, p) { return Math.min(m, p[0]); }, Infinity);
    var maxX = allCoords.reduce(function(m, p) { return Math.max(m, p[0]); }, -Infinity);
    var minY = allCoords.reduce(function(m, p) { return Math.min(m, p[1]); }, Infinity);
    var maxY = allCoords.reduce(function(m, p) { return Math.max(m, p[1]); }, -Infinity);

    var pad = 12;
    var rangeX = maxX - minX || 1;
    var rangeY = maxY - minY || 1;
    var scale = Math.min((width - 2 * pad) / rangeX, (height - 2 * pad) / rangeY);
    var offX = pad + ((width  - 2 * pad) - rangeX * scale) / 2;
    var offY = pad + ((height - 2 * pad) - rangeY * scale) / 2;

    // ── Tile background ────────────────────────────────────────────────────
    var basemapKey = (document.getElementById('basemap') || {}).value || 'osm';
    var activeLeafletLayer = layers[basemapKey];
    var tileTemplate = activeLeafletLayer && activeLeafletLayer._url;
    var rawSd = (activeLeafletLayer && activeLeafletLayer.options && activeLeafletLayer.options.subdomains) || 'abc';
    var subdomains = typeof rawSd === 'string' ? rawSd.split('') : rawSd;
    if (tileTemplate) {
        var zoom = _pickZoom(minX, minY, maxX, maxY, 9);
        var tx0 = _lon2tile(minX, zoom), tx1 = _lon2tile(maxX, zoom);
        var ty0 = _lat2tile(maxY, zoom), ty1 = _lat2tile(minY, zoom);
        var tileFetches = [];
        for (var ty = ty0; ty <= ty1; ty++) {
            for (var tx = tx0; tx <= tx1; tx++) {
                tileFetches.push({ tx: tx, ty: ty, url: _tileUrl(tileTemplate, zoom, tx, ty, subdomains) });
            }
        }
        var tileImgs = await Promise.all(tileFetches.map(function(t) { return _loadTileImage(t.url); }));
        tileImgs.forEach(function(img, i) {
            if (!img) return;
            var t = tileFetches[i];
            var px0 = offX + (_tile2lon(t.tx,     zoom) - minX) * scale;
            var px1 = offX + (_tile2lon(t.tx + 1, zoom) - minX) * scale;
            var py0 = offY + (maxY - _tile2lat(t.ty,     zoom)) * scale;
            var py1 = offY + (maxY - _tile2lat(t.ty + 1, zoom)) * scale;
            ctx.drawImage(img, px0, py0, px1 - px0, py1 - py0);
        });
    }

    // ── Polygon ────────────────────────────────────────────────────────────
    ctx.beginPath();
    rings.forEach(function(ring) {
        var fx = offX + (ring[0][0] - minX) * scale;
        var fy = offY + (maxY - ring[0][1]) * scale;
        ctx.moveTo(fx, fy);
        for (var i = 1; i < ring.length; i++) {
            ctx.lineTo(offX + (ring[i][0] - minX) * scale, offY + (maxY - ring[i][1]) * scale);
        }
        ctx.closePath();
    });
    ctx.fillStyle = 'rgba(34,211,238,0.25)';
    ctx.strokeStyle = '#22d3ee';
    ctx.lineWidth = 2;
    ctx.fill('evenodd');
    ctx.stroke();

    return canvas;
}

// Snapshot captured at preview time — used by somSavePdf so PDF matches what was shown
var _reportSnapshot = null;

function somReverseGeocode(lat, lon) {
    var url = 'https://nominatim.openstreetmap.org/reverse?format=json&lat=' +
        lat + '&lon=' + lon + '&zoom=10&addressdetails=1';
    return fetch(url, { headers: { 'Accept-Language': lang === 'fr' ? 'fr' : 'en' } })
        .then(function(r) { return r.json(); })
        .then(function(data) {
            var a = data.address || {};
            var city = a.city || a.town || a.village || a.municipality || a.county || '';
            var province = a.state || a.province || '';
            var country = a.country || '';
            return [city, province, country].filter(Boolean).join(', ') || null;
        })
        .catch(function() { return null; });
}

export async function somShowPreview() {
    var tLang = T[lang] || T['en'];
    var now = new Date();
    var locale = lang === 'fr' ? 'fr-CA' : 'en-CA';

    var props = (somContext.feature && somContext.feature.properties) || {};
    var farmId       = String(props['idanpar'] || props['idpar'] || props['gid'] || '—');
    var cultureCode  = document.getElementById('somCulture').value || '—';
    var cultureLabel = (typeof GROPRO_LABELS !== 'undefined' && GROPRO_LABELS[cultureCode]) || cultureCode;
    var corgVal      = document.getElementById('somCorg').value   || '—';
    var phVal        = document.getElementById('somPh').value     || '—';
    var sableVal     = document.getElementById('somSable').value  || '—';
    var limonVal     = document.getElementById('somLimon').value  || '—';
    var argileVal    = document.getElementById('somArgile').value || '—';
    var cecVal       = document.getElementById('somCec').value    || '—';
    var ndviVal      = document.getElementById('somScenes').value || '—';
    var waterVal     = document.getElementById('somWater').value  || '—';
    var areaVal      = document.getElementById('somArea').value   || '—';
    var pedoVal      = document.getElementById('somPedo').value   || '—';
    var precipVal    = document.getElementById('somPrecip').value  || '—';

    // Compute bbox center for reverse geocoding
    var extentRaw = (document.getElementById('somExtent').value || '').split(',').map(Number);
    var hasBbox = extentRaw.length === 4 && extentRaw.every(isFinite);
    var centerLon = hasBbox ? (extentRaw[0] + extentRaw[2]) / 2 : null;
    var centerLat = hasBbox ? (extentRaw[1] + extentRaw[3]) / 2 : null;

    var geom = somContext.feature && somContext.feature.geometry;
    var polyDataUrl = geom ? (await somRenderPolygonCanvas(geom, 180, 180)).toDataURL('image/png') : null;
    var chartDataUrl = somChartInstance ? somChartInstance.toBase64Image('image/png', 1.0) : null;

    // Store snapshot immediately (locationStr filled in asynchronously below)
    _reportSnapshot = {
        tLang: tLang, now: now, locale: locale,
        farmId: farmId, cultureCode: cultureCode, cultureLabel: cultureLabel,
        corgVal: corgVal, phVal: phVal, sableVal: sableVal, limonVal: limonVal, argileVal: argileVal, cecVal: cecVal, ndviVal: ndviVal, waterVal: waterVal,
        areaVal: areaVal, pedoVal: pedoVal, precipVal: precipVal,
        polyDataUrl: polyDataUrl, chartDataUrl: chartDataUrl,
        locationStr: null
    };

    // Build preview HTML
    var rows = [
        [tLang['som-pdf-farm-id'],  farmId],
        [tLang['som-pdf-culture'],  cultureCode + ' — ' + cultureLabel],
        [tLang['som-pdf-area'],     areaVal + ' ha'],
        [tLang['som-pdf-pedo'],     pedoVal],
        [tLang['som-pdf-precip'],   precipVal !== '—' ? precipVal + ' mm' : '—'],
        [tLang['som-pdf-water'],    waterVal !== '—' ? waterVal + ' km' : '—'],
        [tLang['som-pdf-corg'],     corgVal + ' %'],
        [tLang['som-pdf-ph'],       phVal],
        [tLang['som-pdf-sable'],    sableVal + ' %'],
        [tLang['som-pdf-limon'],    limonVal + ' %'],
        [tLang['som-pdf-argile'],   argileVal + ' %'],
        [tLang['som-pdf-cec'],      cecVal + ' cmolc/kg'],
        [tLang['som-pdf-ndvi'],     ndviVal]
    ];
    var infoRowsHtml = rows.map(function(r) {
        return '<div class="som-report-info-row">' +
            '<span class="som-report-info-label">' + r[0] + '</span>' +
            '<span class="som-report-info-value">' + r[1] + '</span>' +
            '</div>';
    }).join('');

    var polyHtml = polyDataUrl
        ? '<div style="flex-shrink:0;display:flex;flex-direction:column;align-items:center;gap:.35rem">' +
            '<img src="' + polyDataUrl + '" width="120" height="120" style="border-radius:6px" alt="parcel">' +
            '<span id="somReportLocation" class="som-report-location">…</span>' +
          '</div>'
        : '';
    var chartHtml = chartDataUrl
        ? '<div class="som-report-chart-wrap"><img src="' + chartDataUrl + '" alt="chart"></div>'
        : '';

    var dateStr = now.toLocaleDateString(locale, { day: '2-digit', month: 'long', year: 'numeric' });

    document.getElementById('somReportBody').innerHTML =
        '<div class="som-report-page">' +
            '<div class="som-report-page__header">' +
                '<span class="som-report-page__header-title">' + tLang['som-pdf-title'] + '</span>' +
                '<span class="som-report-page__header-date">' + dateStr + '</span>' +
            '</div>' +
            '<div class="som-report-page__section">' +
                '<div class="som-report-section-title">' + tLang['som-pdf-farm-section'] + '</div>' +
                '<div class="som-report-farm-row">' +
                    polyHtml +
                    '<div class="som-report-info-table">' + infoRowsHtml + '</div>' +
                '</div>' +
            '</div>' +
            '<div class="som-report-page__section">' +
                '<div class="som-report-section-title">' + tLang['som-pdf-projection'] + '</div>' +
                chartHtml +
            '</div>' +
            '<div class="som-report-disclaimer">' + tLang['som-pdf-disclaimer'] + '</div>' +
            '<div class="som-report-footer">' +
                '<span>' + tLang['som-pdf-footer'] + '</span>' +
                '<span>' + now.toLocaleString(locale) + '</span>' +
            '</div>' +
        '</div>';

    document.getElementById('somReportModal').hidden = false;

    // Fetch location asynchronously — updates preview and snapshot once resolved
    if (centerLat !== null && centerLon !== null) {
        somReverseGeocode(centerLat, centerLon).then(function(locationStr) {
            var locEl = document.getElementById('somReportLocation');
            var display = locationStr || '—';
            if (locEl) locEl.textContent = display;
            if (_reportSnapshot) _reportSnapshot.locationStr = display;
        });
    } else {
        var locEl = document.getElementById('somReportLocation');
        if (locEl) locEl.textContent = '—';
    }
}

export function somClosePreview() {
    document.getElementById('somReportModal').hidden = true;
    document.getElementById('somReportBody').innerHTML = '';
    _reportSnapshot = null;
}

export function somSavePdf() {
    var jsPDF = window.jspdf && window.jspdf.jsPDF;
    if (!jsPDF) { alert('jsPDF not available'); return; }
    if (!_reportSnapshot) return;

    var s = _reportSnapshot;
    var tLang = s.tLang;
    var doc = new jsPDF({ orientation: 'portrait', unit: 'mm', format: 'a4' });

    // ── Header ────────────────────────────────────────────────────────────────
    doc.setFillColor(19, 21, 31);
    doc.rect(0, 0, 210, 22, 'F');
    doc.setFont('helvetica', 'bold');
    doc.setFontSize(11);
    doc.setTextColor(232, 234, 240);
    doc.text(tLang['som-pdf-title'], 12, 14);
    doc.setFont('helvetica', 'normal');
    doc.setFontSize(8);
    doc.setTextColor(139, 146, 168);
    doc.text(s.now.toLocaleDateString(s.locale, { day: '2-digit', month: 'long', year: 'numeric' }), 198, 14, { align: 'right' });

    // ── Farm section ──────────────────────────────────────────────────────────
    var y = 30;
    doc.setFont('helvetica', 'bold');
    doc.setFontSize(10);
    doc.setTextColor(34, 211, 238);
    doc.text(tLang['som-pdf-farm-section'], 12, y);
    y += 6;

    if (s.polyDataUrl) {
        doc.addImage(s.polyDataUrl, 'PNG', 12, y, 55, 55);
        // Location name under polygon
        if (s.locationStr && s.locationStr !== '—') {
            doc.setFont('helvetica', 'italic');
            doc.setFontSize(7);
            doc.setTextColor(100, 116, 139);
            doc.text(s.locationStr, 39.5, y + 58, { align: 'center', maxWidth: 55 });
        }
    }

    // Left column: general farm info (next to polygon image)
    var leftRows = [
        [tLang['som-pdf-farm-id'],  s.farmId],
        [tLang['som-pdf-culture'],  s.cultureCode + ' — ' + s.cultureLabel],
        [tLang['som-pdf-area'],     s.areaVal + ' ha'],
        [tLang['som-pdf-pedo'],     s.pedoVal],
        [tLang['som-pdf-precip'],   s.precipVal !== '—' ? s.precipVal + ' mm' : '—'],
        [tLang['som-pdf-water'],    s.waterVal && s.waterVal !== '—' ? s.waterVal + ' km' : (s.waterVal || '—')]
    ];
    // Right column: soil properties
    var rightRows = [
        [tLang['som-pdf-corg'],   s.corgVal + ' %'],
        [tLang['som-pdf-ph'],     s.phVal],
        [tLang['som-pdf-sable'],  s.sableVal + ' %'],
        [tLang['som-pdf-limon'],  s.limonVal + ' %'],
        [tLang['som-pdf-argile'], s.argileVal + ' %'],
        [tLang['som-pdf-cec'],    s.cecVal + ' cmolc/kg'],
        [tLang['som-pdf-ndvi'],   s.ndviVal || '—']
    ];
    var rowSpacing = 9;
    doc.setFontSize(8.5);
    leftRows.forEach(function(row, i) {
        var ry = y + 6 + i * rowSpacing;
        doc.setFont('helvetica', 'bold');
        doc.setTextColor(155, 182, 210);
        doc.text(row[0], 72, ry);
        doc.setFont('helvetica', 'normal');
        doc.setTextColor(30, 40, 60);
        doc.text(String(row[1]), 72, ry + 4.5, { maxWidth: 58 });
    });
    rightRows.forEach(function(row, i) {
        var ry = y + 6 + i * rowSpacing;
        doc.setFont('helvetica', 'bold');
        doc.setTextColor(155, 182, 210);
        doc.text(row[0], 134, ry);
        doc.setFont('helvetica', 'normal');
        doc.setTextColor(30, 40, 60);
        doc.text(String(row[1]), 134, ry + 4.5, { maxWidth: 60 });
    });
    y += 6 + rightRows.length * rowSpacing + 6;

    // ── SOM Projection section ────────────────────────────────────────────────
    doc.setDrawColor(41, 71, 102);
    doc.line(12, y, 198, y);
    y += 7;
    doc.setFont('helvetica', 'bold');
    doc.setFontSize(10);
    doc.setTextColor(34, 211, 238);
    doc.text(tLang['som-pdf-projection'], 12, y);
    y += 6;

    if (s.chartDataUrl) {
        var cw = (somChartInstance && somChartInstance.canvas.width)  || 440;
        var ch = (somChartInstance && somChartInstance.canvas.height) || 180;
        var chartW = 186;
        var chartH = Math.round(chartW * ch / cw);
        doc.addImage(s.chartDataUrl, 'PNG', 12, y, chartW, chartH);
        y += chartH + 5;
    }

    doc.setFont('helvetica', 'italic');
    doc.setFontSize(7.5);
    doc.setTextColor(155, 182, 210);
    doc.text(tLang['som-pdf-disclaimer'], 12, y, { maxWidth: 186 });

    // ── Footer ────────────────────────────────────────────────────────────────
    doc.setDrawColor(41, 71, 102);
    doc.line(12, 285, 198, 285);
    doc.setFont('helvetica', 'normal');
    doc.setFontSize(7);
    doc.setTextColor(155, 182, 210);
    doc.text(tLang['som-pdf-footer'], 12, 291);
    doc.text(s.now.toLocaleString(s.locale), 198, 291, { align: 'right' });

    doc.save('Agri-SDSS_SOM_' + s.farmId + '_' + s.now.toISOString().slice(0, 10) + '.pdf');
    somClosePreview();
}



export async function somAutoGenCorg() {
    var btn = document.getElementById('somCorgGen');
    var status = document.getElementById('somCorgStatus');
    var tLang = T[lang] || T['en'];
    btn.disabled = true;
    status.textContent = tLang['som-loading'];
    status.className = 'som-field__status';
    try {
        var r = await fetch('/raster-api/cog/statistics?url=file:///data/corg_fr_siigsol_cog.tif&nodata=nan&indexes=1', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(somContext.feature)
        });
        var data = await r.json();
        var b1 = data.properties && data.properties.statistics && data.properties.statistics.b1;
        var mean = b1 ? b1.mean : (data['1'] ? data['1'].mean : null);
        if (mean != null) {
            document.getElementById('somCorg').value = (+mean).toFixed(2);
            status.textContent = '';
        } else {
            document.getElementById('somCorg').value = '';
            status.textContent = lang === 'fr' ? 'Aucune donnée pour cette zone' : 'No data for this area';
        }
    } catch(e) {
        status.textContent = tLang['som-error'];
        status.className = 'som-field__status error';
    } finally { btn.disabled = false; }
}

export async function somAutoGenPh() {
    var btn = document.getElementById('somPhGen');
    var status = document.getElementById('somPhStatus');
    var tLang = T[lang] || T['en'];
    btn.disabled = true;
    status.textContent = tLang['som-loading'];
    status.className = 'som-field__status';
    try {
        var r = await fetch('/raster-api/cog/statistics?url=file:///data/ph_fr_siigsol_cog.tif&nodata=nan&indexes=1', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(somContext.feature)
        });
        var data = await r.json();
        var b1 = data.properties && data.properties.statistics && data.properties.statistics.b1;
        var mean = b1 ? b1.mean : (data['1'] ? data['1'].mean : null);
        if (mean != null) {
            document.getElementById('somPh').value = (+mean).toFixed(2);
            status.textContent = '';
        } else {
            document.getElementById('somPh').value = '';
            status.textContent = lang === 'fr' ? 'Aucune donnée pour cette zone' : 'No data for this area';
        }
    } catch(e) {
        status.textContent = tLang['som-error'];
        status.className = 'som-field__status error';
    } finally { btn.disabled = false; }
}

export async function somAutoGenSable() {
    var btn = document.getElementById('somSableGen');
    var status = document.getElementById('somSableStatus');
    var tLang = T[lang] || T['en'];
    btn.disabled = true;
    status.textContent = tLang['som-loading'];
    status.className = 'som-field__status';
    try {
        var r = await fetch('/raster-api/cog/statistics?url=file:///data/sable_fr_siigsol_cog.tif&nodata=nan&indexes=1', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(somContext.feature)
        });
        var data = await r.json();
        var b1 = data.properties && data.properties.statistics && data.properties.statistics.b1;
        var mean = b1 ? b1.mean : (data['1'] ? data['1'].mean : null);
        if (mean != null) {
            document.getElementById('somSable').value = (+mean).toFixed(2);
            status.textContent = '';
        } else {
            document.getElementById('somSable').value = '';
            status.textContent = lang === 'fr' ? 'Aucune donnée pour cette zone' : 'No data for this area';
        }
    } catch(e) {
        status.textContent = tLang['som-error'];
        status.className = 'som-field__status error';
    } finally { btn.disabled = false; }
}

export async function somAutoGenLimon() {
    var btn = document.getElementById('somLimonGen');
    var status = document.getElementById('somLimonStatus');
    var tLang = T[lang] || T['en'];
    btn.disabled = true;
    status.textContent = tLang['som-loading'];
    status.className = 'som-field__status';
    try {
        var r = await fetch('/raster-api/cog/statistics?url=file:///data/limon_fr_siigsol_cog.tif&nodata=nan&indexes=1', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(somContext.feature)
        });
        var data = await r.json();
        var b1 = data.properties && data.properties.statistics && data.properties.statistics.b1;
        var mean = b1 ? b1.mean : (data['1'] ? data['1'].mean : null);
        if (mean != null) {
            document.getElementById('somLimon').value = (+mean).toFixed(2);
            status.textContent = '';
        } else {
            document.getElementById('somLimon').value = '';
            status.textContent = lang === 'fr' ? 'Aucune donnée pour cette zone' : 'No data for this area';
        }
    } catch(e) {
        status.textContent = tLang['som-error'];
        status.className = 'som-field__status error';
    } finally { btn.disabled = false; }
}

export async function somAutoGenArgile() {
    var btn = document.getElementById('somArgileGen');
    var status = document.getElementById('somArgileStatus');
    var tLang = T[lang] || T['en'];
    btn.disabled = true;
    status.textContent = tLang['som-loading'];
    status.className = 'som-field__status';
    try {
        var r = await fetch('/raster-api/cog/statistics?url=file:///data/argile_fr_siigsol_cog.tif&nodata=nan&indexes=1', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(somContext.feature)
        });
        var data = await r.json();
        var b1 = data.properties && data.properties.statistics && data.properties.statistics.b1;
        var mean = b1 ? b1.mean : (data['1'] ? data['1'].mean : null);
        if (mean != null) {
            document.getElementById('somArgile').value = (+mean).toFixed(2);
            status.textContent = '';
        } else {
            document.getElementById('somArgile').value = '';
            status.textContent = lang === 'fr' ? 'Aucune donnée pour cette zone' : 'No data for this area';
        }
    } catch(e) {
        status.textContent = tLang['som-error'];
        status.className = 'som-field__status error';
    } finally { btn.disabled = false; }
}

export async function somAutoGenCec() {
    var btn = document.getElementById('somCecGen');
    var status = document.getElementById('somCecStatus');
    var tLang = T[lang] || T['en'];
    btn.disabled = true;
    status.textContent = tLang['som-loading'];
    status.className = 'som-field__status';
    try {
        var r = await fetch('/raster-api/cog/statistics?url=file:///data/cec_fr_siigsol_cog.tif&nodata=nan&indexes=1', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(somContext.feature)
        });
        var data = await r.json();
        var b1 = data.properties && data.properties.statistics && data.properties.statistics.b1;
        var mean = b1 ? b1.mean : (data['1'] ? data['1'].mean : null);
        if (mean != null) {
            document.getElementById('somCec').value = (+mean).toFixed(2);
            status.textContent = '';
        } else {
            document.getElementById('somCec').value = '';
            status.textContent = lang === 'fr' ? 'Aucune donnée pour cette zone' : 'No data for this area';
        }
    } catch(e) {
        status.textContent = tLang['som-error'];
        status.className = 'som-field__status error';
    } finally { btn.disabled = false; }
}

// Search STAC by bbox intersection, optionally filter by start/end date prefix.
// The datetime query param is not supported on the pgSTAC items endpoint, so we
// fetch up to 20 intersecting items and match dates client-side.
async function _searchStacItem(collection, bb, startDate, endDate) {
    var url = '/stac-api/collections/' + collection + '/items?bbox='
        + bb.map(function(v) { return (+v).toFixed(4); }).join(',')
        + '&limit=20';
    var r = await fetch(url);
    if (!r.ok) return null;
    var fc = await r.json();
    var items = fc.features || [];
    if (!startDate) return items.length > 0 ? items[0] : null;
    return items.find(function(item) {
        var p = item.properties || {};
        return p.start_datetime && p.start_datetime.startsWith(startDate)
            && p.end_datetime   && p.end_datetime.startsWith(endDate);
    }) || null;
}

export async function somAutoGenScenes() {
    var btn = document.getElementById('somScenesGen');
    var status = document.getElementById('somScenesStatus');
    var tLang = T[lang] || T['en'];
    btn.disabled = true;
    status.textContent = tLang['som-loading'];
    status.className = 'som-field__status';
    try {
        var geom = somContext.feature && somContext.feature.geometry;
        if (!geom) throw new Error('No feature geometry');
        var ym = (somContext.collectionId || '').match(/_an_(\d{4})/) ||
                 (somContext.collectionId || '').match(/[_-](20\d{2})[_-]/) ||
                 (somContext.collectionId || '').match(/(20\d{2})/);
        var year = ym ? ym[1] : String(new Date().getFullYear());
        var startDate = year + '-06-01';
        var endDate = year + '-08-31';
        var cachedItem = await _searchStacItem('sentinel2_eo_products', _geomBbox(geom), startDate, endDate);
        var mean;
        if (cachedItem) {
            mean = cachedItem.assets &&
                   cachedItem.assets.ndvi &&
                   cachedItem.assets.ndvi.statistics &&
                   cachedItem.assets.ndvi.statistics['1'] &&
                   cachedItem.assets.ndvi.statistics['1'].mean;
        } else {
            var r = await fetch('/process-api/processes/sentinel-fetch/execution?f=json', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    inputs: {
                        farm_geometry: geom,
                        temporal_extent: [startDate, endDate],
                        output_products: ['ndvi'],
                        aggregation_method: 'median',
                        cloud_cover_max: 20
                    }
                })
            });
            if (!r.ok) throw new Error('HTTP ' + r.status);
            var data = await r.json();
            mean = data.value &&
                   data.value.stac_item &&
                   data.value.stac_item.assets &&
                   data.value.stac_item.assets.ndvi &&
                   data.value.stac_item.assets.ndvi.statistics &&
                   data.value.stac_item.assets.ndvi.statistics['1'] &&
                   data.value.stac_item.assets.ndvi.statistics['1'].mean;
        }
        if (mean == null) throw new Error('No NDVI mean in response');
        document.getElementById('somScenes').value = (+mean).toFixed(3);
        status.textContent = '';
    } catch(e) {
        status.textContent = tLang['som-error'] + ': ' + e.message;
        status.className = 'som-field__status error';
    } finally { btn.disabled = false; }
}

export async function somAutoGenElevation() {
    var btn = document.getElementById('somElevationGen');
    var status = document.getElementById('somElevationStatus');
    var tLang = T[lang] || T['en'];
    btn.disabled = true;
    status.textContent = tLang['som-loading'];
    status.className = 'som-field__status';
    try {
        var b = somContext.layer.getBounds();
        var cachedItem = await _searchStacItem('lidar_quebec', [b.getWest(), b.getSouth(), b.getEast(), b.getNorth()], null, null);
        var mean;
        if (cachedItem) {
            mean = cachedItem.assets &&
                   cachedItem.assets.dtm &&
                   cachedItem.assets.dtm.statistics &&
                   cachedItem.assets.dtm.statistics.mean != null
                   ? cachedItem.assets.dtm.statistics.mean : null;
        } else {
            var bboxGeom = {
                type: 'Polygon',
                coordinates: [[[b.getWest(), b.getSouth()], [b.getEast(), b.getSouth()],
                               [b.getEast(), b.getNorth()], [b.getWest(), b.getNorth()],
                               [b.getWest(), b.getSouth()]]]
            };
            var r = await fetch('/process-api/processes/lidar-fetch/execution?f=json', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ inputs: { farm_geometry: bboxGeom, products: ['dtm'] } })
            });
            if (!r.ok) throw new Error('HTTP ' + r.status);
            var data = await r.json();
            var dtmAsset = data.assets && data.assets.dtm;
            if (!dtmAsset) throw new Error(lang === 'fr' ? 'Aucun actif DTM dans la réponse' : 'No DTM asset in response');
            mean = dtmAsset.statistics && dtmAsset.statistics.mean != null ? dtmAsset.statistics.mean : null;
        }
        if (mean == null) throw new Error(lang === 'fr' ? 'Aucune donnée d\'élévation' : 'No elevation data');
        document.getElementById('somElevation').value = (+mean).toFixed(1);
        status.textContent = '';
    } catch(e) {
        status.textContent = tLang['som-error'] + ': ' + e.message;
        status.className = 'som-field__status error';
    } finally { btn.disabled = false; }
}

function _polygonCentroid(geom) {
    var ring = geom.type === 'MultiPolygon'
        ? geom.coordinates[0][0]
        : geom.coordinates[0];
    var n = ring.length - 1;
    var sumX = 0, sumY = 0;
    for (var i = 0; i < n; i++) { sumX += ring[i][0]; sumY += ring[i][1]; }
    return [sumX / n, sumY / n];
}

function _dist2(a, b) {
    var dx = a[0] - b[0], dy = a[1] - b[1];
    return dx * dx + dy * dy;
}

export async function somAutoGenPrecip() {
    var btn = document.getElementById('somPrecipGen');
    var status = document.getElementById('somPrecipStatus');
    var tLang = T[lang] || T['en'];
    btn.disabled = true;
    status.textContent = tLang['som-loading'];
    status.className = 'som-field__status';
    try {
        var geom = somContext.feature && somContext.feature.geometry;
        if (!geom) throw new Error(lang === 'fr' ? 'Aucune géométrie de parcelle' : 'No feature geometry');

        var end = new Date();
        end.setDate(end.getDate() - 1);
        var start = new Date(end);
        start.setDate(start.getDate() - 6);

        var r = await fetch('/process-api/processes/msc-observations/execution?f=json', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                inputs: {
                    location_type: 'polygon',
                    polygon: geom,
                    collection: 'climate-daily',
                    variables: ['pr'],
                    start_date: start.toISOString().slice(0, 10),
                    end_date: end.toISOString().slice(0, 10)
                }
            })
        });
        if (!r.ok) throw new Error('HTTP ' + r.status);
        var result = await r.json();
        var fc = result.value;
        if (!fc || !fc.features || fc.features.length === 0) {
            status.textContent = tLang['som-precip-none'];
            status.className = 'som-field__status error';
            return;
        }

        var centroid = _polygonCentroid(geom);
        var sorted = fc.features.slice().sort(function(a, b) {
            return _dist2(a.geometry.coordinates, centroid) - _dist2(b.geometry.coordinates, centroid);
        });

        var chosen = null, total = 0, count = 0;
        for (var i = 0; i < sorted.length; i++) {
            var f = sorted[i];
            var prData = f.properties && f.properties.data && f.properties.data.pr;
            var t = 0, c = 0;
            (prData || []).forEach(function(v) {
                if (v != null) { t += v; c++; }
            });
            if (c > 0) { chosen = f; total = t; count = c; break; }
        }

        if (!chosen) {
            status.textContent = tLang['som-precip-nodata'];
            status.className = 'som-field__status error';
            return;
        }

        document.getElementById('somPrecip').value = total.toFixed(1);
        var name = chosen.properties.station_name || chosen.properties.station_id || '?';
        status.textContent = name + ' — ' + count + '/7 ' + tLang['som-precip-days'];
        status.className = 'som-field__status';
    } catch(e) {
        status.textContent = tLang['som-error'] + ': ' + e.message;
        status.className = 'som-field__status error';
    } finally {
        btn.disabled = false;
    }
}

export async function somAutoGenPedo() {
    var btn = document.getElementById('somPedoGen');
    var status = document.getElementById('somPedoStatus');
    var tLang = T[lang] || T['en'];
    btn.disabled = true;
    status.textContent = tLang['som-loading'];
    status.className = 'som-field__status';
    try {
        var geom = somContext.feature && somContext.feature.geometry;
        if (!geom) throw new Error('No feature geometry');
        var r = await fetch('/vector-api/pedo-coverage', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ geometry: geom })
        });
        if (!r.ok) throw new Error('HTTP ' + r.status);
        var data = await r.json();
        if (data.description == null) {
            document.getElementById('somPedo').value = '';
            status.textContent = tLang['som-pedo-none'];
            status.className = 'som-field__status';
        } else {
            document.getElementById('somPedo').value = data.description;
            status.textContent = data.count > 1 ? tLang['som-pedo-multi'] : '';
            status.className = 'som-field__status';
        }
    } catch(e) {
        status.textContent = tLang['som-error'] + ': ' + e.message;
        status.className = 'som-field__status error';
    } finally { btn.disabled = false; }
}

export async function somAutoGenWater() {
    var btn = document.getElementById('somWaterGen');
    var status = document.getElementById('somWaterStatus');
    var tLang = T[lang] || T['en'];
    btn.disabled = true;
    status.textContent = tLang['som-loading'];
    status.className = 'som-field__status';
    try {
        var geom = somContext.feature && somContext.feature.geometry;
        if (!geom) throw new Error('No feature geometry');
        var r = await fetch('/vector-api/water-distance', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ geometry: geom })
        });
        if (!r.ok) throw new Error('HTTP ' + r.status);
        var data = await r.json();
        if (data.distance_m == null) throw new Error(lang === 'fr' ? 'Aucun cours d\'eau à proximité' : 'No water features found nearby');
        document.getElementById('somWater').value = (data.distance_m / 1000).toFixed(2);
        status.textContent = '';
    } catch(e) {
        status.textContent = tLang['som-error'] + ': ' + e.message;
        status.className = 'som-field__status error';
    } finally { btn.disabled = false; }
}

export async function somRunAnalysis() {
    var btn = document.getElementById('somRun');
    var status = document.getElementById('somRunStatus');
    var tLang = T[lang] || T['en'];

    if (!somValidateFields()) {
        status.textContent = tLang['som-fields-required'];
        status.className = 'som-run__status som-run--error';
        return;
    }
    status.className = 'som-run__status';

    btn.disabled = true;
    status.textContent = tLang['som-running'];
    try {
        var r = await fetch('/process-api/', { method: 'GET' });
        if (!r.ok) throw new Error(tLang['som-run-error'] + ' (HTTP ' + r.status + ')');
        if (typeof Chart === 'undefined') throw new Error('Chart.js not loaded');
        var now = new Date();
        var yr1 = now.getFullYear() + 1, yr5 = now.getFullYear() + 5, yr10 = now.getFullYear() + 10;
        var seed = (now.getMonth() + 1) * 0.03 + now.getDay() * 0.01;
        document.getElementById('somResults').hidden = false;
        document.getElementById('somExportPdf').hidden = false;
        if (somChartInstance) { somChartInstance.destroy(); setSomChartInstance(null); }
        setSomChartInstance(new Chart(document.getElementById('somChart'), {
            type: 'bar',
            data: {
                labels: [String(yr1), String(yr5), String(yr10)],
                datasets: [{
                    label: tLang['som-results-title'],
                    data: [+(2.40 + seed).toFixed(2), +(2.80 + seed).toFixed(2), +(3.30 + seed).toFixed(2)],
                    backgroundColor: ['#22d3ee88', '#22d3eeaa', '#22d3ee'],
                    borderColor: ['#22d3ee', '#22d3ee', '#22d3ee'],
                    borderWidth: 1, borderRadius: 4
                }]
            },
            options: {
                responsive: true, maintainAspectRatio: false,
                plugins: { legend: { display: false } },
                scales: {
                    y: { min: 2, max: 4, ticks: { color: '#9bb6d2', font: { size: 11 } }, grid: { color: '#294766' } },
                    x: { ticks: { color: '#9bb6d2', font: { size: 11 } }, grid: { display: false } }
                }
            }
        }));
        status.textContent = tLang['som-run-ok'];
        status.className = 'som-run__status ok';
    } catch(e) {
        status.textContent = (tLang['som-run-error'] || 'Error') + ': ' + e.message;
        status.className = 'som-run__status error';
    } finally { btn.disabled = false; }
}
