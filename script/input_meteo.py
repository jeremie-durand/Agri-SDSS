# -*- coding: utf-8 -*-
import requests
import geopandas as gpd

import json
import os

# Construire le chemin vers config.json basé sur l'emplacement du script
config_path = os.path.join(os.path.dirname(__file__), 'config.json')

# Chargement de la configuration
with open(config_path, 'r') as f:
    config = json.load(f)

DIR = config["DIR"]

# input
sud_du_quebec = gpd.read_file(DIR + "/data/sud_du_quebec/sud_du_quebec.shp")  # Chargement du fichier GeoJSON

# changer crs
sud_du_quebec = sud_du_quebec.to_crs(epsg=4979)  # OGC CRS84 -> EPSG:4979 

# Extraction du bounding box (bbox)
bbox = sud_du_quebec.total_bounds  # [minX, minY, maxX, maxY]
print(bbox)  # Affichage de la bbox pour vérification

# Création de la géométrie GeoJSON pour la bbox
geojson_bbox = {
    "type": "Polygon",
    "coordinates": [[
        [bbox[0], bbox[1]],  # minX, minY
        [bbox[0], bbox[3]],  # minX, maxY
        [bbox[2], bbox[3]],  # maxX, maxY
        [bbox[2], bbox[1]],  # maxX, minY
        [bbox[0], bbox[1]]   # Retour au point de départ
    ]]
}

# URL de base
url = "https://api.weather.gc.ca/collections/climate-daily/items" # GeoMet-OGC-API

# Ajout du bbox comme paramètre dans la requête
params = {
    "datetime": "2025-03-01/2025-03-31",  # Exemple : données pour janvier 2025
    "STATION_NAME": "SHERBROOKE",
    "properties": "MAX_TEMPERATURE",  # Propriétés à récupérer
    "f": "json",  # Format de la réponse
}

# Envoie de la requête GET
response = requests.get(url , params=params)

# Affichage de l'URL complète de la requête
print("URL complète de la requête :", response.url)


# Vérification du code de réponse
if response.status_code == 200:
    data = response.json()
    print(data)
else:
    print(f"Erreur lors de la requête : {response.status_code}")