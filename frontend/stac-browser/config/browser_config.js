window.STAC_BROWSER_CONFIG = {
    catalogUrl: "https://${HOST_URL}/stac-api/",
    catalogTitle: (localStorage.getItem('sdss-lang') || 'fr') === 'fr' ? 'Catalogue STAC' : 'STAC Catalog',
    allowExternalAccess: true,
    allowedDomains: [],
    // The platform language toggle (nav-inject.js) is the single source of
    // truth: browser detection and STAC Browser's own stored locale are off
    // so its chrome can never disagree with the nav bar.
    detectLocaleFromBrowser: false,
    storeLocale: false,
    locale: (localStorage.getItem('sdss-lang') || 'fr') === 'fr' ? "fr" : "en",
    fallbackLocale: "en",
    supportedLocales: ["en", "fr"],
    apiCatalogPriority: null,
    useTileLayerAsFallback: false,
    displayGeoTiffByDefault: true,
    buildTileUrlTemplate: function(asset) {
        // The pipeline stores the display rescale/bidx on the item's "tiles"
        // asset; without them float rasters render as solid black.
        var file = "/" + asset.href.split("/").pop();
        var item = asset.getContext();
        var tiles = item && item.getAssets().find(function(a) {
            return (a.roles || []).indexOf("tiles") !== -1 && a.href.indexOf(file) !== -1;
        });
        if (tiles) {
            return tiles.href.replace("/WebMercatorQuad/tilejson.json", "/tiles/WebMercatorQuad/{z}/{x}/{y}");
        }
        return "https://${HOST_URL}/raster-api/cog/tiles/WebMercatorQuad/{z}/{x}/{y}?url=" +
            encodeURIComponent(asset.href.indexOf("/vsi") === 0 ? asset.href : asset.getAbsoluteUrl());
    },
    preprocessSTAC: function(stac) {
        var lang = localStorage.getItem('sdss-lang') || 'fr';
        var fr = lang === 'fr';

        // Catalog root: translate title and description
        if (stac.type === 'Catalog' || !stac.type) {
            stac.title = fr ? 'Catalogue STAC' : 'STAC Catalog';
            stac.description = fr
                ? 'Un catalogue STAC (SpatioTemporal Asset Catalog) organise les données géospatiales selon deux axes : ' +
                  'l\'espace (où : l\'emprise géographique de chaque image ou couche) et le temps (quand : sa date d\'acquisition). ' +
                  'Cette structure spatio-temporelle permet de rechercher et de filtrer les données par zone géographique et ' +
                  'par période, plutôt que de parcourir les fichiers un à un. Ce catalogue rassemble les données géospatiales ' +
                  'agricoles et environnementales pour la recherche en agriculture durable au Québec'
                : 'A STAC catalog (SpatioTemporal Asset Catalog) organizes geospatial data along two axes: space (where:' +
                  'the geographic extent of each image or layer) and time (when: its acquisition date). This spatio-temporal ' +
                  'structure lets you search and filter data by geographic area and time period, rather than browsing files ' +
                  'one by one. This catalog brings together agricultural and environmental geospatial data for Quebec ' +
                  'sustainable agriculture research.';
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
            stac.description = descFr[stac.id] || stac.description ||
                'Données géospatiales générées par le pipeline Agri-SDSS.';
        }

        return stac;
    },
    pathPrefix: "/stac/",
    historyMode: "hash",
    cardViewMode: "cards",
    showThumbnailsAsAssets: false,
    itemsPerPage: 12,
    defaultThumbnailSize: null,
    crossOriginMedia: null,
    transactions: "off",
    crs: {
        "EPSG:32198": "+proj=lcc +lat_0=44 +lon_0=-68.5 +lat_1=60 +lat_2=46 +x_0=0 +y_0=0 +datum=NAD83 +units=m +no_defs"
    },
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
