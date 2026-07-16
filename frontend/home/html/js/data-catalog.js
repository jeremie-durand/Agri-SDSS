// data-catalog.js — /data page: renders the curated registry (js/catalog.json)
// joined with the live collection lists from the backend APIs.
//
// Curated metadata (names, descriptions, licenses, sources) comes from
// catalog.json; the live APIs contribute existence status (collection count,
// year range). Live collections matching no registry entry are listed in an
// auto-generated "Other datasets in the backend" section (data APIs only —
// processes are services, not datasets, and are listed on /services).

const ENDPOINTS = {
    postgis: '/vector-api/postgis/collections?f=json&limit=500',
    parquet: '/vector-api/parquet/collections?f=json',
    stac:    '/stac-api/collections?f=json',
    process: '/process-api/processes?f=json',
};

const DATA_APIS = ['postgis', 'parquet', 'stac'];

const L = {
    en: {
        live: 'in the backend', collection: 'collection', collections: 'collections',
        notIngested: 'not ingested', unknown: 'status unavailable — API offline',
        external: 'external source — fetched on demand',
        otherBadge: 'Backend', license: 'License', source: 'Source',
        loadError: 'Unable to load the data catalog.',
        apiName: { postgis: 'PostGIS', parquet: 'GeoParquet', stac: 'STAC' },
        catBadge: { crop: 'Crop monitoring', soil: 'Soil properties', climate: 'Meteorology', other: 'Backend' },
    },
    fr: {
        live: 'dans le backend', collection: 'collection', collections: 'collections',
        notIngested: 'non ingéré', unknown: 'statut indisponible — API hors ligne',
        external: 'source externe — accès à la demande',
        otherBadge: 'Backend', license: 'Licence', source: 'Source',
        loadError: 'Impossible de charger le catalogue de données.',
        apiName: { postgis: 'PostGIS', parquet: 'GeoParquet', stac: 'STAC' },
        catBadge: { crop: 'Suivi des cultures', soil: 'Pédologie', climate: 'Météorologie', other: 'Backend' },
    },
};

let state = null;

function getLang() {
    return localStorage.getItem('sdss-lang') || 'fr';
}

function pick(value, lang) {
    if (value && typeof value === 'object') return value[lang] || value.en || value.fr || '';
    return value || '';
}

function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
}

// ── Fetching ──────────────────────────────────────────────────────────────────

async function fetchJson(url) {
    const r = await fetch(url, { cache: 'no-store' });
    if (!r.ok) throw new Error('HTTP ' + r.status);
    return r.json();
}

async function fetchRegistry() {
    return fetchJson('/js/catalog.json');
}

function stacTemporalYears(c) {
    try {
        const interval = c.extent.temporal.interval;
        if (Array.isArray(interval) && Array.isArray(interval[0])) {
            const start = interval[0][0] ? Number(interval[0][0].slice(0, 4)) : null;
            const end = interval[0][1] ? Number(interval[0][1].slice(0, 4)) : null;
            return { start, end };
        }
    } catch (_) { /* extent missing or malformed */ }
    return { start: null, end: null };
}

function normalize(api, json) {
    const items = Array.isArray(json.collections) ? json.collections
                : Array.isArray(json.processes) ? json.processes : [];
    return items.map((c) => ({
        api,
        id: String(c.id || ''),
        title: typeof c.title === 'object' ? pick(c.title, getLang()) : (c.title || c.id || ''),
        description: typeof c.description === 'object' ? pick(c.description, getLang()) : (c.description || ''),
        temporal: api === 'stac' ? stacTemporalYears(c) : { start: null, end: null },
    }));
}

