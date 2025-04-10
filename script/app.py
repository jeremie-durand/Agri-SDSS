# -*- coding: utf-8 -*-
# Scripts
from input_gee import authenticate_gee, create_map # input_gee.py

# Librairies
from flask import Flask, request, jsonify, render_template # Pour créer une application web
import geopandas as gpd # Pour manipuler des données géographiques
import ee

# Python standard library
import logging
import json
import os

# --------------------------------------------------------------------
# VARIABLES
# --------------------------------------------------------------------
# Construire le chemin vers config.json basé sur l'emplacement du script
config_path = os.path.join(os.path.dirname(__file__), 'config.json')

# Chargement de la configuration
with open(config_path, 'r') as f:
    config = json.load(f)


DIR = config["DIR"]
HTML_TEMPLATES_DIR = config["HTML_TEMPLATES_DIR"]

bdppad = gpd.read_file(DIR + "/data/BDPPAD/BDPPAD_v03_AN_2024_s_20241125.shp")

#Initialiser Earth Engine
authenticate_gee()
# --------------------------------------------------------------------
# Flask backend
# --------------------------------------------------------------------
app = Flask(__name__,
    template_folder= HTML_TEMPLATES_DIR
)

# Configuration du logging
logging.basicConfig(
    filename='script/app.log',  # Nom du fichier de log
    level=logging.DEBUG,  # Niveau de logging
    format='%(asctime)s - %(levelname)s - %(message)s'  # Format du log
)

@app.route('/', methods=['GET', 'POST'])
def home():
    return render_template('index.html')

# Route 1️ : Génération de la carte
@app.route('/generate-map', methods=['POST'])
def generate_map():
    try:
        app.logger.info('generate-map begin')

        # 2. Récupérer les données de la requête POST
        data = request.get_json()
        start_year = int(data.get('start_year'))
        end_year = int(data.get('end_year'))
        satellite = data.get('satellite')
        study_area = data.get('study_area')
        selected_indices = data.get('indices', []) # Ex: ['NDVI', 'SAVI']

        # 3. Charger la zone d'étude
        if study_area == 'sud_du_quebec':
            study_area = ee.FeatureCollection('projects/ee-jeremie539yt/assets/sud_du_quebec')

        elif study_area == 'parcelle':
            bdppad = gpd.read_file(DIR + "/data/BDPPAD/BDPPAD_v03_AN_2024_s_20241125.shp")
            # changer crs
            #bdppad = bdppad.to_crs(epsg=4979)  # OGC CRS84 -> EPSG:4979
            # on prend une parcelle spécifique
            study_area = bdppad.iloc[0]  # Exemple
            # convert to geodataframe
            study_area = gpd.GeoDataFrame(geometry=[study_area.geometry])
            # Extraction du bounding box (bbox)
            #bbox = data.geometry.bounds  # [minX, minY, maxX, maxY]

        # 4. Générer la carte HTML
        try:
            app.logger.info('--- creating map ---')
            generated_map_html = create_map(start_year, end_year, study_area, satellite, selected_indices)
            #app.logger.info(f"Generated map HTML: {generated_map_html}")
        except Exception as e:
            app.logger.error('Erreur lors de la génération de la carte (génération du HTML) : {}'.format(e))
            return jsonify({'success': False, 'message': 'Erreur de génération de la carte : {}'.format(str(e))}), 500

        return jsonify({'success': True, 'map_html': generated_map_html})

    except Exception as e:
        app.logger.error("Erreur globale lors du traitement de la requête /generate-map : {}".format(e))
        return jsonify({'success': False, 'message': 'Erreur globale lors du traitement : {}'.format(str(e))})
    
if __name__ == "__main__":
    app.run(debug=True)