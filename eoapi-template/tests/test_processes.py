# tests/test_processes.py
import pytest
import requests

from demo.config import Config

# ------------------------------------------
# List of processes to test
# ------------------------------------------
processes = [
    {
        "id": "hello-world-pygeoapi",
        "valid_input": {"name": {"value": "Jérémie"}},
        "invalid_input": None,  # Pas d’entrée invalide pour ce processus
    },
    {
        "id": "mycool-process",
        "valid_input": {},  # Pas d'entrée nécessaire
        "invalid_input": None,  # Pas d’entrée invalide pour ce processus
    },
]


# ------------------------------------------
# Test cases for processes API
# ------------------------------------------
def test_api_processes_returns_200():
    """
    Test if the processes endpoint returns a 200 status code.
    """
    response = requests.get(f"{Config.PYGEOAPI_API_URL}/processes")
    assert response.status_code == 200


def test_api_processes_has_processes_or_title():
    """
    Test if the processes endpoint returns a valid response with processes or title.
    """
    response = requests.get(f"{Config.PYGEOAPI_API_URL}/processes")
    json = response.json()
    assert "processes" in json or "title" in json


# ------------------------------------------
# Test cases for specific processes
# ------------------------------------------
@pytest.mark.parametrize("process", processes)
def test_process_description_has_id(process):
    """
    Test if the process description has an ID.
    """
    assert process.get("id") is not None, "Process ID must be defined"


@pytest.mark.parametrize("process", processes)
def test_get_process_description_returns_200(process):
    """
    Test if the process description endpoint returns a 200 status code.
    """
    response = requests.get(f"{Config.PYGEOAPI_API_URL}/processes/{process['id']}")
    assert response.status_code == 200


@pytest.mark.parametrize("process", processes)
def test_get_process_description_has_id_in_response(process):
    """
    Test if the process description response contains the process ID.
    """
    response = requests.get(f"{Config.PYGEOAPI_API_URL}/processes/{process['id']}")
    assert "id" in response.json()


@pytest.mark.parametrize("process", processes)
def test_post_process_execution_valid_status(process):
    """
    Test if the process execution endpoint returns a valid status code.
    """
    if process["valid_input"] is not None:
        payload = {"inputs": process["valid_input"]}
    else:
        payload = {}

    response = requests.post(
        f"{Config.PYGEOAPI_API_URL}/processes/{process['id']}/execution", json=payload
    )
    assert response.status_code in [200, 201]


@pytest.mark.parametrize("process", processes)
def test_post_process_execution_valid_response(process):
    """
    Test if the process execution endpoint returns a valid response.
    """
    if process["valid_input"] is not None:
        payload = {"inputs": process["valid_input"]}
    else:
        payload = {}

    response = requests.post(
        f"{Config.PYGEOAPI_API_URL}/processes/{process['id']}/execution", json=payload
    )
    json = response.json()
    assert "outputs" in json or "value" in json or "jobID" in json


@pytest.mark.parametrize(
    "process", [p for p in processes if p["invalid_input"] is not None]
)
def test_post_process_execution_invalid_status(process):
    """
    Test if the process execution endpoint returns a 400 status code for invalid input.
    """
    response = requests.post(
        f"{Config.PYGEOAPI_API_URL}/processes/{process['id']}/execution",
        json={"inputs": process["invalid_input"]},
    )
    assert response.status_code == 400


@pytest.mark.parametrize(
    "process", [p for p in processes if p["invalid_input"] is not None]
)
def test_post_process_execution_invalid_response(process):
    """
    Test if the process execution endpoint returns an error message for invalid input.
    """
    response = requests.post(
        f"{Config.PYGEOAPI_API_URL}/processes/{process['id']}/execution",
        json={"inputs": process["invalid_input"]},
    )
    json = response.json()
    assert "error" in json or "message" in json
