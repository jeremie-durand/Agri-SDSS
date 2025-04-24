# -*- coding: utf-8 -*-
import ee
import folium
import folium.plugins
from folium import LinearColormap
import geopandas as gpd

import sys
import platform
import logging

# Configuration du logging
logging.basicConfig(
    filename='script/app.log',  # Nom du fichier de log
    level=logging.DEBUG,  # Niveau de logging
    format='%(asctime)s - %(levelname)s - %(message)s'  # Format du log
)

# Logger pour Earth Engine
logger = logging.getLogger('EarthEngine')

# Bypass blessings if on Windows
if platform.system() == 'Windows':
    sys.modules['blessings'] = type('Terminal', (), {'Terminal': lambda *args, **kwargs: None})()


# --- Authentification et Initialisation Earth Engine ---
def authenticate_gee():
    try:
        #ee.Authenticate()
        ee.Initialize(project='ee-jeremie539yt')
        print("Earth Engine authenticated and initialized.")
    except Exception as e:
        print(f"Error during authentication: {e}")

# --------------------------------------------------------------------
# FUNCTIONS
# --------------------------------------------------------------------
def mask_clouds(image, satellite):
    """
    This function applies cloud and shadow masking to images from various satellites
    using their respective quality bands. Different satellites have specific quality
    assurance (QA) bands that indicate cloud, shadow, and cirrus cloud presence.

    Parameters:
        image (ee.Image): An Earth Engine image object containing QA bands for masking.
        satellite (str): The name of the satellite. Supported values are:
          - "Sentinel-2"

    Returns:
        ee.Image: The input image with clouds and shadows masked.

    Raises:
        ValueError: If the satellite name is not supported.
    """
    if satellite == "Sentinel-2":
        # Use the QA60 band to identify clouds
        qa = image.select('QA60')
        cloud_mask = qa.bitwiseAnd(1 << 3).eq(0)  # No clouds
        shadow_mask = qa.bitwiseAnd(1 << 4).eq(0)  # No shadows
        return image.updateMask(cloud_mask).updateMask(shadow_mask)
    
    else:
        # Raise an error for unsupported satellites
        raise ValueError("Unsupported satellite: {}".format(satellite))

def create_mosaic(images, bands_list, study_area, cloud_cover_band=False):
    """
    Creates a mosaic of the best images based on cloud cover, selects the desired bands, 
    and returns a median composite clipped to the study area.

    This function processes an image collection by optionally sorting it by cloud cover, 
    selecting specific bands, and computing the median composite. The result is then clipped 
    to the provided study area.

    Parameters:
        images (ee.ImageCollection): The image collection to process.
        bands_list (list): List of band names to include in the mosaic.
        study_area (ee.Geometry): Geometry defining the study area to clip the final mosaic.
        cloud_cover_band (str, optional): The name of the band used to sort images by cloud cover.
          If False, no sorting by cloud cover is applied. Default is False.

    Returns:
        ee.Image: A median composite of the selected bands, clipped to the study area.
    """
    # Optionally sort images by cloud cover percentage if a cloud cover band is specified
    if cloud_cover_band:
        images = images.sort(cloud_cover_band)
    
    # Select the desired bands from the image collection
    images_bands_filtered = images.select(bands_list)
    
    # Compute the median composite of the selected bands
    images_median = images_bands_filtered.median()
    
    # Clip the median composite to the specified study area
    mosaic = images_median.clip(study_area)
    
    return mosaic

