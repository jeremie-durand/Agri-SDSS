import { map, stacState } from './state.js';

function _tL() { return (window.T && window.T[window.lang]) || {}; }

/*
 * sendFeatureContext — auto-populate the chatbot with farm/feature context on parcel click.
 * Disabled for now; re-enable by restoring the body and uncommenting callers in vector.js / aac.js.
 *
 * export function sendFeatureContext(collectionId, feature, center) {
 *     var chatPanel = document.getElementById('chatPanel');
 *     var chatToggle = document.getElementById('chatToggle');
 *     var chatInput = document.getElementById('chatInput');
 *     if (!chatInput) return;
 *
 *     if (chatPanel && chatPanel.hidden) {
 *         chatPanel.hidden = false;
 *         if (chatToggle) chatToggle.hidden = true;
 *     }
 *
 *     var id = (feature && feature.id) || '';
 *     var props = (feature && feature.properties) || {};
 *     var isBdppad = collectionId.toLowerCase().indexOf('bdppad') === 0;
 *     var lines = [];
 *
 *     if (isBdppad) {
 *         lines.push('I am looking at an agricultural parcel from the Agri-SDSS platform database. Here is its recorded information:');
 *         lines.push('');
 *         if (id) lines.push('Parcel ID: ' + id);
 *         if (collectionId) lines.push('Dataset: ' + collectionId);
 *         lines.push('');
 *         lines.push('Dataset context: BDPPAD (Base de données sur les parcelles et propriétés agricoles du Québec) is the Quebec provincial registry of agricultural parcels. The "typpar" field is the official parcel type code; its meaning is given in the "description" field. The "suphec" field is the parcel area in hectares.');
 *     } else {
 *         lines.push('I am looking at a geographic feature from the Agri-SDSS platform. Here is its recorded information:');
 *         lines.push('');
 *         if (id) lines.push('Feature ID: ' + id);
 *         if (collectionId) lines.push('Dataset: ' + collectionId);
 *     }
 *
 *     var propKeys = Object.keys(props).filter(function(k) {
 *         var v = props[k];
 *         return v !== null && v !== undefined && v !== '';
 *     });
 *     if (propKeys.length) {
 *         lines.push('');
 *         lines.push('Recorded attributes:');
 *         propKeys.forEach(function(k) { lines.push('  ' + k + ': ' + props[k]); });
 *     }
 *
 *     var stacItem = stacState.selectedItem;
 *     if (stacItem && stacItem.type === 'Feature') {
 *         var sp = stacItem.properties || {};
 *         lines.push('');
 *         lines.push('Selected remote sensing item from the platform catalog:');
 *         lines.push('  id: ' + (stacItem.id || 'unknown'));
 *         lines.push('  collection: ' + (stacItem.collection || sp.collection || 'unknown'));
 *         if (stacItem.bbox) lines.push('  bbox: ' + stacItem.bbox.join(', '));
 *         Object.keys(sp).forEach(function(k) {
 *             if (sp[k] !== null && sp[k] !== undefined && sp[k] !== '') lines.push('  ' + k + ': ' + sp[k]);
 *         });
 *     }
 *
 *     lines.push('');
 *     if (isBdppad) {
 *         lines.push('Please provide an agronomic analysis of this parcel based on the information above. What does the parcel type, area, and classification suggest? What kind of agricultural use or soil conditions might be expected?');
 *     } else {
 *         lines.push('Please analyze this geographic feature based on the information above. What does the data suggest about this location in the context of Quebec agriculture or land use?');
 *     }
 *
 *     chatInput.value = lines.join('\n');
 *     chatInput.focus();
 * }
 */
export function sendFeatureContext(_collectionId, _feature, _center) { /* disabled */ }

// ── Chat panel (module-scoped, replaces IIFE) ─────────────────────────────────
const chatToggle = document.getElementById('chatToggle');
const chatPanel = document.getElementById('chatPanel');
const chatClose = document.getElementById('chatClose');
const chatMessages = document.getElementById('chatMessages');
const chatForm = document.getElementById('chatForm');
const chatInput = document.getElementById('chatInput');
const chatSend = document.getElementById('chatSend');

let sessionId = Math.random().toString(36).slice(2);
let history = [];
let chatLayers = [];
let chatNavCenter = null;

chatToggle.addEventListener('click', function() {
    chatPanel.hidden = false;
    chatToggle.hidden = true;
    chatInput.focus();
});
chatClose.addEventListener('click', function() {
    chatPanel.hidden = true;
    chatToggle.hidden = false;
});

function addMsg(role, text) {
    var div = document.createElement('div');
    div.className = 'chat-msg chat-msg--' + role;
    div.textContent = text;
    chatMessages.appendChild(div);
    chatMessages.scrollTop = chatMessages.scrollHeight;
    return div;
}

function clearChatLayers() {
    chatLayers.forEach(function(l) { map.removeLayer(l); });
    chatLayers = [];
}