async function fetchLive() {
    const apis = Object.keys(ENDPOINTS);
    const results = await Promise.allSettled(apis.map((api) => fetchJson(ENDPOINTS[api])));
    const records = [];
    const apiStatus = {};
    results.forEach((result, i) => {
        const api = apis[i];
        if (result.status === 'fulfilled') {
            apiStatus[api] = 'ok';
            records.push(...normalize(api, result.value));
        } else {
            apiStatus[api] = 'down';
            console.warn('data-catalog: ' + api + ' unavailable — ' + result.reason.message);
        }
    });
    return { records, apiStatus };
}

// ── Join ──────────────────────────────────────────────────────────────────────

function compileMatcher(m) {
    try {
        return { api: m.api, re: new RegExp(m.idPattern) };
    } catch (e) {
        console.warn('data-catalog: bad idPattern "' + m.idPattern + '" — ' + e.message);
        return null;
    }
}

function joinCatalog(registry, live) {
    const claimed = new Set();
    const blockMatches = new Map();

    for (const entry of registry.datasets) {
        for (const block of entry.datasets) {
            const matchers = (block.match || []).map(compileMatcher).filter(Boolean);
            const matches = live.records.filter((r) =>
                matchers.some((m) => m.api === r.api && m.re.test(r.id)));
            matches.forEach((r) => claimed.add(r.api + ':' + r.id));
            blockMatches.set(block, matches);
        }
    }

    const excludes = (registry.exclude || []).map(compileMatcher).filter(Boolean);
    const others = live.records.filter((r) =>
        DATA_APIS.includes(r.api) &&
        !claimed.has(r.api + ':' + r.id) &&
        !excludes.some((m) => m.api === r.api && m.re.test(r.id)));

    return { blockMatches, others };
}

function yearRange(matches) {
    const years = [];
    for (const r of matches) {
        for (const m of r.id.match(/(19|20)\d{2}/g) || []) years.push(Number(m));
        if (r.temporal.start) years.push(r.temporal.start);
        if (r.temporal.end) years.push(r.temporal.end);
    }
    if (!years.length) return null;
    const min = Math.min(...years);
    const max = Math.max(...years);
    return min === max ? String(min) : min + '–' + max;
}

// ── Status ────────────────────────────────────────────────────────────────────

function blockStatus(block, entryType, matches, apiStatus, t) {
    const dataMatches = matches.filter((r) => DATA_APIS.includes(r.api));
    if (dataMatches.length) {
        const n = dataMatches.length;
        const years = yearRange(dataMatches);
        const label = n + ' ' + (n > 1 ? t.collections : t.collection) + ' ' + t.live
            + (years ? ' · ' + years : '');
        return { kind: 'live', dot: '●', label };
    }
    const type = block.type || entryType;
    const matcherApis = (block.match || []).map((m) => m.api);
    if (matcherApis.length && matcherApis.every((api) => apiStatus[api] === 'down')) {
        return { kind: 'unknown', dot: '◌', label: t.unknown };
    }
    if (type === 'external' || matches.length) {
        return { kind: 'external', dot: '◍', label: t.external };
    }
    return { kind: 'not-ingested', dot: '○', label: t.notIngested };
}

// ── Rendering ─────────────────────────────────────────────────────────────────

function renderFormats(formats) {
    const tags = el('div', 'format-tags');
    for (const f of formats || []) {
        tags.appendChild(el('span', 'format-tag fmt-' + (f.tag || 'ogc'), f.label));
    }
    return tags;
}

function renderBlock(block, entryType, matches, apiStatus, lang) {
    const t = L[lang];
    const div = el('div', 'dataset-block');
    div.appendChild(el('div', 'dataset-name', pick(block.name, lang)));

    const meta = el('div', 'dataset-meta');
    meta.appendChild(el('span', 'meta-years', pick(block.years, lang)));
    meta.appendChild(renderFormats(block.formats));
    div.appendChild(meta);

    const status = blockStatus(block, entryType, matches, apiStatus, t);
    div.appendChild(el('div', 'dataset-status dataset-status--' + status.kind,
        status.dot + ' ' + status.label));
    return div;
}

