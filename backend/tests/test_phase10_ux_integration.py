import pytest
import os
import sqlite3
from unittest.mock import patch
from app import app

@pytest.fixture
def client():
    app.config['TESTING'] = True
    os.environ['REQUIREMENTS_ENGINE_ENABLED'] = 'True'
    with app.test_client() as client:
        yield client

def test_compat_endpoint_success(client):
    resp = client.post("/api/game/730/compatibility", json={
        "cpu_external_id": "cpu-intelcorei913900k",
        "gpu_external_id": "nvidia-geforce-rtx-4090",
        "ram_gb": 32.0
    })
    assert resp.status_code == 200
    data = resp.get_json()
    assert "verdict" in data
    assert "components" in data
    assert "notes" in data
    
def test_compat_unknown_state_and_missing_ram(client):
    resp = client.post("/api/game/730/compatibility", json={
        "cpu_external_id": "cpu-intelcorei913900k",
        "gpu_external_id": "nvidia-geforce-rtx-4090"
    })
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["verdict"] == "unknown"
    ram_comp = next(c for c in data["components"] if c["component"] == "ram")
    assert ram_comp["meets_minimum"] is None

def test_compat_malformed_hardware(client):
    resp = client.post("/api/game/730/compatibility", json={
        "cpu_external_id": {"bad": "type"},
        "gpu_external_id": ["x"],
        "ram_gb": "hello"
    })
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["verdict"] == "unknown"

@patch('backend.steam.get_appdetails')
def test_zero_steam_calls(mock_get_appdetails, client):
    mock_get_appdetails.side_effect = RuntimeError("STEAM_CALLED")
    resp = client.post("/api/game/730/compatibility", json={
        "cpu_external_id": "cpu-intelcorei913900k",
        "gpu_external_id": "nvidia-geforce-rtx-4090",
        "ram_gb": 32.0
    })
    assert resp.status_code == 200
    assert mock_get_appdetails.call_count == 0
