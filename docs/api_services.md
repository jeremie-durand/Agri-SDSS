| Service ou API | Standard utilisé | Stockage des données | Exemples de requêtes | Types de données renvoyées |
| --- | --- | --- | --- | --- |
| **STAC API** | STAC API | PostGIS | `GET /collections/farms/items/farm-x`<br>`GET /collections/estrie/items/estrie-ph`<br>`POST /search` | GeoJSON avec métadonnées STAC |
| **Raster API** | OGC API – Tiles / Maps | COG en local avec PostGIS pour métadonnées | `GET /cog/tiles/{z}{x}{y}.png?url=data/raster-x.tif`<br>`GET /cog/info?url=data/raster-x.tif` | Tuile raster PNG |
| **Vector API** | OGC API - Features | PostGIS | `GET /collections/farms/items/farm-x` | GeoJSON |
| **Process API** | OGC API - Processes | PostGIS/DuckDB et tous les services | `GET /processes/my-process-x/execution`<br>`GET /processes/process-mos-model/execution` | Dépend du process : GeoJSON, JSON |
| **Proxy services** | Dépend du service redirigé | Données externes | `http://proxy-wms/wms?service=WMS&request=GetMap...`<br>`http://proxy-ogc-api-features/collections/lakes/items?` | Dépend du proxy |
