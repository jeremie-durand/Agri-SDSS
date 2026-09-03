import os
import sys
import traceback

import yaml
from pygeoapi.openapi import get_oas

try:
    sys.path.insert(0, "/app")

    # Load configuration manually
    with open(os.environ["PYGEOAPI_CONFIG"], "r") as f:
        config = yaml.safe_load(f)

    # Generate OpenAPI specification
    oas = get_oas(config)
    with open(os.environ["PYGEOAPI_OPENAPI"], "w") as f:
        yaml.dump(oas, f, default_flow_style=False, sort_keys=False)

    print("OpenAPI document generated successfully")
    print(f"File size: {os.path.getsize(os.environ['PYGEOAPI_OPENAPI'])} bytes")

except Exception as e:
    print(f"Error generating OpenAPI: {e}")
    traceback.print_exc()
    sys.exit(1)
