const metadataStatusEl = document.getElementById("metadataStatus");
const metadataBoxEl = document.getElementById("metadataBox");

export function clearMetadata() {
    metadataStatusEl.textContent = "Aucun item selectionne.";
    metadataBoxEl.innerHTML = "<p class=\"legend\">Selectionnez un item STAC pour afficher ses metadonnees.</p>";
}

export function addMetadataRow(key, value) {
    if (value === undefined || value === null || value === "") return;
    const row = document.createElement("div");
    row.className = "metadata-row";
    const keyEl = document.createElement("div");
    keyEl.className = "metadata-key";
    keyEl.textContent = key;
    const valueEl = document.createElement("div");
    valueEl.className = "metadata-value";
    valueEl.textContent = Array.isArray(value) ? value.join(", ") : String(value);
    row.appendChild(keyEl);
    row.appendChild(valueEl);
    metadataBoxEl.appendChild(row);
}

export function addMetadataSection(title) {
    const titleEl = document.createElement("div");
    titleEl.className = "metadata-section-title";
    titleEl.textContent = title;
    metadataBoxEl.appendChild(titleEl);
}

export function formatMetadataValue(value) {
    if (value === undefined || value === null || value === "") return null;
    if (Array.isArray(value)) {
        const isPrimitive = value.every((v) => v === null || ["string", "number", "boolean"].includes(typeof v));
        return isPrimitive ? value.join(", ") : JSON.stringify(value);
    }
    if (typeof value === "object") return JSON.stringify(value);
    return String(value);
}

export function flattenMetadataObject(source, prefix = "", entries = []) {
    if (!source || typeof source !== "object" || Array.isArray(source)) return entries;
    Object.keys(source).sort().forEach((key) => {
        const value = source[key];
        const nextKey = prefix ? `${prefix}.${key}` : key;
        if (value && typeof value === "object" && !Array.isArray(value)) {
            flattenMetadataObject(value, nextKey, entries);
            return;
        }
        entries.push([nextKey, value]);
    });
    return entries;
}

export function addMetadataRowsFromObject(source, options = {}) {
    const { title, keyPrefix = "", maxEntries = 100 } = options;
    const entries = flattenMetadataObject(source, keyPrefix).slice(0, maxEntries);
    if (!entries.length) return;
    if (title) addMetadataSection(title);
    entries.forEach(([key, value]) => addMetadataRow(key, formatMetadataValue(value)));
}

export function renderAssetsMetadata(assets) {
    const assetNames = Object.keys(assets || {});
    if (!assetNames.length) return;
    addMetadataSection("Assets");
    const assetsRow = document.createElement("div");
    assetsRow.className = "metadata-row";
    const keyEl = document.createElement("div");
    keyEl.className = "metadata-key";
    keyEl.textContent = "Liste";
    const assetsWrap = document.createElement("div");
    assetsWrap.className = "metadata-assets";
    assetNames.forEach((assetName) => {
        const asset = assets[assetName] || {};
        const assetEl = document.createElement("div");
        assetEl.className = "metadata-asset";
        const details = [asset.title || assetName];
        if (asset.type) details.push(asset.type);
        if (Array.isArray(asset.roles) && asset.roles.length) details.push(`roles: ${asset.roles.join(", ")}`);
        if (asset.href) details.push(asset.href);
        assetEl.textContent = details.join(" | ");
        assetsWrap.appendChild(assetEl);
    });
    assetsRow.appendChild(keyEl);
    assetsRow.appendChild(assetsWrap);
    metadataBoxEl.appendChild(assetsRow);
}

export function renderLinksMetadata(links) {
    if (!Array.isArray(links) || !links.length) return;
    addMetadataSection("Links");
    links.forEach((link, index) => {
        if (!link) return;
        const parts = [];
        if (link.rel) parts.push(`rel=${link.rel}`);
        if (link.type) parts.push(`type=${link.type}`);
        if (link.href) parts.push(link.href);
        addMetadataRow(`link.${index + 1}`, parts.join(" | "));
    });
}
