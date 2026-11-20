// ── Language ──────────────────────────────────────────────────────────────────

// Backends negotiate against the fr-CA / en-US locales declared server-side;
// the bare tag is kept as a q=0.9 fallback so a plain `fr` catalog still matches.
const ACCEPT_LANGUAGE = { fr: "fr-CA,fr;q=0.9", en: "en-US,en;q=0.9" };

export function currentLang() {
    return window.lang || localStorage.getItem("sdss-lang") || "fr";
}

export function formatZoom(zoom) {
    return String(Number(zoom.toFixed(2)));
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

const JOB_POLL_INTERVAL_MS = 3000;
const JOB_TIMEOUT_MS = 35 * 60 * 1000;
const JOB_RETRY_STATUSES = new Set([429, 502, 503, 504]);
const JOB_TIMEOUT_MESSAGE = {
    fr: "Délai dépassé en attendant la fin du traitement",
    en: "Timed out waiting for the process to finish",
};

async function _jsonOrThrow(response) {
    if (!response.ok) throw new Error("HTTP " + response.status);
    return response.json();
}

function _retryDelayMs(response) {
    const seconds = Number(response.headers.get("Retry-After"));
    return Number.isFinite(seconds) && seconds > 0
        ? Math.max(seconds * 1000, JOB_POLL_INTERVAL_MS)
        : JOB_POLL_INTERVAL_MS;
}

// Runs a process-api process as an async job and resolves to the same body as a
// sync execution. A process without async support answers 200 directly. Rate
// limits and proxy errors while polling are retried: the job keeps running.
export async function runProcessJob(processId, body) {
    const r = await apiFetch(`/process-api/processes/${processId}/execution?f=json`, {
        method: "POST",
        headers: { "Content-Type": "application/json", "Prefer": "respond-async" },
        body: JSON.stringify(body),
    });
    if (r.status !== 201) return _jsonOrThrow(r);
    const location = r.headers.get("Location");
    if (!location) throw new Error("HTTP 201");
    const jobPath = new URL(location, window.location.origin).pathname;
    const deadline = Date.now() + JOB_TIMEOUT_MS;
    let waitMs = JOB_POLL_INTERVAL_MS;
    while (Date.now() < deadline) {
        await new Promise(resolve => setTimeout(resolve, waitMs));
        waitMs = JOB_POLL_INTERVAL_MS;
        const statusResponse = await apiFetch(`${jobPath}?f=json`);
        if (JOB_RETRY_STATUSES.has(statusResponse.status)) {
            waitMs = _retryDelayMs(statusResponse);
            continue;
        }
        const job = await _jsonOrThrow(statusResponse);
        if (job.status === "failed") throw new Error(job.message);
        if (job.status !== "successful") continue;
        const results = await apiFetch(`${jobPath}/results?f=json`);
        if (JOB_RETRY_STATUSES.has(results.status)) {
            waitMs = _retryDelayMs(results);
            continue;
        }
        return _jsonOrThrow(results);
    }
    throw new Error(JOB_TIMEOUT_MESSAGE[currentLang()] || JOB_TIMEOUT_MESSAGE.fr);
}

// ── URLs ──────────────────────────────────────────────────────────────────────

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
