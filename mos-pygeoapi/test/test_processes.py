import time

import pytest
import requests
import responses

# ------------------------------------------
# List of processes to test
# ------------------------------------------
processes = [
    {
        "id": "hello-world-pygeoapi",
        "valid_input": {"name": {"value": "Jérémie"}},
        "invalid_input": None,  # No invalid input for this process
    },
    {
        "id": "mycool-process",
        "valid_input": {},  # No input required
        "invalid_input": None,  # No invalid input for this process
    },
]


# ------------------------------------------
# Fixtures
# ------------------------------------------
@pytest.fixture
def processes_test_data():
    """Test data for processes."""
    return [
        {
            "id": "hello-world-pygeoapi",
            "valid_input": {"name": {"value": "Jérémie"}},
            "invalid_input": {"name": {"value": 123}},  # Wrong type
            "empty_input": {},
            "supports_async": True,
            "expected_output_keys": ["greeting"],
        },
        {
            "id": "mycool-process",
            "valid_input": {},
            "invalid_input": {"unknown_param": {"value": "test"}},
            "empty_input": {},
            "supports_async": False,
            "expected_output_keys": ["result"],
        },
        {
            "id": "buffer-process",
            "valid_input": {
                "geometry": {"value": {"type": "Point", "coordinates": [0, 0]}},
                "distance": {"value": 100},
            },
            "invalid_input": {"geometry": {"value": "invalid_geometry"}},
            "empty_input": {},
            "supports_async": True,
            "expected_output_keys": ["buffered_geometry"],
        },
    ]


@pytest.fixture
def sample_processes_response(pygeoapi_api_url_fixture):
    """Complete processes list response."""
    base = pygeoapi_api_url_fixture
    return {
        "processes": [
            {
                "id": "hello-world-pygeoapi",
                "title": "Hello World Process",
                "description": "Simple greeting process",
                "version": "1.0.0",
                "jobControlOptions": ["sync-execute", "async-execute"],
                "outputTransmission": ["value", "reference"],
            },
            {
                "id": "mycool-process",
                "title": "My Cool Process",
                "description": "Demonstration process",
                "version": "1.0.0",
                "jobControlOptions": ["sync-execute"],
                "outputTransmission": ["value"],
            },
        ],
        "links": [
            {
                "href": f"{base}/processes",
                "rel": "self",
                "type": "application/json",
            }
        ],
    }


@pytest.fixture
def sample_process_detail():
    """Detailed process description."""
    return {
        "id": "hello-world-pygeoapi",
        "title": "Hello World Process",
        "description": "Returns personalized greeting message",
        "version": "1.0.0",
        "jobControlOptions": ["sync-execute", "async-execute"],
        "outputTransmission": ["value", "reference"],
        "inputs": {
            "name": {
                "title": "Name",
                "description": "Your name for greeting",
                "schema": {"type": "string"},
                "minOccurs": 0,
                "maxOccurs": 1,
            }
        },
        "outputs": {
            "greeting": {
                "title": "Greeting Message",
                "description": "Personalized message",
                "schema": {"type": "string"},
            }
        },
    }


# ------------------------------------------
# API mocked tests
# ------------------------------------------
@pytest.mark.mocked
@responses.activate
def test_mocked_processes_list(pygeoapi_api_url_fixture, sample_processes_response):
    """Test processes list endpoint with mock."""
    responses.add(
        responses.GET,
        f"{pygeoapi_api_url_fixture}/processes",
        json=sample_processes_response,
        status=200,
    )

    response = requests.get(f"{pygeoapi_api_url_fixture}/processes")

    assert response.status_code == 200
    data = response.json()
    assert "processes" in data
    assert len(data["processes"]) >= 2

    # Verify process structure
    for process in data["processes"]:
        required_fields = ["id", "title", "description", "version"]
        for field in required_fields:
            assert field in process


@pytest.mark.mocked
@responses.activate
def test_mocked_process_description(pygeoapi_api_url_fixture, sample_process_detail):
    """Test individual process description."""
    process_id = "hello-world-pygeoapi"
    responses.add(
        responses.GET,
        f"{pygeoapi_api_url_fixture}/processes/{process_id}",
        json=sample_process_detail,
        status=200,
    )

    response = requests.get(f"{pygeoapi_api_url_fixture}/processes/{process_id}")

    assert response.status_code == 200
    data = response.json()
    assert data["id"] == process_id
    assert "inputs" in data
    assert "outputs" in data
    assert "jobControlOptions" in data


