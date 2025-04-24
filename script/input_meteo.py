# -*- coding: utf-8 -*-
import requests
import pandas as pd
import geopandas as gpd

# --------------------------------------------------------------------
# FUNCTIONS
# --------------------------------------------------------------------
def meteo_data_GeoMet_pipeline(data, variables, use_bdppad=False, use_study_site=False):
    """
    Fonction de pipeline pour traiter les données météo.

    Cette fonction prend en entrée un GeoDataFrame et renvoie un GeoDataFrame contenant les données météo
    extraites à partir de l'API de Météo Canada (GeoMet) et des variables d'entrées. Elle gère également le filtrage des données en fonction de la région
    d'intérêt (parcelle spécifique ou zone d'étude) et élargit le bounding box si aucune station n'est trouvée.

    Args:
        data (gpd.GeoDataFrame): Le GeoDataFrame contenant les données géographiques.
        variables (list): Liste des variables météo à extraire.
        use_bdppad (bool): Indique si une parcelle spécifique doit être utilisée.
        use_study_site (bool): Indique si la zone d'étude doit être utilisée.
    """
    try:
        # Initialisation des variables
        bbox = None  # Initialisation de la variable bbox

        # Vérification si le fichier est un GeoDataFrame
        if not isinstance(data, gpd.GeoDataFrame):
            raise ValueError("Le fichier doit être un GeoDataFrame.")
        
        #print(data.head())  # Affichage de l'aperçu des données

        # Changer le CRS
        data = data.to_crs(epsg=4979)  # OGC CRS84 -> EPSG:4979

        # Filtrer les données pour ne garder que celles de la région d'intérêt
        print(use_bdppad, use_study_site)
        if use_bdppad is True:
            # On prend une parcelle spécifique
            data = data.iloc[0]  # Exemple hardcodé #TODO à remplacer par une sélection dynamique selon la position spatiale
            #print("Aperçu de la parcelle :")
            #print(data)

            # Extraction du bounding box (bbox)
            bbox = data.geometry.bounds  # [minX, minY, maxX, maxY]
            #print(bbox)  # Affichage de la bbox pour vérification

        if use_study_site is True:
            # On prend la zone d'étude
            bbox = data.total_bounds  # [minX, minY, maxX, maxY]
            #print(bbox)

        # URL de base de l'API de Météo Canada (GeoMet-OGC-API)
        url = "https://api.weather.gc.ca/collections/climate-daily/items" 

        # Ajout du bbox comme paramètre dans la requête
        params = {
            "datetime": "2025-04-24",  # Exemple : données pour mars 2025 : 2025-03-01/2025-03-31 #TODO à remplacer par une sélection dynamique
            "bbox": f"{bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]}",  # Format : minX,minY,maxX,maxY
            "limit": 10000,  # Limite de résultats
            "properties": ",".join(variables),  # Propriétés à récupérer en chaine de caractères
            "f": "json",  # Format de la réponse
        }

        # Envoie de la requête GET
        response = requests.get(url, params=params)
        # Affichage de l'URL complète de la requête
        print("URL complète de la requête :", response.url)

        # Vérification du code de réponse
        if response.status_code == 200:
            data = response.json()
            if not data["features"]:  # Si aucune station n'est trouvée
                print("Aucune station trouvée dans le bbox. Élargissement progressif du bbox...")

                # Calcul du centre du bbox
                bbox_center = [(bbox[1] + bbox[3]) / 2, (bbox[0] + bbox[2]) / 2]  # [latitude, longitude]

                # Initialisation des variables pour élargir le bbox
                expansion_factor = 0.25  # Augmenter de 25% à chaque itération
                iteration = 0

                while True:  # Boucle infinie jusqu'à trouver une station
                    # Élargir le bbox
                    width = (bbox[2] - bbox[0]) * (1 + expansion_factor)
                    height = (bbox[3] - bbox[1]) * (1 + expansion_factor)
                    bbox = [
                        bbox_center[1] - width / 2,  # minX
                        bbox_center[0] - height / 2,  # minY
                        bbox_center[1] + width / 2,  # maxX
                        bbox_center[0] + height / 2,  # maxY
                    ]

                    # Nouvelle requête avec le bbox élargi
                    params["bbox"] = f"{bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]}"
                    response = requests.get(url, params=params)

                    if response.status_code == 200:
                        data = response.json()
                        if data["features"]:  # Si des stations sont trouvées
                            print(f"Stations trouvées après élargissement du bbox (itération {iteration + 1}) :")
                            break
                    elif response.status_code == 400:
                        raise ValueError("Erreur 400 : Aucune donnée disponible pour ce bbox.")
                    else:
                        print(f"Erreur lors de la requête avec bbox élargi : {response.status_code}")
                        exit(1)

                    iteration += 1
                    print(f"Élargissement du bbox, itération {iteration}...")

            else:
                print("Stations trouvées dans le bbox.")
        elif response.status_code == 400:
            raise ValueError("Erreur 400 : Aucune donnée disponible pour ce bbox.")
        else:
            print(f"Erreur lors de la requête : {response.status_code}")
            exit(1)

        # Traitement des données
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
        max_length = max(len(values) for values in data_response.values())
        for key in data_response:
            while len(data_response[key]) < max_length:
                data_response[key].append(0)  # Remplissage avec 0 pour les colonnes manquantes

        # Conversion des données en DataFrame
        df_reponse = pd.DataFrame(data_response)

        #TODO ajouter les colonnes de latitude et longitude

        return df_reponse

    except ValueError as ve:
        print(f"Erreur de validation : {ve}")
    except requests.RequestException as re:
        print(f"Erreur de requête HTTP : {re}")
    except Exception as e:
        print(f"Erreur inattendue : {e}")