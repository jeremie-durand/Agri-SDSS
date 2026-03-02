# SERIES_SOLS_QUEBEC - Quebec Soil Series Database

Comprehensive soil series data for Quebec including linked relational tables with detailed soil properties, textures, and organic matter studies.

**Source**: [Séries de sols (.csv) - Tables liées à carte pédo par FK](https://irda.qc.ca/fr/outils/donnees-pedologiques-sols/cartes-pedologiques-quebec-irda/#:~:text=Information%20suppl%C3%A9mentaire%3A%20Bases%20de%20donn%C3%A9es%20sur%20les%20sols%20li%C3%A9es%20aux%20cartes) - IRDA provides soil series data in CSV format linked to pedological maps through foreign keys, enabling detailed soil property analysis across Quebec.

## Overview

**SERIES_SOLS_QUEBEC** provides relational soil series data from Quebec's pedological database, maintained by the Institut de recherche et de développement en agroenvironnement (IRDA). This dataset contains detailed soil characteristics including texture, depth, organic matter content, and temporal study data linked through foreign keys to pedological map features.

The data is integrated through the eoAPI backend infrastructure using OGC API - Features standard, enabling modern vector data access with nested properties and comprehensive spatial queries.

## Data Details

| Property | Value |
|----------|-------|
| **Type** | Vector (Relational Database) |
| **Format** | CSV (linked tables) |
| **CRS** | Na |
| **Geometry Type** | Na |
| **Spatial Extent** | Na |
| **Data Structure** | Linked soil series studies with Foreign Key (FK) |
| **Update Frequency** | Na |
| **License** | Open Government License - Quebec (OGL-Q) |

### Data Structure

There are two datasets:
- Propriétés pédologiques du sol dominant (PPSD)
- Propriétés physico-chimique par couche (PPC)

These datasets are linked with [CARTE PEDOLOGIQUE](/docs/data/sources/CARTE_PEDOLOGIQUE_QUEBEC.md)

## Using SERIES_SOLS_QUEBEC Data

**Note**: The following examples require services to be running (`docker compose up`).

## Integration Example - Proof of Concept

A proof of concept demonstrates the integration in a Leaflet playground: https://jsfiddle.net/glenn/8rgpo3q8/

The example shows:
- Hardcoded GeoJSON example simulating the API collection endpoint structure (`fieldsGeoJSON`)
- An adapter function to read nested "properties" and display them in Leaflet popups
- Styling based on soil properties (e.g., organic matter content)

This minimalist example can be extended with more complete data and advanced visualization tools.

### HTML
```HTML
<link rel="stylesheet" href="https://unpkg.com/leaflet/dist/leaflet.css" />
<div id="map"></div>
<script src="https://unpkg.com/leaflet/dist/leaflet.js"></script>
```

### CSS
```CSS
.map {
  width: 100%;
  height: 480px;
}
#map { height: 600px; width: 100%; }
    table { border-collapse: collapse; width: 100%; }
    th, td { border: 1px solid black; padding: 2px 5px; text-align: center; }
```

### JavaScript
```JavaScript
/* ============================================
   Exemple GeoJSON avec propriétés imbriquées compatible avec OGCI API - Features
   ============================================ */
const fieldsGeoJSON = {
  "type": "FeatureCollection",
  "features": [
    {
      "type": "Feature",
      "id": 1,
      "geometry": {
        "type": "Polygon",
        "coordinates": [[
          [-72.3, 46.1], [-72.3, 46.2], [-72.2, 46.2], [-72.2, 46.1], [-72.3, 46.1]
        ]]
      },
      "properties": {
        "name": "Champ Alpha",
        "soil_series_studies": [
          {"year": 2020, "depth": "0-30", "texture": "SL", "organic_matter": 2.8},
          {"year": 2021, "depth": "0-30", "texture": "CL", "organic_matter": 3.5},
          {"year": 2022, "depth": "0-30", "texture": "SCL", "organic_matter": 4.1}
        ]
      }
    },
    {
      "type": "Feature",
      "id": 2,
      "geometry": {
        "type": "Polygon",
        "coordinates": [[
          [-72.4, 46.0], [-72.4, 46.1], [-72.3, 46.1], [-72.3, 46.0], [-72.4, 46.0]
        ]]
      },
      "properties": {
        "name": "Champ Bravo",
        "soil_series_studies": [
          {"year": 2021, "depth": "0-25", "texture": "CL", "organic_matter": 3.2}
        ]
      }
    },
    {
      "type": "Feature",
      "id": 3,
      "geometry": {
        "type": "Polygon",
        "coordinates": [[
          [-72.2, 46.0], [-72.2, 46.05], [-72.15, 46.05], [-72.15, 46.0], [-72.2, 46.0]
        ]]
      },
      "properties": {
        "name": "Champ Charlie",
        "soil_series_studies": []
      }
    }
  ]
};

/* ============================================
   Fonction adaptateur pour afficher les properties dans les popups Leaflet
   ============================================ */
function formatFieldFeature(feature) {
  const name = feature.properties?.name || "Champ inconnu";
  const soilSeries = feature.properties?.soil_series_studies || [];

  let html = `<h3>${name}</h3>`;

  if (soilSeries.length === 0) {
    html += "<p>Aucune étude de sol disponible</p>";
  } else {
    html += "<table><tr><th>Année</th><th>Horizon</th><th>Texture</th><th>Matière organique (%)</th></tr>";
    soilSeries.forEach(s => {
      html += `<tr>
        <td>${s.year || "-"}</td>
        <td>${s.depth || "-"}</td>
        <td>${s.texture || "-"}</td>
        <td>${s.organic_matter || "-"}</td>
      </tr>`;
    });
    html += "</table>";
  }

  return html;
}

/* ============================================
   Initialisation Leaflet
   ============================================ */
const map = L.map('map').setView([46.05, -72.25], 12);

L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
  attribution: '© OpenStreetMap contributors'
}).addTo(map);

/* ============================================
   Ajout du GeoJSON avec styles et popup
   ============================================ */
L.geoJSON(fieldsGeoJSON, {
  style: function(feature) {
    // Exemple : couleur selon la première valeur de matière organique
    const firstOM = feature.properties?.soil_series_studies?.[0]?.organic_matter;
    return {
      color: firstOM > 3 ? "green" : "orange",
      weight: 2,
      fillOpacity: 0.5
    };
  },
  onEachFeature: function(feature, layer) {
    layer.bindPopup(formatFieldFeature(feature));
  }
}).addTo(map);
```

**Live Demo**: [Leaflet Playground - Soil Series Integration](https://jsfiddle.net/glenn/8rgpo3q8/)

## Metadata

- **Publisher**: Institut de recherche et de développement en agroenvironnement (IRDA)
- **Language**: French
- **Data Model**: Relational (main features + linked studies via FK)
- **API Standard**: OGC API - Features (GeoJSON)
- **External Links**:
  - IRDA Soil Data Portal: https://irda.qc.ca/fr/outils/donnees-pedologiques-sols/cartes-pedologiques-quebec-irda/
  - Données Québec: https://www.donneesquebec.ca/