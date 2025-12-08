# Read GeoParquet with Leaflet
Leaflet does not natively support reading of GeoParquet. That's why we need to create a workflow for this task.
Here is the workflow using [OGC API standards](https://ogcapi.ogc.org/).

```mermaid
sequenceDiagram

    autonumber

    participant Pipeline as Vector Pipeline

    participant VectorAPI as Vector API (OGC API)

    participant Leaflet

    participant Browser as Browser fetch()

  

    Note over Pipeline,VectorAPI: 1. Processing Geoparquet into Vector Services

    Pipeline ->> Pipeline: Parse vector data

    Pipeline ->> VectorAPI: Expose as OGC API - Features and OGC API - Tiles (MVT)

  

    Note over Leaflet,VectorAPI: 2. Reading vector data in Leaflet

  

    alt Small dataset (GeoJSON feasible)

        Leaflet ->> Browser: fetch(.../items?f=json)

        Browser ->> VectorAPI: HTTP GET items?f=json

        VectorAPI -->> Browser: Return GeoJSON

        Browser -->> Leaflet: Pass parsed GeoJSON

        Leaflet ->> Leaflet: L.geoJSON(data).addTo(map)

    else Large dataset (Tiles recommended)

        Leaflet ->> VectorAPI: Request MVT tile {z}/{x}/{y}?f=mvt

        VectorAPI -->> Leaflet: Return MVT tile

        Leaflet ->> Leaflet: Render vectorGrid.protobuf with styling

    end
```
