// catalog.js — Data / Données catalog modal
// Read-only browser: PostGIS, Parquet/DuckDB, STAC, OGC Processes

var _loaded = { vector: false, stac: false, processes: false };

function _tL() {
    return (window.T && window.T[window.lang]) || (window.T && window.T['en']) || {};
}

// ── Tab switching ─────────────────────────────────────────────────────────────
function _switchTab(name) {
    var panels = {
        vector:    document.getElementById('catalogPanelVector'),
        stac:      document.getElementById('catalogPanelStac'),
        processes: document.getElementById('catalogPanelProcesses'),
    };
    var tabs = {
        vector:    document.getElementById('catalogTabVector'),
        stac:      document.getElementById('catalogTabStac'),
        processes: document.getElementById('catalogTabProcs'),
    };

    Object.keys(panels).forEach(function(k) {
        panels[k].hidden = (k !== name);
        tabs[k].classList.toggle('som-tab--active', k === name);
        tabs[k].setAttribute('aria-selected', String(k === name));
    });

    if (name === 'vector'    && !_loaded.vector)    _loadVector();
    if (name === 'stac'      && !_loaded.stac)      _loadStac();
    if (name === 'processes' && !_loaded.processes)  _loadProcesses();
}

// ── DOM helpers ───────────────────────────────────────────────────────────────
function _makeCard(title, description, badgeKey) {
    var t = _tL();
    var card = document.createElement('div');
    card.className = 'catalog-card';

    var header = document.createElement('div');
    header.className = 'catalog-card__header';

    var name = document.createElement('span');
    name.className = 'catalog-card__name';
    name.textContent = title;

    var badge = document.createElement('span');
    badge.className = 'catalog-badge catalog-badge--' + badgeKey;
    badge.textContent = t['catalog-badge-' + badgeKey] || badgeKey;

    header.appendChild(name);
    header.appendChild(badge);

    var desc = document.createElement('p');
    desc.className = 'catalog-card__desc';
    desc.textContent = description || t['catalog-no-desc'] || '';

    card.appendChild(header);
    card.appendChild(desc);
    return card;
}

function _setError(statusEl, message) {
    var t = _tL();
    statusEl.textContent = (t['catalog-error'] || 'Error: ') + message;
    statusEl.classList.add('catalog-status--error');
    statusEl.hidden = false;
}

function _clearStatus(statusEl) {
    statusEl.textContent = '';
    statusEl.hidden = true;
}

function _setEmpty(statusEl) {
    statusEl.textContent = _tL()['catalog-empty'] || 'No data found.';
    statusEl.hidden = false;
}