@pytest.mark.mocked
@responses.activate
def test_mocked_sync_execution(pygeoapi_api_url_fixture):
    """Test synchronous process execution."""
    process_id = "hello-world-pygeoapi"
    execution_response = {"outputs": {"greeting": {"value": "Hello, Jérémie!"}}}

    responses.add(
        responses.POST,
        f"{pygeoapi_api_url_fixture}/processes/{process_id}/execution",
        json=execution_response,
        status=200,
    )

    payload = {"inputs": {"name": {"value": "Jérémie"}}, "mode": "sync"}

    response = requests.post(
        f"{pygeoapi_api_url_fixture}/processes/{process_id}/execution", json=payload
    )

    assert response.status_code == 200
    data = response.json()
    assert "outputs" in data
    assert "greeting" in data["outputs"]


@pytest.mark.mocked
@responses.activate
def test_mocked_async_execution(pygeoapi_api_url_fixture):
    """Test asynchronous process execution."""
    process_id = "hello-world-pygeoapi"
    job_response = {
        "jobID": "job-abc123",
        "status": "accepted",
        "message": "Job accepted",
        "created": "2024-01-15T10:00:00Z",
    }

    responses.add(
        responses.POST,
        f"{pygeoapi_api_url_fixture}/processes/{process_id}/execution",
        json=job_response,
        status=201,
        headers={"Location": f"{pygeoapi_api_url_fixture}/jobs/job-abc123"},
    )

    payload = {"inputs": {"name": {"value": "Jérémie"}}, "mode": "async"}

    response = requests.post(
        f"{pygeoapi_api_url_fixture}/processes/{process_id}/execution",
        json=payload,
        headers={"Prefer": "respond-async"},
    )

    assert response.status_code == 201
    data = response.json()
    assert "jobID" in data
    assert data["status"] == "accepted"
    assert "Location" in response.headers


# ------------------------------------------
# Parameterized Tests
# ------------------------------------------
@pytest.mark.parametrize(
    "process_data",
    [
        {"id": "hello-world-pygeoapi", "valid_input": {"name": {"value": "Test"}}},
        {"id": "mycool-process", "valid_input": {}},
    ],
)
def test_process_data_structure(process_data):
    """Test process test data has required structure."""
    assert "id" in process_data
    assert "valid_input" in process_data
    assert isinstance(process_data["id"], str)
    assert len(process_data["id"]) > 0


# ------------------------------------------
# Error Handling Tests
# ------------------------------------------
@pytest.mark.mocked
@responses.activate
def test_mocked_nonexistent_process_404(pygeoapi_api_url_fixture):
    """Test 404 for non-existent process."""
    responses.add(
        responses.GET,
        f"{pygeoapi_api_url_fixture}/processes/nonexistent-process",
        json={"type": "NotFound", "title": "Process not found"},
        status=404,
    )

    response = requests.get(f"{pygeoapi_api_url_fixture}/processes/nonexistent-process")
    assert response.status_code == 404


@pytest.mark.mocked
@responses.activate
def test_mocked_invalid_execution_400(pygeoapi_api_url_fixture):
    """Test 400 for invalid process execution."""
    process_id = "hello-world-pygeoapi"
    responses.add(
        responses.POST,
        f"{pygeoapi_api_url_fixture}/processes/{process_id}/execution",
        json={
            "type": "InvalidParameterValue",
            "title": "Invalid input",
            "detail": "Input validation failed",
        },
        status=400,
    )

    payload = {"inputs": {"invalid_param": {"value": "test"}}}

    response = requests.post(
        f"{pygeoapi_api_url_fixture}/processes/{process_id}/execution", json=payload
    )

    assert response.status_code == 400
    data = response.json()
    assert "type" in data or "error" in data


@pytest.mark.mocked
@responses.activate
def test_mocked_server_error_500(pygeoapi_api_url_fixture):
    """Test 500 server error handling."""
    responses.add(
        responses.GET,
        f"{pygeoapi_api_url_fixture}/processes",
        json={"error": "Internal server error"},
        status=500,
    )

    response = requests.get(f"{pygeoapi_api_url_fixture}/processes")
    assert response.status_code == 500


