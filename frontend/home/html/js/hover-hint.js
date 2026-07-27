// Shared floating tooltip shown while hovering an interactive map layer
// (BDPPAD parcels, AAC pixels) to signal that clicking will open details.

let hintEl = null;

function _ensureHintEl() {
    if (hintEl) return hintEl;
    hintEl = document.createElement('div');
    hintEl.className = 'map-hover-hint';
    hintEl.hidden = true;
    document.body.appendChild(hintEl);
    return hintEl;
}

export function showHoverHint(clientX, clientY, text) {
    const el = _ensureHintEl();
    el.textContent = text;
    el.style.left = (clientX + 14) + 'px';
    el.style.top = (clientY + 14) + 'px';
    el.hidden = false;
}

export function hideHoverHint() {
    if (hintEl) hintEl.hidden = true;
}
