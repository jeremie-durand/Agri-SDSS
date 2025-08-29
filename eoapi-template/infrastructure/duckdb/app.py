# infrastructure/duckdb/app.py
from demo.config import Config
from demo.duckdb_utils import DuckDBManager
from flask import Flask, jsonify

# Initialize Flask app
app = Flask(__name__)

# Create a persistent DuckDBManager instance for the entire application
duckdb_manager = DuckDBManager()
duckdb_manager.init_extensions()  # Initialize DuckDB extensions at startup


@app.route("/")
def home():
    return "DuckDB is ready!"


@app.route("/fetch-postgis", methods=["POST"])
def fetch_data_route():
    """Fetch data from PostGIS and save them as Parquet files in DuckDB."""
    try:
        duckdb_manager.fetch_postgis(tables=Config.VECTOR_TABLES)
        return (
            jsonify(
                {"status": "success", "message": "Data fetched and saved to parquet"}
            ),
            200,
        )
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/check-data", methods=["GET"])
def check_data_route():
    """Check all data in DuckDB."""
    try:
        result = duckdb_manager.check_data()
        return jsonify({"status": "success", "result": result}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/generate-centroids", methods=["POST"])
def generate_centroids_route():
    """Generate centroids for all vector data in DuckDB."""
    try:
        result = duckdb_manager.get_centroids(tables=Config.VECTOR_TABLES)

        return (
            jsonify(
                {
                    "status": "success",
                    "message": "Centroids computed and saved",
                    "result": result,
                }
            ),
            200,
        )
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8084)