// ── Vector tab — PostGIS + Parquet fetched in parallel ────────────────────────
async function _loadVector() {
    _loaded.vector = true;
    var t = _tL();

    var pgStatus = document.getElementById('catalogPostgisStatus');
    var pqStatus = document.getElementById('catalogParquetStatus');
    var pgList   = document.getElementById('catalogPostgisList');
    var pqList   = document.getElementById('catalogParquetList');

    pgStatus.textContent = t['catalog-loading'] || 'Loading…';
    pgStatus.hidden = false;
    pqStatus.textContent = t['catalog-loading'] || 'Loading…';
    pqStatus.hidden = false;

    var [pgResult, pqResult] = await Promise.allSettled([
        fetch('/mos-vector/postgis/collections?f=json&limit=500')
            .then(function(r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); }),
        fetch('/mos-vector/parquet/collections?f=json')
            .then(function(r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
    ]);

    if (pgResult.status === 'fulfilled') {
        var pgColls = Array.isArray(pgResult.value.collections) ? pgResult.value.collections : [];
        _clearStatus(pgStatus);
        if (!pgColls.length) { _setEmpty(pgStatus); }
        else { pgColls.forEach(function(c) { pgList.appendChild(_makeCard(c.title || c.id, c.description, 'postgis')); }); }
    } else {
        _setError(pgStatus, pgResult.reason.message);
    }

    if (pqResult.status === 'fulfilled') {
        var pqColls = Array.isArray(pqResult.value.collections) ? pqResult.value.collections : [];
        _clearStatus(pqStatus);
        if (!pqColls.length) { _setEmpty(pqStatus); }
        else { pqColls.forEach(function(c) { pqList.appendChild(_makeCard(c.title || c.id, c.description, 'parquet')); }); }
    } else {
        _setError(pqStatus, pqResult.reason.message);
    }
}

// ── STAC tab ──────────────────────────────────────────────────────────────────
async function _loadStac() {
    _loaded.stac = true;
    var t = _tL();
    var statusEl = document.getElementById('catalogStacStatus');
    var listEl   = document.getElementById('catalogStacList');

    statusEl.textContent = t['catalog-loading'] || 'Loading…';
    statusEl.hidden = false;

    try {
        var r = await fetch('/mos-stac/collections?f=json');
        if (!r.ok) throw new Error('HTTP ' + r.status);
        var data = await r.json();
        var colls = Array.isArray(data.collections) ? data.collections : [];

        _clearStatus(statusEl);
        if (!colls.length) { _setEmpty(statusEl); return; }

        colls.forEach(function(c) {
            var temporal = '';
            try {
                var interval = c.extent.temporal.interval;
                if (Array.isArray(interval) && Array.isArray(interval[0])) {
                    var start = interval[0][0] ? interval[0][0].slice(0, 10) : '?';
                    var end   = interval[0][1] ? interval[0][1].slice(0, 10) : 'present';
                    temporal = start + ' → ' + end;
                }
            } catch(_) {}

            var card = _makeCard(c.title || c.id, c.description, 'stac');
            if (temporal) {
                var tempEl = document.createElement('p');
                tempEl.className = 'catalog-card__temporal';
                tempEl.textContent = (t['catalog-temporal'] || 'Temporal: ') + temporal;
                card.appendChild(tempEl);
            }
            listEl.appendChild(card);
        });
    } catch(e) {
        _setError(statusEl, e.message);
    }
}

// ── Processes tab ─────────────────────────────────────────────────────────────
async function _loadProcesses() {
    _loaded.processes = true;
    var t = _tL();
    var statusEl = document.getElementById('catalogProcsStatus');
    var listEl   = document.getElementById('catalogProcsList');

    statusEl.textContent = t['catalog-loading'] || 'Loading…';
    statusEl.hidden = false;

    try {
        var r = await fetch('/mos-pygeoapi/processes?f=json');
        if (!r.ok) throw new Error('HTTP ' + r.status);
        var data = await r.json();
        var procs = Array.isArray(data.processes) ? data.processes
                  : Array.isArray(data) ? data : [];

        _clearStatus(statusEl);
        if (!procs.length) { _setEmpty(statusEl); return; }

        procs.forEach(function(p) {
            var desc = typeof p.description === 'object' ? (p.description[window.lang] || p.description['en'] || '') : (p.description || '');
            var title = typeof p.title === 'object' ? (p.title[window.lang] || p.title['en'] || p.id) : (p.title || p.id);
            listEl.appendChild(_makeCard(title, desc, 'process'));
        });
    } catch(e) {
        _setError(statusEl, e.message);
    }
}

// ── Public API ────────────────────────────────────────────────────────────────
export function openCatalogModal() {
    _loaded.vector = false;
    _loaded.stac = false;
    _loaded.processes = false;

    ['catalogPostgisList', 'catalogParquetList', 'catalogStacList', 'catalogProcsList'].forEach(function(id) {
        document.getElementById(id).innerHTML = '';
    });

    _switchTab('vector');
    document.getElementById('catalogModal').hidden = false;
    document.getElementById('catalogClose').focus();
}

export function closeCatalogModal() {
    document.getElementById('catalogModal').hidden = true;
}

export function initCatalogTabs() {
    document.getElementById('catalogTabVector').addEventListener('click', function() { _switchTab('vector'); });
    document.getElementById('catalogTabStac').addEventListener('click', function() { _switchTab('stac'); });
    document.getElementById('catalogTabProcs').addEventListener('click', function() { _switchTab('processes'); });

    document.getElementById('catalogModal').addEventListener('keydown', function(e) {
        if (e.key === 'Escape') closeCatalogModal();
    });
}