function link(href, label) {
    const a = el('a', null, label);
    a.href = href;
    a.target = '_blank';
    a.rel = 'noopener';
    return a;
}

function renderCardShell(iconText, category, title, lang) {
    const t = L[lang];
    const card = el('article', 'service-card');
    const header = el('div', 'card-header');
    header.appendChild(el('div', 'card-icon card-icon--' + category, iconText));
    const titleGroup = el('div', 'card-title-group');
    titleGroup.appendChild(el('div', 'card-title', title));
    titleGroup.appendChild(el('span', 'card-badge card-badge--' + category, t.catBadge[category]));
    header.appendChild(titleGroup);
    card.appendChild(header);
    return card;
}

function renderCard(entry, joined, apiStatus, lang) {
    const t = L[lang];
    const card = renderCardShell(entry.icon, entry.category, pick(entry.org, lang), lang);

    const blocks = el('div', 'datasets');
    for (const block of entry.datasets) {
        blocks.appendChild(renderBlock(block, entry.type,
            joined.blockMatches.get(block) || [], apiStatus, lang));
    }
    card.appendChild(blocks);
    card.appendChild(el('p', 'card-description', pick(entry.description, lang)));

    const links = el('p', 'card-links');
    if (entry.license && entry.license.url) {
        links.appendChild(document.createTextNode(t.license + ': '));
        links.appendChild(link(entry.license.url, entry.license.label));
    }
    if (entry.source && entry.source.url) {
        if (links.childNodes.length) links.appendChild(document.createTextNode(' · '));
        links.appendChild(document.createTextNode(t.source + ': '));
        links.appendChild(link(entry.source.url, entry.source.label));
    }
    if (links.childNodes.length) card.appendChild(links);
    return card;
}

function renderOtherCard(record, lang) {
    const t = L[lang];
    const card = renderCardShell(t.apiName[record.api] || record.api, 'other',
        record.title || record.id, lang);
    const meta = el('div', 'datasets');
    const block = el('div', 'dataset-block');
    block.appendChild(el('div', 'dataset-name', record.id));
    const years = record.temporal.start
        ? record.temporal.start + '–' + (record.temporal.end || '…') : null;
    if (years) {
        const m = el('div', 'dataset-meta');
        m.appendChild(el('span', 'meta-years', years));
        block.appendChild(m);
    }
    meta.appendChild(block);
    card.appendChild(meta);
    if (record.description) card.appendChild(el('p', 'card-description', record.description));
    return card;
}

function renderAll() {
    if (!state) return;
    const lang = getLang();
    const grids = {
        crop: document.getElementById('grid-crop'),
        soil: document.getElementById('grid-soil'),
        climate: document.getElementById('grid-climate'),
    };
    Object.values(grids).forEach((g) => { if (g) g.innerHTML = ''; });

    for (const entry of state.registry.datasets) {
        const grid = grids[entry.category];
        if (grid) grid.appendChild(renderCard(entry, state.joined, state.apiStatus, lang));
    }

    const otherSection = document.getElementById('section-other');
    const otherGrid = document.getElementById('grid-other');
    if (otherSection && otherGrid) {
        otherGrid.innerHTML = '';
        for (const record of state.joined.others) {
            otherGrid.appendChild(renderOtherCard(record, lang));
        }
        otherSection.hidden = !state.joined.others.length;
    }
}

// ── Entry point ───────────────────────────────────────────────────────────────

async function main() {
    let registry;
    try {
        registry = await fetchRegistry();
    } catch (e) {
        const grid = document.getElementById('grid-crop');
        if (grid) grid.appendChild(el('p', 'card-description', L[getLang()].loadError));
        console.error('data-catalog: registry load failed — ' + e.message);
        return;
    }
    const live = await fetchLive();
    state = { registry, apiStatus: live.apiStatus, joined: joinCatalog(registry, live) };
    renderAll();
}

document.addEventListener('sdss-lang-changed', renderAll);
main();
