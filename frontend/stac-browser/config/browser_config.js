window.STAC_BROWSER_CONFIG = {
    catalogUrl: "https://${HOST_URL}/stac-api/",
    catalogTitle: (localStorage.getItem('sdss-lang') || 'fr') === 'fr' ? 'Catalogue STAC' : 'STAC Catalog',
    allowExternalAccess: true,
    allowedDomains: [],
    detectLocaleFromBrowser: true,
    storeLocale: true,
    locale: "fr",
    fallbackLocale: "en",
    supportedLocales: ["de", "es", "en", "fr", "it", "ro"],
    apiCatalogPriority: null,
    useTileLayerAsFallback: true,
    displayGeoTiffByDefault: true,
    buildTileUrlTemplate: function(opts) {
        var href = opts.href, asset = opts.asset;
        return "https://${HOST_URL}/raster-api/cog/tiles/{z}/{x}/{y}@2x?url=" +
            encodeURIComponent(asset.href.indexOf("/vsi") === 0 ? asset.href : href);
    },
    preprocessSTAC: function(stac) {
        var lang = localStorage.getItem('sdss-lang') || 'fr';
        var fr = lang === 'fr';

        // Catalog root: translate title and description
        if (stac.type === 'Catalog' || !stac.type) {
            stac.title = fr ? 'Catalogue STAC' : 'STAC Catalog';
            stac.description = fr
                ? 'Données géospatiales agricoles et environnementales pour la recherche en agriculture durable au Québec. ' +
                  'Collections incluant l\'imagerie satellitaire (MODIS, Sentinel-2), LiDAR, cartes des sols et données climatiques.'
                : 'Agricultural and environmental geospatial data for Quebec sustainable agriculture research. ' +
                  'Collections include satellite imagery (MODIS, Sentinel-2), LiDAR, soil maps, and climate datasets.';
        }

        // Collections: translate description only (titles are technical names, kept as-is)
        if (stac.type === 'Collection' && fr) {
            var descFr = {
                'sentinel2_eo_products':
                    'Produits Sentinel-2 traités (NDVI, EVI, SAVI, vraie couleur) générés via le backend openEO ' +
                    'à partir des données Copernicus Data Space.',
                'lidar_quebec':
                    'Produits raster dérivés du LiDAR (MNA, MHC, ombrage, pente) issus du portail de données ' +
                    'ouvertes du MRNF du Québec, découpés par parcelles agricoles.'
            };
            stac.description = descFr[stac.id] ||
                'Données géospatiales générées par le pipeline Agri-SDSS.';
        }

        return stac;
    },
    stacProxyUrl: null,
    pathPrefix: "/stac/",
    historyMode: "hash",
    cardViewMode: "cards",
    cardViewSort: "desc",
    showThumbnailsAsAssets: false,
    stacLint: true,
    geoTiffResolution: 128,
    redirectLegacyUrls: false,
    itemsPerPage: 12,
    defaultThumbnailSize: null,
    maxPreviewsOnMap: 50,
    crossOriginMedia: null,
    requestHeaders: {},
    requestQueryParameters: {},
    authConfig: null,
    footerLinks: [
        {
            label: "Raster API — COG Tiles",
            url: "https://${HOST_URL}/raster-api/"
        },
        {
            label: "Vector API — OGC Features",
            url: "https://${HOST_URL}/vector-api/"
        },
        {
            label: "OGC Processes — PyGeoAPI",
            url: "https://${HOST_URL}/process-api/"
        }
    ]
};
