## Pipeline Command-Line Arguments

| Argument | Description |
|----------|-------------|
| `-h, --help` | show this help message and exit |
| `--input` | Path to the input source for data ingestion. |
| `--crs` | Global CRS to reproject all data to (EPSG code). |
| `--collection` | Collection ID to associate with the ingested data. |



## `--help` Output

```bash
usage: generate_args_md.py [-h] [--input INPUT] [--crs CRS] [--collection COLLECTION_ID]

Run the geoprocessing pipeline.

options:
  -h, --help            show this help message and exit
  --input INPUT         Path to the input source for data ingestion.
  --crs CRS             Global CRS to reproject all data to (EPSG code).
  --collection COLLECTION_ID           Collection ID to associate with the ingested data.
```
