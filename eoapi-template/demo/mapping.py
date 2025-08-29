# demo/mapping.py
vector_stac_columns = {
    "gid": "INTEGER PRIMARY KEY",
    "geom": "geometry(Geometry, 4326)",
    "start_date": "TIMESTAMP",
    "end_date": "TIMESTAMP",
    "file_url": "TEXT",
    "metadata": "JSONB",
}

vector_columns_mapping = {
    "gid": "gid",
    "geom": "geom",
    "start_date": "start_date",
    "end_date": "end_date",
    "file_url": "file_url",
    "metadata": "metadata",
}

attribute_null_mapping = {
    "": None,
    "na": None,
    "Na": None,
    "NA": None,
    "n/a": None,
    "N/A": None,
    None: None,
}


# Mapping for other use cases ...
# WEB_SERVICE_MAPPING = {...}
# ANOTHER_MAPPING = {...}
