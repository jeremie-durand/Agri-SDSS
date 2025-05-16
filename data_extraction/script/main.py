# -*- coding: utf-8 -*-
print("main.py started...")
# scripts
from input_meteo import meteo_data_GeoMet_pipeline # input_meteo.py

# Python standard library
import json
import os

# Librairies
import pandas as pd  # Pour manipuler des données tabulaires
import geopandas as gpd # Pour manipuler des données géographiques

# --------------------------------------------------------------------
# VARIABLES
# --------------------------------------------------------------------
# Construire le chemin vers config.json basé sur l'emplacement du script
config_path = os.path.join(os.path.dirname(__file__), 'config.json')

# Chargement de la configuration
with open(config_path, 'r') as f:
    config = json.load(f)

DIR = config["DIR"]
METEO_VARIABLES = config["METEO_VARIABLES"]

# inputs
sud_du_quebec = gpd.read_file(DIR + "/data/study_site/sud_du_quebec.shp")  
#bdppad = gpd.read_file(DIR + "/data/BDPPAD/BDPPAD_v03_AN_2024_s_20241125.shp")

# --------------------------------------------------------------------
# LAUNCHING SCRIPTS
# --------------------------------------------------------------------
data_response = meteo_data_GeoMet_pipeline(data=sud_du_quebec, variables=METEO_VARIABLES, use_study_site=True)  # Exemple d'utilisation de la fonction

# Vérification des colonnes et des données
print("Colonnes du DataFrame :", data_response.columns)
print("Aperçu des données extraites :")
print(data_response)