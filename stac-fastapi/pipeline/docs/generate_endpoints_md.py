from pathlib import Path

from pipeline.config import Config

# Map service names
SERVICES = {
    "STAC API": "STAC_API_PORT",
    "Raster API": "RASTER_API_PORT",
    "Vector API": "VECTOR_API_PORT",
    "Process API": "PYGEOAPI_API_PORT",
    "Frontend": "FRONTEND_PORT",
}

# Map examples of endpoints
EXAMPLES = {
    "STAC API": "/collections/<MY_COLLECTION>/items",
    "Raster API": "/cog/tiles/{{z}}/{{x}}/{{y}}.png?url=<COG_URL>",
    "Vector API": "/collections/public.<VECTOR_TABLE>/items",
    "Process API": "/processes/<PROCESS_NAME>",
    "Frontend": "/collections/<MY_COLLECTION>/items",
}

md_path = Path(__file__).parent / "ENDPOINTS.md"

with md_path.open("w") as f:
    f.write("## Endpoints\n\n")
    f.write("| Service | URL |\n")
    f.write("|--------|-----|\n")
    for service, port_var in SERVICES.items():
        port = getattr(Config, port_var)
        url = f"http://localhost:{port}{EXAMPLES.get(service, '')}"
        f.write(f"| **{service}** | {url} |\n")

print(f"ENDPOINTS.md generated at {md_path.resolve()}")
