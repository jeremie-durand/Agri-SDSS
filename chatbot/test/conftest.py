import os

os.environ["STAC_API_URL"] = "http://stac-api:8080"
os.environ["RASTER_API_INTERNAL_URL"] = "http://raster-api:8080"
os.environ["VECTOR_API_INTERNAL_URL"] = "http://vector-api:8080"
os.environ["VECTOR_API_URL"] = os.environ["VECTOR_API_INTERNAL_URL"]  # upstream alias
os.environ["PYGEOAPI_INTERNAL_URL"] = "http://process-api:5000"
os.environ["LLM_API_KEY"] = os.environ.get("LLM_API_KEY") or "test-fake-key"
os.environ["LLM_PROVIDER"] = os.environ.get("LLM_PROVIDER") or "openai"
os.environ["LLM_MODEL"] = os.environ.get("LLM_MODEL") or "gpt-4o"
os.environ["ENABLE_AUTH"] = "false"
os.environ.setdefault("API_KEY", "test-api-key")