def get_images_for_year(year, study_area, satellite):
    """
    Retrieves satellite images for a specified year, applies cloud masking, 
    creates a mosaic, and calculates vegetation indices.

    Parameters:
        year (int): The year for which to retrieve images (e.g., 2024).
        study_area (ee.Geometry): The geographic area to filter and clip the images.
        satellite (str): The satellite to use. Supported values:
          - "Sentinel-2"

    Returns:
        tuple:
          - ee.Image: A mosaic of the processed images for the specified year and area.
          - dict: Visualization parameters for true color rendering.
          - dict: Mapping of band names for the selected satellite.

    Raises:
      ValueError: If an unsupported satellite name is provided.
    """
    if satellite == "Sentinel-2":
        min_value = 0  # Visualization parameter: minimum reflectance
        max_value = 3000  # Visualization parameter: maximum reflectance
        
        # Sentinel-2 band mapping
        bands_mapping = {
            "red": "B4",   # Red band
            "green": "B3", # Green band
            "blue": "B2",  # Blue band
            "nir": "B8",   # Near Infrared (NIR) band
        }
        
        bands_list = list(bands_mapping.values())
        bands_trueColor = [bands_mapping["red"], bands_mapping["green"], bands_mapping["blue"]]
        
        # Filter Sentinel-2 image collection by date, region, and cloud cover
        images = (
            ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
            .filterBounds(study_area)
            .filterDate("{}-05-01".format(year), "{}-09-30".format(year))
            .filter(ee.Filter.lt('CLOUDY_PIXEL_PERCENTAGE', 20))
            .map(lambda image: mask_clouds(image, satellite))  # Apply cloud masking
        )
        
        mosaic = create_mosaic(images, bands_list, study_area, cloud_cover_band='CLOUDY_PIXEL_PERCENTAGE')

    else:
        raise ValueError("Unsupported satellite: {}".format(satellite))

    return mosaic, bands_mapping, min_value, max_value

