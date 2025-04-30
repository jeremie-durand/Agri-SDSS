# -*- coding: utf-8 -*-
import requests
import pandas as pd
import geopandas as gpd

# --------------------------------------------------------------------
# FUNCTIONS
# --------------------------------------------------------------------
def meteo_data_GeoMet_pipeline(data, variables, use_bdppad=False, use_study_site=False):
    """
    Fonction de pipeline pour traiter les données météo sur plusieurs années.

    Cette fonction prend en entrée un GeoDataFrame et renvoie un DataFrame contenant les moyennes annuelles
    et les sommes annuelles des variables météo extraites à partir de l'API de Météo Canada (GeoMet).

    Args:
        data (gpd.GeoDataFrame): Le GeoDataFrame contenant les données géographiques.
        variables_mean (list): Liste des variables météo pour lesquelles calculer la moyenne.
        variables_sum (list): Liste des variables météo pour lesquelles calculer la somme.
        use_bdppad (bool): Indique si une parcelle spécifique doit être utilisée.
        use_study_site (bool): Indique si la zone d'étude doit être utilisée.
    """
    try:
        # Initialisation des variables
        bbox = None  # Initialisation de la variable bbox
        variables_mean = []  # Liste pour les variables à calculer la moyenne
        variables_sum = []  # Liste pour les variables à calculer la somme

        # Variables pour la moyenne et la somme automatically using variables
        if variables is None:
            raise ValueError("Aucune variable spécifiée.")
        
        if "MEAN_TEMPERATURE" in variables:
            variables_mean.append("MEAN_TEMPERATURE")

        if "HEATING_DEGREE_DAYS" in variables:
            variables_mean.append("HEATING_DEGREE_DAYS")

        if "TOTAL_PRECIPITATION" in variables:
            variables_sum.append("TOTAL_PRECIPITATION")
        
        if "TOTAL_RAIN" in variables:
            variables_sum.append("TOTAL_RAIN")

        # Vérification si le fichier est un GeoDataFrame
        if not isinstance(data, gpd.GeoDataFrame):
            raise ValueError("Le fichier doit être un GeoDataFrame.")
        
        # Changer le CRS
        data = data.to_crs(epsg=4979)  # OGC CRS84 -> EPSG:4979

        # Filtrer les données pour ne garder que celles de la région d'intérêt
        if use_bdppad is True:
            # On prend une parcelle spécifique
            data = data.iloc[0]  # Exemple hardcodé
            bbox = data.geometry.bounds  # [minX, minY, maxX, maxY]

        if use_study_site is True:
            # On prend la zone d'étude
            bbox = data.total_bounds  # [minX, minY, maxX, maxY]

        # URL de base de l'API de Météo Canada (GeoMet-OGC-API)
        url = "https://api.weather.gc.ca/collections/climate-daily/items"

        # Initialisation du DataFrame pour stocker les moyennes et sommes annuelles
        annual_results = []

        # Calculer les moyennes et sommes pour les 5 dernières années
        current_year = 2025  # Exemple : année actuelle
        for year in range(current_year - 5, current_year):
            # Définir la plage de dates pour l'année
            start_date = f"{year}-01-01"
            end_date = f"{year}-12-31"

            # Ajout du bbox et des dates comme paramètres dans la requête
            params = {
                "datetime": f"{start_date}/{end_date}",  # Format : YYYY-MM-DD/YYYY-MM-DD
                "bbox": f"{bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]}",  # Format : minX,minY,maxX,maxY
                "limit": 10000,  # Limite de résultats
                "properties": ",".join(variables_mean + variables_sum),  # Propriétés à récupérer
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

                # Pipeline pour les moyennes
                mean_values = pd.DataFrame()
                if variables_mean:
                    mean_values = df_year[variables_mean].mean().reset_index()
                    mean_values.columns = ["variable", "mean_value"]

                # Pipeline pour les sommes
                sum_values = pd.DataFrame()
                if variables_sum:
                    sum_values = df_year[variables_sum].sum().reset_index()
                    sum_values.columns = ["variable", "sum_value"]

                # Ajouter l'année comme colonne
                result = pd.concat([mean_values, sum_values])
                result["year"] = year
                annual_results.append(result)

            elif response.status_code == 400:
                print(f"Erreur 400 : Aucune donnée disponible pour l'année {year}.")
            else:
                print(f"Erreur lors de la requête pour l'année {year} : {response.status_code}")

        # Combiner les résultats annuels dans un DataFrame final
        df_annual_results = pd.concat(annual_results, ignore_index=True)
        df_annual_results = df_annual_results.pivot(index="year", columns="variable", values=["mean_value", "sum_value"]) # Pivot pour avoir les années comme index et les variables comme colonnes
        #df_annual_results.columns = [f"{col[1]}_{col[0]}" for col in df_annual_results.columns]  # Renommer les colonnes
        df_annual_results.reset_index(inplace=True)  # Réinitialiser l'index pour avoir l'année comme colonne

        return df_annual_results

    except ValueError as ve:
        print(f"Erreur de validation : {ve}")
    except requests.RequestException as re:
        print(f"Erreur de requête HTTP : {re}")
    except Exception as e:
        print(f"Erreur inattendue : {e}")