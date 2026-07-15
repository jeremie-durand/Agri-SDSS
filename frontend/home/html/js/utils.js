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
