import pytest
import os
from pathlib import Path
from services.hardware.engine.storage.requirements_db import RequirementsDB, requirements_db
from services.hardware.engine.compatibility.query_engine import QueryEngine
from app import app

@pytest.fixture
def client():
    app.config['TESTING'] = True
    with app.test_client() as client:
        yield client

def test_path_resolution():
    # Verify that the DB path does not contain 'berli' or hardcoded windows strings in its source instantiation
    # (Although it will when resolved on this machine, we check the default is None)
    
    # Actually, we can check the path relative to the module
    import services.hardware.engine.storage.requirements_db as db_mod
    import services.hardware.engine.compatibility.query_engine as qe_mod
    
    db_file = Path(db_mod.__file__).resolve()
    qe_file = Path(qe_mod.__file__).resolve()
    
    db = RequirementsDB()
    qe = QueryEngine()
    
    assert db.db_path.is_absolute(), "Path should resolve to absolute based on __file__"
    assert "backend" in db.db_path.parts
    assert "data" in db.db_path.parts
    assert db.db_path.name == "requirements.db"
    
    # Works from alternate working directory? We are already in pytest, so it is dynamic
    assert qe.db is not None

def test_ram_vram_semantics(client):
    os.environ['REQUIREMENTS_ENGINE_ENABLED'] = 'True'
    
    # Known RAM
    resp = client.post("/api/game/730/compatibility", json={
        "cpu_external_id": "cpu-intelcorei913900k",
        "gpu_external_id": "nvidia-geforce-rtx-4090",
        "ram_gb": 32.0
    })
    data = resp.get_json()
    assert data["verdict"] == "unknown"  # Generic GPU without VRAM leads to unknown
    ram_comp = next(c for c in data["components"] if c["component"] == "ram")
    assert ram_comp["meets_minimum"] is True
    
    # Missing RAM
    resp = client.post("/api/game/730/compatibility", json={
        "cpu_external_id": "cpu-intelcorei913900k",
        "gpu_external_id": "nvidia-geforce-rtx-4090"
        # ram_gb omitted
    })
    data = resp.get_json()
    ram_comp = next(c for c in data["components"] if c["component"] == "ram")
    assert ram_comp["meets_minimum"] is None, "Missing RAM must be unknown"

    # RAM = null
    resp = client.post("/api/game/730/compatibility", json={
        "cpu_external_id": "cpu-intelcorei913900k",
        "gpu_external_id": "nvidia-geforce-rtx-4090",
        "ram_gb": None
    })
    data = resp.get_json()
    ram_comp = next(c for c in data["components"] if c["component"] == "ram")
    assert ram_comp["meets_minimum"] is None, "Null RAM must be unknown"

    # RAM = invalid string
    resp = client.post("/api/game/730/compatibility", json={
        "cpu_external_id": "cpu-intelcorei913900k",
        "gpu_external_id": "nvidia-geforce-rtx-4090",
        "ram_gb": "hello"
    })
    data = resp.get_json()
    ram_comp = next(c for c in data["components"] if c["component"] == "ram")
    assert ram_comp["meets_minimum"] is None, "Invalid string RAM must be unknown"

def test_input_validation(client):
    os.environ['REQUIREMENTS_ENGINE_ENABLED'] = 'True'
    
    # Missing fields
    resp = client.post("/api/game/730/compatibility", json={"cpu_external_id": 123})
    assert resp.status_code == 200
    
    # Malformed array
    resp = client.post("/api/game/730/compatibility", json={"gpu_external_id": ["x"]})
    assert resp.status_code == 200
    assert resp.get_json()["verdict"] in ["not_recommended", "unknown"]
    
    # Malformed dict
    resp = client.post("/api/game/730/compatibility", json={"ram_gb": {}})
    assert resp.status_code == 200
    
    # Boolean
    resp = client.post("/api/game/730/compatibility", json={"ram_gb": True})
    assert resp.status_code == 200
    
    # Empty payload
    resp = client.post("/api/game/730/compatibility", json={})
    assert resp.status_code == 200

def test_appid_validation(client):
    cases = [
        730,
        "730",
        "steam_730",
        -999,
        0,
        "invalid_string",
        "123' OR '1'='1"
    ]
    for appid in cases:
        resp = client.post(f"/api/game/{appid}/compatibility", json={})
        assert resp.status_code == 200, f"Failed on AppID {appid}"
