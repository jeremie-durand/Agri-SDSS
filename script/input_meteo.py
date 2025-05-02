# -*- coding: utf-8 -*-
import requests
import pandas as pd
import geopandas as gpd

# --------------------------------------------------------------------
# FUNCTIONS
# --------------------------------------------------------------------
def meteo_data_GeoMet_pipeline(data, variables, use_parcelle=False, use_study_site=False):
    """
    Fonction de pipeline pour traiter les données météo sur plusieurs années.

    Cette fonction prend en entrée un GeoDataFrame et renvoie un DataFrame contenant les moyennes annuelles,
    les sommes annuelles et les écarts types des variables météo extraites à partir de l'API de Météo Canada (GeoMet).

    Args:
        data (gpd.GeoDataFrame): Le GeoDataFrame contenant les données géographiques. #TODO Supporter d'autres formats de fichiers (ex: shapefile, etc.)
        variables (list): Liste des variables météo à traiter.
        use_parcelle (bool): Indique si une parcelle spécifique doit être utilisée.
        use_study_site (bool): Indique si une zone d'étude doit être utilisée.
    """
    try:
        # Initialisation des variables
        bbox = None  # Initialisation de la variable bbox

        # Vérification si le fichier est un GeoDataFrame
        if not isinstance(data, gpd.GeoDataFrame):
            raise ValueError("Le fichier doit être un GeoDataFrame.")
        
        # Changer le CRS
        data = data.to_crs(epsg=4979)  # OGC CRS84 -> EPSG:4979

        if use_parcelle is True: # On prend une parcelle spécifique
            data = data.iloc[0]  # Exemple hardcodé d'une parcelle filtrée
            bbox = data.geometry.bounds  # [minX, minY, maxX, maxY]

        if use_study_site is True: # On prend la zone d'étude
            bbox = data.total_bounds  # [minX, minY, maxX, maxY]

        # URL l'API de Météo Canada (GeoMet-OGC-API) pour les données journalières
        url = "https://api.weather.gc.ca/collections/climate-daily/items"

        # Initialisation du DataFrame pour stocker les résultats annuels
        annual_results = []

        # Calculer les statistiques pour les 10 dernières années
        current_year = 2025  # Exemple : année actuelle hardcodée
        for year in range(current_year - 10, current_year):
            # Définir la plage de dates pour l'année
            start_date = f"{year}-01-01" #TODO À modifier pour le début de la période de croissance
            end_date = f"{year}-12-31" #TODO À modifier pour la fin de la période de croissance

            # Ajout du bbox et des dates comme paramètres dans la requête
            params = {
                "datetime": f"{start_date}/{end_date}",  # Format : YYYY-MM-DD/YYYY-MM-DD
                "bbox": f"{bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]}",  # Format : minX,minY,maxX,maxY
                "limit": 10000,
                "properties": ",".join(variables),  # Propriétés à récupérer
                "f": "json",  # Format de la réponse
            }

            # Envoie de la requête GET
            response = requests.get(url, params=params)
            print(f"URL complète de la requête pour {year} :", response.url)

            # Vérification du code de réponse
            if response.status_code == 200:
                data = response.json()
                if not data["features"]:  # Si aucune station n'est trouvée
                    print(f"Aucune station trouvée pour l'année {year}.")
                    continue

                # Traitement des données
                data_response = {}
                for feature in data["features"]:
                    for key, value in feature["properties"].items():
                        if key not in data_response:
                            data_response[key] = []
                        data_response[key].append(value if value is not None else 0)

                # Conversion des données en DataFrame
                df_year = pd.DataFrame(data_response)

                # Calculer les statistiques pour chaque variable
                mean_values = df_year[variables].mean().reset_index() # reset_index() pour transformer la série en DataFrame
                mean_values.columns = ["variable", "mean_value"] # Renommer les colonnes

                sum_values = df_year[variables].sum().reset_index()
                sum_values.columns = ["variable", "sum_value"]

                std_values = df_year[variables].std().reset_index()
                std_values.columns = ["variable", "std_value"]

                # Fusionner les résultats
                result = pd.merge(mean_values, sum_values, on="variable")
                result = pd.merge(result, std_values, on="variable")

                # Ajouter l'année comme colonne
                result["year"] = year
                annual_results.append(result)

            elif response.status_code == 400:
                print(f"Erreur 400 : Aucune donnée disponible pour l'année {year}.")
            else:
                print(f"Erreur lors de la requête pour l'année {year} : {response.status_code}")

        # Combiner les résultats annuels dans un DataFrame final
        df_annual_results = pd.concat(annual_results, ignore_index=True)

        return df_annual_results

    except ValueError as ve:
        print(f"Erreur de validation : {ve}")
    except requests.RequestException as re:
        print(f"Erreur de requête HTTP : {re}")
    except Exception as e:
        print(f"Erreur inattendue : {e}")