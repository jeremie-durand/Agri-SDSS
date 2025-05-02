# SAD-MOS
Projet de maîtrise sur le développement d'une architecture côté-serveur d'un système d'aide à la décision (SAD) afin d’optimiser le potentiel de la matière organique des sols (MOS) au Québec et les meilleurs pratiques pour l'atteindre

## Tools à tester
MapServer vs GeoServer -> serveur cartographique

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
