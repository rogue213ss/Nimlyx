import unittest
from flask import Flask, session
from routes.rig import rig_bp
from routes.game import game_bp
import json

class TestRigPersistence(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.secret_key = "test-secret"
        self.app.register_blueprint(rig_bp)
        self.app.register_blueprint(game_bp)
        self.client = self.app.test_client()

    def test_get_empty_rig(self):
        res = self.client.get("/api/rig")
        self.assertEqual(res.status_code, 404)
        self.assertEqual(res.get_json()["status"], "not_configured")

    def test_create_and_retrieve_rig(self):
        # Create
        rig_data = {
            "cpu_external_id": "cpu-intel-i5-2500k",
            "gpu_external_id": "nvidia-geforce-rtx-4090",
            "ram_gb": 16
        }
        res = self.client.put("/api/rig", json=rig_data)
        self.assertEqual(res.status_code, 200)
        
        # Retrieve
        res2 = self.client.get("/api/rig")
        self.assertEqual(res2.status_code, 200)
        self.assertEqual(res2.get_json()["cpu_external_id"], "cpu-intel-i5-2500k")

    def test_update_rig(self):
        self.client.put("/api/rig", json={"cpu_external_id": "cpu1", "ram_gb": 8})
        res = self.client.put("/api/rig", json={"cpu_external_id": "cpu2", "ram_gb": 16})
        self.assertEqual(res.get_json()["rig"]["cpu_external_id"], "cpu2")
        self.assertEqual(res.get_json()["rig"]["ram_gb"], 16)

    def test_clear_rig(self):
        self.client.put("/api/rig", json={"cpu_external_id": "cpu1", "ram_gb": 8})
        self.client.delete("/api/rig")
        res = self.client.get("/api/rig")
        self.assertEqual(res.status_code, 404)

    def test_malformed_rig_input(self):
        res = self.client.put("/api/rig", json={
            "cpu_external_id": [],
            "gpu_external_id": {},
            "ram_gb": "potato"
        })
        self.assertEqual(res.status_code, 200)
        data = res.get_json()["rig"]
        self.assertIsNone(data["cpu_external_id"])
        self.assertIsNone(data["gpu_external_id"])
        self.assertIsNone(data["ram_gb"])

    def test_missing_hardware(self):
        res = self.client.put("/api/rig", json={
            "cpu_external_id": "valid-cpu"
        })
        data = res.get_json()["rig"]
        self.assertEqual(data["cpu_external_id"], "valid-cpu")
        self.assertIsNone(data["gpu_external_id"])
        self.assertIsNone(data["ram_gb"])
