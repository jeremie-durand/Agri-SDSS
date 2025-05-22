# eoapi-template
Template repository to deploy eoapi localy

# Requirements
python >=3.9
docker
node >=14

## Création Python env
Install python dependencies with
1. python -m venv venv
2. linux -> source venv/bin/activate Or on Windows -> venv\Scripts\activate

# Docker
docker compose up --build
Once the applications are up, you'll need to add STAC Collections and Items to the PgSTAC database.

# Endpoints
Then you can start exploring your dataset with:

## the STAC Metadata service 
http://localhost:8081
Les données doivent être publier dans le catalogue STAC pour être disponible dans l'API

## the Raster service 
http://localhost:8082
Pas encore testé

## the Vector service 
http://localhost:8083
Les données sont disponible directement via postgis sous public (si c'est des données vectorielles)

## the browser UI 
http://localhost:8085
Visualisation des données disponible dans le catalogue STAC

# Add data
1. Build le docker
2. Add data to PostGIS (manuellement pour l'instant)
3. Transformer et publier les données en standard STAC items et collections (init_postgis.py et processing_stac.py)
4. Tester les endpoints