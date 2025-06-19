vector_stac_columns = {
    "gid": "INTEGER PRIMARY KEY", 
    "geom": "geometry(Geometry, 4326)",
    "start_date": "TIMESTAMP",
    "end_date": "TIMESTAMP",
    "file_url": "TEXT",
    "metadata": "JSONB"
}

vector_columns_mapping = {
    "id": "id",
    "geometry": "geometry", 
    "start_date": "start_date",
    "end_date": "end_date",
    "file_url": "file_url",
    "metadata": "metadata"
}

# Mapping pour d'autres usages...
# WEB_SERVICE_MAPPING = {...}
# ANOTHER_MAPPING = {...}