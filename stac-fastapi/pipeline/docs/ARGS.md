## Pipeline Command-Line Arguments

| Argument | Description |
|----------|-------------|
| `-h, --help` | show this help message and exit |
| `--input` | Path to the input source for data ingestion. |
| `--crs` | Global CRS to reproject all data to (EPSG code). |
| `--stac-collection-id` | STAC Collection ID to associate with the ingested data. |
| `--csv-items` | Flag indicating the input data includes csv data format. |


## `--help` Output

```bash
usage: generate_args_md.py [-h] [--input INPUT] [--crs CRS] [--stac-collection-id STAC_COLLECTION_ID] [--csv-items]

Run the geoprocessing pipeline.

options:
  -h, --help            show this help message and exit
  --input INPUT         Path to the input source for data ingestion.
  --crs CRS             Global CRS to reproject all data to (EPSG code).
  --stac-collection-id STAC_COLLECTION_ID
                        STAC Collection ID to associate with the ingested data.
  --csv-items        Flag indicating the input data includes csv data format.
```
