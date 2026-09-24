import pytest
import socket
import urllib.request
import requests
import os
from app import app
from services.hardware.engine.storage.requirements_db import requirements_db

def block_network():
    def throw(*args, **kwargs):
        raise RuntimeError("NETWORK ATTEMPTED!")
    socket.socket = throw
    socket.create_connection = throw
    urllib.request.urlopen = throw
    requests.Session.request = throw

def test_offline_engine():
    block_network()
    app.config['TESTING'] = True
    os.environ['REQUIREMENTS_ENGINE_ENABLED'] = 'True'
    with app.test_client() as client:
        resp = client.post("/api/game/730/compatibility", json={
            "cpu_external_id": "cpu-intelcorei913900k",
            "gpu_external_id": "nvidia-geforce-rtx-4090",
            "ram_gb": 32.0
        })
        assert resp.status_code == 200
        print(resp.get_json())
        print("PASS")

if __name__ == '__main__':
    test_offline_engine()
