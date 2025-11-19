# Processes Endpoint Documentation
This document describes the creation and usage of the `/processes` endpoint in the API, along with Python process demonstrations.

## Getting Started

### Running the Services

- **Full container stack**: `docker compose up --build`
- **Processes endpoint only** (under pygeoapi): `docker compose up pygeoapi --build`

Once running, processes are available at: http://localhost:5000/processes?f=html

### Configuration

The pygeoapi configuration file `/config/pygeoapi-config.yaml` dynamically generates the `/openapi/openapi.yaml` file, creating the OpenAPI documentation available at: http://localhost:5000/openapi#/

## Available Processes

### Process #1: hello-world-pygeoapi

A basic "Hello World" process from the pygeoapi GitHub repository.

**Source**: https://github.com/geopython/pygeoapi/blob/master/pygeoapi/process/hello_world.py

#### Usage Example

```bash
curl -X POST http://localhost:5000/processes/hello-world-pygeoapi/execution \
  -H "Content-Type: application/json" \
  -d '{
    "inputs": {
      "name": {
        "value": "Jérémie"
      }
    }
  }'
```

Response
```json
{
  "id": "echo",
  "value": "Hello Jérémie!"
}
```

### Process #2: mycool-process
A process that takes a CSV file and calculates the square root of the "value" field.

Demo file: /processes/demo/obs.csv
Process implementation: /processes/demo/mycool_process.py

Usage Example
```bash
curl -X POST http://localhost:5000/processes/mycool-process/execution \
  -H "Content-Type: application/json" \
  -d '{}'
```

Response
```json
{
  "id": "sqrt_values",
  "value": [
    {
      "id": 1,
      "value": 25,
      "sqrt": 5.0
    },
    {
      "id": 2,
      "value": 100,
      "sqrt": 10.0
    }
  ]
}
```

## Development Notes
- Processes are configured through the pygeoapi configuration file
- Each process must implement the required pygeoapi process interface
- The OpenAPI specification is automatically generated from the configuration
