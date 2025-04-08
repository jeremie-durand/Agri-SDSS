# -*- coding: utf-8 -*-
import requests
import geopandas as gpd
import pandas as pd
import numpy as np

import json
import os

# Construire le chemin vers config.json basé sur l'emplacement du script
config_path = os.path.join(os.path.dirname(__file__), 'config.json')

# Chargement de la configuration
with open(config_path, 'r') as f:
    config = json.load(f)

DIR = config["DIR"]
variable = ["TOTAL_PRECIPITATION", "MEAN_TEMPERATURE"]  # Exemple de variable à extraire

# input
sud_du_quebec = gpd.read_file(DIR + "/data/study_site/sud_du_quebec.shp")  # Chargement du fichier GeoJSON

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
    "datetime": "2025-03-31",  # Exemple : données pour mars 2025 : 2025-03-01/2025-03-31
    #"STATION_NAME": "SHERBROOKE",
    "bbox": f"{bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]}",  # Format : minX,minY,maxX,maxY
    "limit": 10000,  # Limite de résultats
    "properties": ",".join(variable),  # Propriétés à récupérer en chaine de caractères
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

data_response = {}
# Parcours des features dans la réponse
for feature in data["features"]:
    for key, value in feature["properties"].items():
        # Initialisation de la clé dans le dictionnaire si elle n'existe pas encore
        if key not in data_response:
            data_response[key] = []

        # Ajout de la valeur (remplace None par 0 pour les variables numériques)
        data_response[key].append(value if value is not None else 0)

# Vérification que toutes les colonnes ont la même longueur
# Si une clé manque dans certaines features, on remplit avec des valeurs par défaut (None ou 0)
max_length = max(len(values) for values in data_response.values())
for key in data_response:
    while len(data_response[key]) < max_length:
        data_response[key].append(0)  # Remplissage avec 0 pour les colonnes manquantes

# Conversion des données en DataFrame
df = pd.DataFrame(data_response)

# Vérification des colonnes et des données
print("Colonnes du DataFrame :", df.columns)
print("Aperçu des données extraites :")
print(df.head())

# Ajout des colonnes de latitude et longitude
#df["latitude"] = [feature["geometry"]["coordinates"][1] for feature in data["features"]]
#df["longitude"] = [feature["geometry"]["coordinates"][0] for feature in data["features"]]

# Calcul des statistiques pour chaque variable
for column in df.columns:
    if pd.api.types.is_numeric_dtype(df[column]):  # Vérification si la colonne est numérique
        mean_value = df[column].mean()
        min_value = df[column].min()
        max_value = df[column].max()
        count_value = df[column].count()

        # Affichage des résultats avec 2 chiffres après la virgule
        print(f"\nStatistiques pour {column} :")
        print(f"Moyenne : {mean_value:.2f}")
        print(f"Minimum : {min_value:.2f}")
        print(f"Maximum : {max_value:.2f}")
        print(f"Nombre de valeurs : {count_value}")