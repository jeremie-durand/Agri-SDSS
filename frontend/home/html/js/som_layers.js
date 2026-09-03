import { map } from './state.js';

var _somBoundaryLayer = null;

/**
 * Initialise the SOM field boundaries vector tile layer and wire the toggle checkbox.
 * Green polygons have GEE training data; grey polygons are boundary-only.
 *
 * @param {HTMLInputElement} checkbox - The toggle checkbox element.
 */
export function initSomBoundaryLayer(checkbox) {
    _somBoundaryLayer = L.vectorGrid.protobuf(
        '/vector-api/postgis/collections/public.som_field_boundaries/tiles/WebMercatorQuad/{z}/{x}/{y}',
        {
            vectorTileLayerStyles: {
                default: function(props) {
                    var hasData = props.has_gee_data;
                    return {
                        weight: 1.2,
                        color:       hasData ? '#34d399' : '#64748b',
                        fillColor:   hasData ? '#34d399' : '#64748b',
                        fillOpacity: hasData ? 0.22 : 0.07,
                        fill: true
                    };
                }
            },
            interactive: false,
            maxZoom: 18,
            rendererFactory: L.canvas.tile
        }
    );

    checkbox.addEventListener('change', function() {
        if (checkbox.checked) map.addLayer(_somBoundaryLayer);
        else map.removeLayer(_somBoundaryLayer);
    });
}
