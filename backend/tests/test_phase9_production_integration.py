import pytest
from unittest.mock import patch
import json
import os

from app import app
from services.hardware.engine.nimlyx_adapter import NimlyxAdapter

@pytest.fixture
def client():
    app.config['TESTING'] = True
    os.environ['REQUIREMENTS_ENGINE_ENABLED'] = 'True'
    with app.test_client() as client:
        yield client

def test_single_game_endpoint_works(client):
    # AppID 730 mapping internally to steam_730
    payload = {
        "cpu_external_id": "cpu-intelcorei58350u",
        "gpu_external_id": "nvidia-geforce-rtx-2060",
        "ram_gb": 16.0
    }
    response = client.post("/api/game/730/compatibility", json=payload)
    assert response.status_code == 200
    data = response.get_json()
    assert "verdict" in data
    assert "components" in data
    assert len(data["components"]) == 3

def test_missing_vram_fails_safely():
    adapter = NimlyxAdapter()
    res = adapter.evaluate_production_endpoint(730, "cpu-intelcorei58350u", "nvidia-geforce-rtx-4090", 16.0)
    # VRAM is inherently passed as 0.0, so if the game requires VRAM, it might fail.
    # We just ensure it doesn't crash and returns valid shape
    assert "verdict" in res

def test_unknown_game():
    adapter = NimlyxAdapter()
    res = adapter.evaluate_production_endpoint(999999999, "cpu", "gpu", 8.0)
    assert res["verdict"] == "unknown"

def test_malformed_numeric():
    adapter = NimlyxAdapter()
    res = adapter.evaluate_production_endpoint(730, "cpu", "gpu", "invalid_ram")
    assert res["verdict"] == "unknown" or res["verdict"] == "not_recommended"
    # Actually if ram is malformed, _safe_float returns None, falling back to 0.0 in adapter or query engine.
    
def test_zero_network(client):
    with patch('socket.socket') as mock_socket:
        mock_socket.side_effect = Exception("NETWORK BLOCKED")
        payload = {
            "cpu_external_id": "cpu-intelcorei58350u",
            "gpu_external_id": "nvidia-geforce-rtx-2060",
            "ram_gb": 16.0
        }
        response = client.post("/api/game/730/compatibility", json=payload)
        assert response.status_code == 200 # Should not raise Network blocked!

