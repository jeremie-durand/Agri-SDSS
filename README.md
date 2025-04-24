# SAD-MOS
Projet de maîtrise sur le développement d'une architecture côté-serveur d'un système d'aide à la décision (SAD) afin d’optimiser le potentiel de la matière organique des sols (MOS) au Québec et les meilleurs pratiques pour l'atteindre

## Tools à tester
MapServer vs GeoServer -> serveur cartographique

Database | Vector Format (Best) | Raster Format (Best) | Native Raster Support? | Typical Use Cases / Roles
PostGIS | GeoPackage (.gpkg) | GeoTIFF (.tif) | ✅ Full native support | Heavy spatial querying, geometry analysis, joins with attribute tables, spatial joins
 | (also: Shapefile, CSV+WKT) | (also: JPEG2000, PNG) |  | Suitable for geospatial infrastructure or web GIS backends (e.g. QGIS server)
MongoDB | GeoJSON | ❌ None | ❌ (only GridFS workaround) | Lightweight geometry store, web delivery, user-generated locations, logs, events, sensors
 | (also: TopoJSON, WKT) |  |  | Good for real-time geo dashboards, IoT, mobile apps, geofencing
DuckDB | GeoParquet | ❌ No native raster yet | ❌ Experimental only | Fast analytics on massive tables, batch jobs, data pipelines, summary stats
 | (also: CSV + WKB/WKT) | (use preprocessed tabular) |  | Best for ETL, preprocessing, machine learning input, and offline reporting

Use Case | Recommended Format | Recommended DB
Spatial joins, routing, topological operations | GeoPackage / PostGIS | PostGIS
Live location updates from mobile users | GeoJSON / MongoDB | MongoDB
Vectorized NDVI summaries from raster | GeoParquet / DuckDB | DuckDB
Daily raster NDVI download from Sentinel-2 | GeoTIFF (outside DB) | Store path + summary in PostGIS or MongoDB
Point observations from sensors (e.g., weather) | GeoJSON or CSV+WKT | MongoDB or DuckDB
Statistical analysis of 1M+ lakes / tiles | GeoParquet | DuckDB
Export for GIS clients (ArcGIS, QGIS, etc.) | GeoPackage / Shapefile | PostGIS export

Workflow Example for Integrated System
Let’s say your system ingests satellite + IoT + user data:
Raw NDVI (COG or GeoTIFF) → Preprocessed into pixel tables → stored in DuckDB
Vector lakes / polygons → Stored in PostGIS for full GIS operations
Mobile app sends location pings → Stored in MongoDB in GeoJSON
Batch process in DuckDB → Aggregates NDVI by polygon → Pushes summaries to PostGIS
Dashboard queries MongoDB for live data + PostGIS for mapped context

DuckDB et MongoDB -> possible d'ecxtraire les valeurs des pixels


pygeoapi -> creation d'une api web pour python suivant les standards de l'OGC



GeoTIFF vs COG -> format uniformisé matriciel

## Tools confirmé
Python (via Flask, APIs, etc.) -> backend / acquisition et traitement des données

Docker -> container

GitHub -> partage / publication / collaboration

## APIs
Données Québec
https://www.donneesquebec.ca/page-api/
https://docs.ckan.org/en/2.10/api/index.html

Open Canada
https://open.canada.ca/en/access-our-application-programming-interface-api
CKAN aussi

BDPPAD - téléchargeable dans le code source
view-source:https://www.fadq.qc.ca/documents/donnees/base-de-donnees-des-parcelles-et-productions-agricoles-declarees

ECCC
https://eccc-msc.github.io/open-data/msc-geomet/readme_en/

IRDA - téléchargeable dans le code source
view-source:https://irda.qc.ca/fr/outils/donnees-pedologiques-sols/cartes-pedologiques-quebec-irda/

## Création Python env
1. python -m venv venv
2. linux -> source venv/bin/activate
Or on Windows -> venv\Scripts\activate
3. pip install -r requirements.txt
4. activate -> venv\Scripts\activate

## GEE authentification (In terminal)
earthengine authenticate

## Run the app
python -m flask run ou python script/app.py
http://127.0.0.1:5000/