# ------------------------------------------
# Job Management Tests
# ------------------------------------------
@pytest.mark.mocked
@responses.activate
def test_mocked_job_status_check(pygeoapi_api_url_fixture):
    """Test job status checking."""
    job_id = "job-abc123"
    job_status = {
        "jobID": job_id,
        "status": "running",
        "message": "Processing...",
        "progress": 50,
        "created": "2024-01-15T10:00:00Z",
    }

    responses.add(
        responses.GET,
        f"{pygeoapi_api_url_fixture}/jobs/{job_id}",
        json=job_status,
        status=200,
    )

    response = requests.get(f"{pygeoapi_api_url_fixture}/jobs/{job_id}")

    assert response.status_code == 200
    data = response.json()
    assert data["jobID"] == job_id
    assert data["status"] == "running"
    assert data["progress"] == 50


@pytest.mark.mocked
@responses.activate
def test_mocked_job_results(pygeoapi_api_url_fixture):
    """Test job results retrieval."""
    job_id = "job-abc123"
    job_results = {"outputs": {"greeting": {"value": "Hello, World!"}}}

    responses.add(
        responses.GET,
        f"{pygeoapi_api_url_fixture}/jobs/{job_id}/results",
        json=job_results,
        status=200,
    )

    response = requests.get(f"{pygeoapi_api_url_fixture}/jobs/{job_id}/results")

    assert response.status_code == 200
    data = response.json()
    assert "outputs" in data


# ------------------------------------------
# OGC API - Processes Compliance Tests
# ------------------------------------------
@pytest.mark.mocked
@responses.activate
def test_mocked_ogc_conformance(pygeoapi_api_url_fixture):
    """Test OGC API - Processes conformance."""
    conformance_response = {
        "conformsTo": [
            "http://www.opengis.net/spec/ogcapi-processes-1/1.0/conf/core",
            "http://www.opengis.net/spec/ogcapi-processes-1/1.0/conf/json",
        ]
    }

    responses.add(
        responses.GET,
        f"{pygeoapi_api_url_fixture}/conformance",
        json=conformance_response,
        status=200,
    )

    response = requests.get(f"{pygeoapi_api_url_fixture}/conformance")

    assert response.status_code == 200
    data = response.json()
    assert "conformsTo" in data
    assert len(data["conformsTo"]) > 0


@pytest.mark.mocked
@responses.activate
def test_mocked_content_negotiation(pygeoapi_api_url_fixture):
    """Test content negotiation support."""
    responses.add(
        responses.GET,
        f"{pygeoapi_api_url_fixture}/processes",
        json={"processes": []},
        status=200,
        headers={"Content-Type": "application/json"},
    )

    # Test JSON content type
    response = requests.get(
        f"{pygeoapi_api_url_fixture}/processes", headers={"Accept": "application/json"}
    )

    assert response.status_code == 200
    assert "application/json" in response.headers.get("Content-Type", "")


# ------------------------------------------
# Performance and Load Tests
# ------------------------------------------
@pytest.mark.mocked
@responses.activate
def test_mocked_response_time(pygeoapi_api_url_fixture):
    """Test API response time performance."""
    responses.add(
        responses.GET,
        f"{pygeoapi_api_url_fixture}/processes",
        json={"processes": []},
        status=200,
    )

    start_time = time.time()
    response = requests.get(f"{pygeoapi_api_url_fixture}/processes")
    response_time = time.time() - start_time

    assert response.status_code == 200
    assert response_time < 2.0  # Should respond within 2 seconds


@pytest.mark.mocked
@responses.activate
def test_mocked_multiple_concurrent_requests(pygeoapi_api_url_fixture):
    """Test handling multiple concurrent requests."""
    import queue
    import threading

    responses.add(
        responses.GET,
        f"{pygeoapi_api_url_fixture}/processes",
        json={"processes": []},
        status=200,
    )

    results = queue.Queue()

    def make_request():
        try:
            response = requests.get(f"{pygeoapi_api_url_fixture}/processes")
            results.put(response.status_code)
        except Exception as e:
            results.put(str(e))

    # Create multiple threads
    threads = []
    for _ in range(5):
        thread = threading.Thread(target=make_request)
        threads.append(thread)
        thread.start()

    # Wait for all threads
    for thread in threads:
        thread.join()

    # Check results
    status_codes = []
    while not results.empty():
        status_codes.append(results.get())

    assert len(status_codes) == 5
    assert all(code == 200 for code in status_codes)
