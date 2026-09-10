// ── Language ──────────────────────────────────────────────────────────────────

// Backends negotiate against the fr-CA / en-US locales declared server-side;
// the bare tag is kept as a q=0.9 fallback so a plain `fr` catalog still matches.
const ACCEPT_LANGUAGE = { fr: "fr-CA,fr;q=0.9", en: "en-US,en;q=0.9" };

export function currentLang() {
    return window.lang || localStorage.getItem("sdss-lang") || "fr";
}

// Wrapper around fetch() for same-origin Agri-SDSS APIs: carries the active UI
// language so backends can localise their error messages. Accept-Language is a
// CORS-safelisted header, so this adds no preflight.
export function apiFetch(input, init = {}) {
    const headers = new Headers(init.headers || {});
    if (!headers.has("Accept-Language")) {
        headers.set("Accept-Language", ACCEPT_LANGUAGE[currentLang()] || ACCEPT_LANGUAGE.fr);
    }
    return fetch(input, { ...init, headers });
}

// ── URLs ──────────────────────────────────────────────────────────────────────

export function normalizeUrl(value) {
    if (!value || !value.trim()) return null;
    const raw = value.trim();
    try { return new URL(raw).toString(); } catch (_) {}
    try { return new URL(raw, window.location.origin).toString(); } catch (_) {}
    return null;
}

export function getColorForCollection(collectionId) {
    const palette = ["#22d3ee", "#34d399", "#f59e0b", "#60a5fa", "#f87171", "#a78bfa", "#4ade80", "#fbbf24"];
    const text = String(collectionId || "collection");
    let hash = 0;
    for (let i = 0; i < text.length; i++) {
        hash = ((hash << 5) - hash) + text.charCodeAt(i);
        hash |= 0;
    }
    return palette[Math.abs(hash) % palette.length];
}

export function bboxAreaHa(bounds) {
    const dlat = bounds.getNorth() - bounds.getSouth();
    const dlon = bounds.getEast() - bounds.getWest();
    const latRad = (bounds.getNorth() + bounds.getSouth()) / 2 * Math.PI / 180;
    return dlat * 111320 * dlon * 111320 * Math.cos(latRad) / 10000;
}