async function signUrl(url) {
    try {
        var r = await fetch('/api/sign-mosaic-url', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ url: url })
        });
        if (!r.ok) return url;
        var d = await r.json();
        return d.signed_url || url;
    } catch (_) { return url; }
}

async function addTileLayer(tjUrl, bbox) {
    try {
        var signed = await signUrl(tjUrl);
        var r = await fetch(signed);
        if (!r.ok) return;
        var tj = await r.json();
        var tileUrl = tj.tiles && tj.tiles[0];
        if (!tileUrl) return;
        tileUrl = tileUrl.replace(/^\/api\/raster\//, '/raster-api/');
        // zIndex 650 puts the overlay above Leaflet's tilePane (200) and overlayPane (400).
        // No bounds restriction — auto-navigation already zooms to the right area,
        // and bounding would hide tiles when the MODIS grid cell doesn't align with
        // the chatNavCenter point.
        var opts = { opacity: 0.85, attribution: 'MOS overlay', zIndex: 650 };
        chatLayers.push(L.tileLayer(tileUrl, opts).addTo(map));
    } catch (_) {}
}

function isSdssQuery(text) {
    var t = text.toLowerCase();
    return /\bprocess(es)?\b/.test(t) || /\bpygeoapi\b/.test(t) || /\bexecute\b/.test(t) ||
           /\b(what|which|list).*(analys|process|tool|capabilit)/.test(t) ||
           /\bspatial (analysis|analyses|tools)\b/.test(t) || /\bhello.?world\b/.test(t);
}

async function sendQuery(text) {
    chatSend.disabled = true;
    chatInput.value = '';
    addMsg('user', text);
    var thinking = addMsg('thinking', 'Analysing…');
    history.push({ role: 'user', content: text });
    var endpoint = isSdssQuery(text) ? '/sdss/query' : '/api/query';
    var data;
    try {
        var r = await fetch(endpoint, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ query: text, session_id: sessionId, conversation_history: history.slice(-10) })
        });
        data = await r.json();
    } catch (_) {
        thinking.className = 'chat-msg chat-msg--assistant';
        thinking.textContent = _tL()['chat-backend-error'] || 'Error: could not reach the backend.';
        chatSend.disabled = false;
        return;
    }
    thinking.remove();
    var reply = data.response || data.message || '(no response)';
    addMsg('assistant', reply);
    history.push({ role: 'assistant', content: reply });

    if (data.action === 'navigate_to' && data.navigate_to) {
        var nav = data.navigate_to;
        if (typeof nav.latitude === 'number' && typeof nav.longitude === 'number') {
            var navZoom = nav.zoom || 10;
            chatNavCenter = { lat: nav.latitude, lon: nav.longitude, zoom: navZoom };
            map.setView([nav.latitude, nav.longitude], navZoom);
        } else if (Array.isArray(nav.bbox) && nav.bbox.length === 4) {
            var b = nav.bbox;
            chatNavCenter = { lat: (b[1] + b[3]) / 2, lon: (b[0] + b[2]) / 2, zoom: null };
            map.fitBounds([[b[1], b[0]], [b[3], b[2]]]);
        }
    }

    clearChatLayers();
    var meta = data.translation_metadata || {};
    var hasTiles = false;
    if (meta.mosaic_tilejson && meta.mosaic_tilejson.tilejson_url) {
        await addTileLayer(meta.mosaic_tilejson.tilejson_url, null);
        hasTiles = true;
    } else if (meta.all_tile_urls && meta.all_tile_urls.length) {
        var tiles = meta.all_tile_urls.slice(0, 3);
        for (var i = 0; i < tiles.length; i++) await addTileLayer(tiles[i].tilejson_url, tiles[i].bbox);
        hasTiles = true;
    }

    // Auto-navigate to query location when tiles were added but no explicit navigate_to
    if (hasTiles && !data.navigate_to) {
        var qbbox = meta.stac_query && meta.stac_query.bbox;
        if (Array.isArray(qbbox) && qbbox.length === 4) {
            var cx = (qbbox[0] + qbbox[2]) / 2;
            var cy = (qbbox[1] + qbbox[3]) / 2;
            var qw = Math.abs(qbbox[2] - qbbox[0]);
            var qh = Math.abs(qbbox[3] - qbbox[1]);
            // Expand tiny LLM bboxes to at least 0.5° for a useful city-scale view
            var pad = Math.max(0, 0.25 - Math.min(qw, qh) / 2);
            var navBbox = [qbbox[0] - pad, qbbox[1] - pad, qbbox[2] + pad, qbbox[3] + pad];
            chatNavCenter = { lat: cy, lon: cx, zoom: 10 };
            map.fitBounds([[navBbox[1], navBbox[0]], [navBbox[3], navBbox[2]]]);
        }
    }
    chatSend.disabled = false;
}

chatForm.addEventListener('submit', function(e) {
    e.preventDefault();
    var text = chatInput.value.trim();
    if (text) sendQuery(text);
});
chatInput.addEventListener('keydown', function(e) {
    if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
        e.preventDefault();
        var text = chatInput.value.trim();
        if (text) sendQuery(text);
    }
});
