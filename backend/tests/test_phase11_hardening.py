import pytest
import os
from app import app

@pytest.fixture
def client():
    app.config['TESTING'] = True
    os.environ['REQUIREMENTS_ENGINE_ENABLED'] = 'True'
    with app.test_client() as client:
        yield client

def test_missing_all_hardware(client):
    resp = client.post("/api/game/1091500/compatibility", json={})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data['verdict'] == 'unknown'
    for comp in data['components']:
        assert comp['meets_minimum'] is None
        assert comp['meets_recommended'] is None

def test_missing_cpu(client):
    resp = client.post("/api/game/1091500/compatibility", json={
        "gpu_external_id": "nvidia-geforce-rtx-4090",
        "ram_gb": 32.0
    })
    assert resp.status_code == 200
    data = resp.get_json()
    cpu_comp = next(c for c in data['components'] if c['component'] == 'cpu')
    assert cpu_comp['meets_minimum'] is None

def test_missing_gpu(client):
    resp = client.post("/api/game/1091500/compatibility", json={
        "cpu_external_id": "cpu-intelcorei913900k",
        "ram_gb": 32.0
    })
    assert resp.status_code == 200
    data = resp.get_json()
    gpu_comp = next(c for c in data['components'] if c['component'] == 'gpu')
    assert gpu_comp['meets_minimum'] is None

def test_malformed_cpu_gpu_ram(client):
    resp = client.post("/api/game/1091500/compatibility", json={
        "cpu_external_id": ["list"],
        "gpu_external_id": {"dict": True},
        "ram_gb": "not_a_number"
    })
    assert resp.status_code == 200
    data = resp.get_json()
    assert data['verdict'] == 'unknown'
