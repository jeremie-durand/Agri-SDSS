import { map, layers, defaultView } from './state.js';
import './chat.js';
import { loadBdppadCollections, deselectBdppadCollection, setBdppadActivateCallback } from './vector.js';
import { initAacSection, deselectAac, setAacActivateCallback } from './aac.js';
import { initGrhqSection, deselectGrhq, setGrhqActivateCallback } from './grhq.js';
import { closeSomModal, somAutoGenCorg, somAutoGenPh, somAutoGenSable, somAutoGenLimon, somAutoGenArgile, somAutoGenCec, somAutoGenScenes, somAutoGenElevation, somAutoGenPrecip, somAutoGenPedo, somAutoGenWater, somRunAnalysis, somShowPreview, somClosePreview, somSavePdf, somPredictRun } from './som.js';
import { initSomBoundaryLayer } from './som_layers.js';

// ── DOM refs ──────────────────────────────────────────────────────────────────
const coordsEl = document.getElementById("coords");

// ── Service worker ────────────────────────────────────────────────────────────
// Unregister any previously installed SW to avoid stale cache issues.
if ("serviceWorker" in navigator) {
    navigator.serviceWorker.getRegistrations().then((regs) => {
        regs.forEach((r) => r.unregister());
    });
}

// ── Map utils ─────────────────────────────────────────────────────────────────
function updateCoords(latlng) {
    coordsEl.textContent = `Lat: ${latlng.lat.toFixed(5)}, Lon: ${latlng.lng.toFixed(5)}, Zoom: ${map.getZoom()}`;
}

// ── Map event listeners ───────────────────────────────────────────────────────
map.on("mousemove", (event) => updateCoords(event.latlng));
map.on("zoomend", () => updateCoords(map.getCenter()));

// ── Basemap switcher ──────────────────────────────────────────────────────────
let activeLayer = layers.osm.addTo(map);
activeLayer.setZIndex(0);
document.getElementById("basemap").addEventListener("change", (event) => {
    const newLayer = layers[event.target.value];
    if (!newLayer || newLayer === activeLayer) return;
    map.removeLayer(activeLayer);
    activeLayer = newLayer.addTo(map);
    activeLayer.setZIndex(0);
});

// ── Navigation buttons ────────────────────────────────────────────────────────
document.getElementById("btnHome").addEventListener("click", () => map.setView(defaultView.center, defaultView.zoom));

// ── Map overlay controls ──────────────────────────────────────────────────────
document.getElementById("mapZoomIn").addEventListener("click", () => map.zoomIn());
document.getElementById("mapZoomOut").addEventListener("click", () => map.zoomOut());
document.getElementById("mapLocate").addEventListener("click", () => {
    if (!navigator.geolocation) return;
    navigator.geolocation.getCurrentPosition(
        (position) => {
            const latlng = [position.coords.latitude, position.coords.longitude];
            map.setView(latlng, 14);
            L.circleMarker(latlng, { radius: 8, weight: 2, color: "#22d3ee", fillColor: "#06b6d4", fillOpacity: 0.6 }).addTo(map);
        },
        () => {},
        { enableHighAccuracy: true, timeout: 10000, maximumAge: 0 }
    );
});

// ── SOM calculator controls ───────────────────────────────────────────────────
document.getElementById('somCorgGen').addEventListener('click', somAutoGenCorg);
document.getElementById('somPhGen').addEventListener('click', somAutoGenPh);
document.getElementById('somSableGen').addEventListener('click', somAutoGenSable);
document.getElementById('somLimonGen').addEventListener('click', somAutoGenLimon);
document.getElementById('somArgileGen').addEventListener('click', somAutoGenArgile);
document.getElementById('somCecGen').addEventListener('click', somAutoGenCec);
document.getElementById('somScenesGen').addEventListener('click', somAutoGenScenes);
document.getElementById('somElevationGen').addEventListener('click', somAutoGenElevation);
document.getElementById('somPrecipGen').addEventListener('click', somAutoGenPrecip);
document.getElementById('somPedoGen').addEventListener('click', somAutoGenPedo);
document.getElementById('somWaterGen').addEventListener('click', somAutoGenWater);
document.getElementById('somRun').addEventListener('click', somRunAnalysis);
document.getElementById('somExportPdf').addEventListener('click', somShowPreview);
document.getElementById('somPredictRun').addEventListener('click', somPredictRun);
document.getElementById('somReportSave').addEventListener('click', somSavePdf);
document.getElementById('somReportCancel').addEventListener('click', somClosePreview);
document.getElementById('somReportClose').addEventListener('click', somClosePreview);
document.getElementById('somReportBackdrop').addEventListener('click', somClosePreview);
document.getElementById('somClose').addEventListener('click', closeSomModal);
document.getElementById('somCancel').addEventListener('click', closeSomModal);
document.getElementById('somBackdrop').addEventListener('click', closeSomModal);

// ── Init ──────────────────────────────────────────────────────────────────────
setBdppadActivateCallback(() => { deselectAac(); deselectGrhq(); });
setAacActivateCallback(() => { deselectBdppadCollection(); deselectGrhq(); });
setGrhqActivateCallback(() => { deselectBdppadCollection(); deselectAac(); });

initAacSection();
initGrhqSection();
const somBoundaryToggle = document.getElementById('somBoundaryToggle');
somBoundaryToggle.checked = true;
initSomBoundaryLayer(somBoundaryToggle);
somBoundaryToggle.dispatchEvent(new Event('change'));
loadBdppadCollections();
updateCoords(map.getCenter());
requestAnimationFrame(() => map.invalidateSize());

if (navigator.geolocation) {
    navigator.geolocation.getCurrentPosition(
        function(pos) { map.setView([pos.coords.latitude, pos.coords.longitude], 14); },
        function() {},
        { timeout: 5000, maximumAge: 60000 }
    );
}
