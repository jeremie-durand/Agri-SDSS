import React, { useEffect } from 'react';

interface SoilMapViewerProps {
  lat?: number;
  lon?: number;
  zoom?: number;
  bbox?: [number, number, number, number]; // [west, south, east, north]
}

export default function SoilMapViewer({ lat, lon, zoom = 10, bbox }: SoilMapViewerProps) {
  useEffect(() => {
    if (window.parent === window) return; // not embedded in iframe

    if (bbox) {
      window.parent.postMessage({ type: 'MOS_GIS_ZOOM', bbox }, '*');
    } else if (lat !== undefined && lon !== undefined) {
      window.parent.postMessage({ type: 'MOS_GIS_ZOOM', lat, lon, zoom }, '*');
    }
  }, [lat, lon, zoom, bbox]);

  if (lat === undefined || lon === undefined) {
    return (
      <div className="soil-map-viewer soil-map-viewer--empty">
        Select a location to view SOM potential.
      </div>
    );
  }

  const tileUrl = `/api/raster/tiles/{z}/{x}/{y}?layer=som_potential`;

  return (
    <div className="soil-map-viewer" data-testid="soil-map-viewer">
      <div className="soil-map-viewer__header">Soil Organic Matter Potential</div>
      <div
        className="soil-map-viewer__map"
        data-tile-url={tileUrl}
        data-lat={lat}
        data-lon={lon}
        data-zoom={zoom}
      />
    </div>
  );
}
