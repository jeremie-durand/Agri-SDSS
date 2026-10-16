// Defaults are overridden by window.AGRI_CONFIG, which entrypoint.sh writes
// into /runtime-config.js from environment variables at container start.

const injected = (typeof window !== 'undefined' && window.AGRI_CONFIG) || {};

const defaults = {
    primaryCollectionPrefix: 'bdppad',
    mapCenter: [46.8139, -71.2080],
    mapZoom: 6,
    somRasterBasenames: {
        corg: 'corg_fr_siigsol_cog',
        ph: 'ph_fr_siigsol_cog',
        sable: 'sable_fr_siigsol_cog',
        limon: 'limon_fr_siigsol_cog',
        argile: 'argile_fr_siigsol_cog',
        cec: 'cec_fr_siigsol_cog'
    }
};

export const config = {
    ...defaults,
    ...injected,
    somRasterBasenames: {
        ...defaults.somRasterBasenames,
        ...(injected.somRasterBasenames || {})
    }
};

export function somRasterUrl(key) {
    const basename = config.somRasterBasenames[key];
    if (!basename) {
        throw new Error(`No SOM raster configured for key: ${key}`);
    }
    return `file:///data/${basename}.tif`;
}
