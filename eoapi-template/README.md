# eoapi-template
Template repository to deploy EoAPI locally

## Requirements
- Docker
- PostgreSQL / PostGIS
- pgAdmin (optionnel)

## Étapes à suivre déploiement local
### 1. Variables d'env
Créer un fichier .env en se basant sur .env.example et setter les variables voulus
Note pour la base de données, le script pg-init/001_create_postgres_role.sql défini automatiquement un rôle que Docker utilise, donc pas besoin de les changer

### 2. Docker
Ouvrir un terminal Docker -> 
Se dirigier dans l'emplacement du dossier eoapi-template
```sh
cd eoapi-template
```
Construire et rouler le container Docker
```sh
docker compose up --build
``` 

### 3. Adding data locally (if wanted)
**Données Raster**
1. Choisir une/des image(s) GeoTIFF a intégrer dans l'API (fonctionne pour plusieurs images si dans le même dossier)
2. Stocker l'image localement et copier le path Windows du dossier, ce sera la variable RASTER_PATH dans .env
3. Ouvrir un nouveau terminal Docker
4. Pointer le path du dossier dans un serveur nginx via la commande (modifier RASTER_PATH) ->
```sh
docker run --rm -it -p 8001:80 -v "RASTER_PATH:/usr/share/nginx/html:ro" nginx
```

**Données Vector**
1. Choisir une/des donnée(s) vectorielles à intégrer dans l'API (shapefile, geoJSON, geopackage, ...)
2. Créer des nouvelles tables à la base de donnée PostGIS en y intégrant chaque données et en identifiant le bon SRID (PostgreSQL). Facile avec PostGIS Bundle avec les connections dans .env
3. Se connceter dans pgAdmin au serveur docker-pgstac, toujours avec les connections dans .env
4. Vérifier que les nouvelles données sont bien présents sous public.
5. Rajouter les noms des tables à la variable VECTOR_TABLES de .env

### 4. Run Python script in Docker for the new data (if data added)
1. Ouvrir un nouveau terminal Docker
2. Se dirigier dans l'emplacement du dossier eoapi-template ```cd eoapi-template```
3. Ouvrir l'env Python dans Docker : ```docker compose exec gdal-python sh```
4. Vérifier que les scripts sont bien là : ```ls``` (Astuce : avec click droit, on peut copier-coller)
5. Run le script principal qui va permettre d'effectuer les traitemetents et POST les nouvelles données dans l'API : ```python main.py```
6. Vérifier les requête POST, si status: 200 et il y a présence de STAC validation sucessful, les données ont bien été rajoutées dans l'API

### 5. Tester les Endpoints
**STAC Metadata service**
La page principale : `http://localhost:8081`
Pour voir les items STAC dans la collection : `http://localhost:8081/collections/my-collection/items`

**Raster service**
La page principale : `http://localhost:8082`
Pour voir les métadonnées d'un COG précis (changer COG_NAME): `http://localhost:8082/cog/info?url=http://host.docker.internal:8001/COG_NAME.tif` 
Pour voir dans un service XYZ Tiles comme QGIS (changer COG_NAME): `http://localhost:8082/cog/tiles/{z}/{x}/{y}.png?url=http://host.docker.internal:8001/COG_NAME.tif`

**Vector service**
la page principale : `http://localhost:8083`
Pour voir toutes les collections vectorielles (pas nécessairement STAC, il s'agit d'un service indépendant) : `http://localhost:8083/collections`
Pour afficher les données d'une collections précises (Changer VECTOR_TABLE) : `http://localhost:8083/collections/public.VECTOR_TABLE/items`

**STAC Browser**
la page principale du frontend STAC : `http://localhost:8085`
Pour voir les items du collection précise : `http://localhost:8085/collections/my-collection`
Pour voir un item en particulier : `http://localhost:8085/collections/my-collection/items/example-item-id`