def create_map(start_year, end_year, study_area, satellite, indices=()):
    """
    Create an interactive folium Map object and add yearly image mosaics 
    and vegetation indices as layers for a specified satellite and study area.

    Parameters:
        - start_year (int): The starting year for the image mosaics.
        - end_year (int): The ending year for the image mosaics.
        - study_area (ee.FeatureCollection): The study area geometry.
        - satellite (str): The satellite data source.
        - indices (tuple): A tuple of vegetation indices to include (e.g., ('NDVI', 'SAVI')).

    Returns:
        - str: HTML representation of the map for display in Jupyter notebooks.
    """
    # if study area is an ee.FeatureCollection, convert it to a geometry
    if isinstance(study_area, ee.FeatureCollection):
        study_area_geometry = study_area.geometry() 
        
        # Get the bounds of the geometry (min/max latitudes and longitudes)
        bounds = study_area_geometry.bounds().getInfo()  # This returns the bounds as a dictionary

        # Extract the coordinates for the bounds (Ensure study area is not more complex)
        coordinates = bounds['coordinates'][0]
        min_lng, min_lat = coordinates[0]  # Lower left corner
        max_lng, max_lat = coordinates[2]  # Upper right corner

        # log the coordinates
        logger.info(f"Bounding box coordinates: min_lng={min_lng}, min_lat={min_lat}, max_lng={max_lng}, max_lat={max_lat}")

    elif isinstance(study_area, gpd.GeoDataFrame):
        # If the study area is a GeoDataFrame (e.g., parcelle)
        if study_area.crs.to_epsg() != 4326:
            # Ensure the CRS is EPSG:4326 (WGS84)
            study_area = study_area.to_crs(epsg=4326)

        # Extract the geometry of the first parcel
        parcelle_geometry = study_area.geometry.iloc[0]

        # Convert the geometry to GeoJSON format
        geojson_bbox = parcelle_geometry.__geo_interface__

        # Extract the bounding box (minX, minY, maxX, maxY)
        bbox = parcelle_geometry.bounds  # [minX, minY, maxX, maxY]
        min_lng, min_lat, max_lng, max_lat = bbox

        # Log the bounding box coordinates
        logger.info(f"Bounding box coordinates: min_lng={min_lng}, min_lat={min_lat}, max_lng={max_lng}, max_lat={max_lat}")

        # Create a GeoJSON object for the bounding box
        geojson_bbox = {
            "type": "Polygon",
            "coordinates": [[
                [min_lng, min_lat],  # Bottom-left
                [min_lng, max_lat],  # Top-left
                [max_lng, max_lat],  # Top-right
                [max_lng, min_lat],  # Bottom-right
                [min_lng, min_lat]   # Close the polygon
            ]]
        }

        # Log the generated GeoJSON
        logger.info(f"GeoJSON generated: {geojson_bbox}")

    else:
        raise ValueError("Unsupported study area type. Must be ee.FeatureCollection or gpd.GeoDataFrame.")

    # Dynamically center the map based on the study area centroid
    map_center = [study_area_geometry.centroid().coordinates().get(1).getInfo(), 
                  study_area_geometry.centroid().coordinates().get(0).getInfo()]
    Map = folium.Map(location=map_center, zoom_start=8)

    # Loop through each year and add layers for the satellite imagery and indices
    for year in range(start_year, end_year + 1):
        # Get the mosaic, visualization parameters, and band mapping for the year
        mosaic, bands_mapping, min_value, max_value = get_images_for_year(year, study_area, satellite)
        bands_trueColor = ["red", "green", "blue"]

        # Define visualization parameters for true color display
        vis_params = mosaic.getThumbUrl({
            'min': min_value,
            'max': max_value,
            'region' : study_area_geometry,
            'dimensions': '800x600'
        })

        mosaic_palette = LinearColormap(
            ["red", "green", "blue"],  # True color
            vmin=min_value, vmax=max_value  # NDVI values typically range from -1 to 1
        ).to_step(n=9)  # Step allows you to adjust the number of colors in the palette

        # Add the mosaic (true color) as a layer
        folium.raster_layers.ImageOverlay(
            image=vis_params,
            attr='Google Earth Engine',
            name="{} - {}".format(year, satellite),
            overlay=True,
            control=True,
            bounds=[[min_lat, min_lng], [max_lat, max_lng]],  # Set the bounds using the geometry's coordinates
            colormap=mosaic_palette,  # Apply the custom NDVI color palette
        ).add_to(Map)

        mosaic_palette.add_to(Map)

        # Add vegetation indices layers if selected
        if "NDVI" in indices:
            # Calculate NDVI using the formula on GEE
            ndvi = mosaic.normalizedDifference([bands_mapping["nir"], bands_mapping["red"]]).rename('NDVI')

            ndvi_params = ndvi.getThumbUrl({
                'min': -1.0,
                'max': 1.0,
                'region': study_area_geometry,  
                'dimensions': '800x600'
            })

            # Define a custom color map for NDVI
            ndvi_palette = LinearColormap(
                ['red', 'yellow', 'green'],  # Custom color palette for NDVI
                vmin=-1.0, vmax=1.0  # NDVI values typically range from -1 to 1
            ).to_step(n=9)  # Step allows you to adjust the number of colors in the palette

            # Add the NDVI as a layer
            folium.raster_layers.ImageOverlay(
                image=ndvi_params,
                attr='Google Earth Engine',
                name="{} - {} - NDVI".format(year, satellite),
                overlay=True,
                control=True,
                bounds=[[min_lat, min_lng], [max_lat, max_lng]],  # Set the bounds using the geometry's coordinates
                colormap=ndvi_palette,  # Apply the custom NDVI color palette
            ).add_to(Map)

            ndvi_palette.add_to(Map)

        if "SAVI" in indices:
            # SAVI adjustment factor
            L = 0.5

            # Calculate SAVI using the formula on GEE
            savi = (mosaic.select(bands_mapping["nir"]).subtract(mosaic.select(bands_mapping["red"]))
                    .multiply(1 + L)
                    .divide(mosaic.select(bands_mapping["nir"]).add(mosaic.select(bands_mapping["red"])).add(L))
                    .rename('SAVI'))
            
            # Define visualization parameters for SAVI
            savi_params = savi.getThumbUrl({
                'min': -1.0,
                'max': 1.0,
                'region': study_area_geometry,  
                'dimensions': '800x600'
            })

            savi_palette = LinearColormap(
                ['purple', 'yellow', 'green'], 
                vmin=-1.0, vmax=1.0
            ).to_step(n=9)

            # Add SAVI as a layer
            folium.raster_layers.ImageOverlay(
                image=savi_params,
                attr='Google Earth Engine',
                name="{} - {} - SAVI".format(year, satellite),
                overlay=True,
                control=True,
                bounds=[[min_lat, min_lng], [max_lat, max_lng]],
                colormap=savi_palette,
            ).add_to(Map)

            savi_palette.add_to(Map)

        if "EVI" in indices:
            # EVI coefficients and parameters
            L = 10000  # Soil adjustment factor
            C1 = 6     # Coefficient for red band
            C2 = 7.5   # Coefficient for blue band
            G = 2.5    # Gain factor

            # Calculate EVI using an GEE expression
            evi = mosaic.expression(
                'G * ((nir_band - red_band) / (nir_band + C1 * red_band - C2 * blue_band + L))',
                {
                    'G': G,
                    'nir_band': mosaic.select(bands_mapping["nir_band"]),
                    'red_band': mosaic.select(bands_mapping["red_band"]),
                    'blue_band': mosaic.select(bands_mapping["blue_band"]),
                    'C1': C1,
                    'C2': C2,
                    'L': L
                }
            ).rename('EVI')
            
            # Define visualization parameters for EVI
            evi_params = evi.getThumbUrl({
                'min': -0.1,
                'max': 2.5,
                'region': study_area_geometry,  
                'dimensions': '800x600'
            })

            evi_palette = LinearColormap(
                ['blue', 'white', 'green'], 
                vmin=-0.1, vmax=2.5
            ).to_step(n=9)

            # Add EVI as a layer
            folium.raster_layers.ImageOverlay(
                image=evi_params,
                attr='Google Earth Engine',
                name="{} - {} - EVI".format(year, satellite),
                overlay=True,
                control=True,
                bounds=[[min_lat, min_lng], [max_lat, max_lng]],
                colormap=evi_palette,
            ).add_to(Map)

            evi_palette.add_to(Map)

        if "OMI" in indices:
            # Calculate OMI using the formula on GEE
            omi = mosaic.select(bands_mapping["nir_band"]).divide(mosaic.select(bands_mapping["red_band"])).rename('OMI')
            
            omi_params = omi.getThumbUrl({
                'min': 0,
                'max': 3,
                'region': study_area_geometry,  
                'dimensions': '800x600'
            })

            omi_palette = LinearColormap(
                ['blue', 'green', 'yellow', 'red'], 
                vmin=0, vmax=3
            ).to_step(n=9)

            # Add SAVI as a layer
            folium.raster_layers.ImageOverlay(
                image=omi_params,
                attr='Google Earth Engine',
                name="{} - {} - OMI".format(year, satellite),
                overlay=True,
                control=True,
                bounds=[[min_lat, min_lng], [max_lat, max_lng]],
                colormap=omi_palette,
            ).add_to(Map)

            omi_palette.add_to(Map)

        if "SI" in indices:
            # Calculate SI using the formula on GEE
            si = (mosaic.select(bands_mapping["nir_band"]).subtract(mosaic.select(bands_mapping["red_band"]))
                .divide(mosaic.select(bands_mapping["nir_band"]).add(mosaic.select(bands_mapping["red_band"])))
                .rename('SI'))
            
            si_params = si.getThumbUrl({
                'min': -1.0,
                'max': 1.0,
                'region': study_area_geometry,  
                'dimensions': '800x600'
            })

            si_palette = LinearColormap(
                ['blue', 'white', 'green'], 
                vmin=-1.0, vmax=1.0
            ).to_step(n=9)

            # Add SAVI as a layer
            folium.raster_layers.ImageOverlay(
                image=si_params,
                attr='Google Earth Engine',
                name="{} - {} - SI".format(year, satellite),
                overlay=True,
                control=True,
                bounds=[[min_lat, min_lng], [max_lat, max_lng]],
                colormap=si_palette,
            ).add_to(Map)

            si_palette.add_to(Map)

    # Add layer control
    folium.LayerControl().add_to(Map)

    # Return the HTML representation of the map
    return Map._repr_html_()  # Use folium's method to get HTML