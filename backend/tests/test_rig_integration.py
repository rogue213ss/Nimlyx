import unittest
from unittest.mock import patch, MagicMock
from flask import Flask, session
from routes.rig import rig_bp
from routes.game import game_bp
import os
import sys

# Mock the engine so the local import in game.py doesn't crash if rapidfuzz is missing
mock_engine = MagicMock()
mock_adapter_class = MagicMock()
mock_engine.NimlyxAdapter = mock_adapter_class
sys.modules['services.hardware.engine.nimlyx_adapter'] = mock_engine

class TestRigIntegration(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.secret_key = "test-secret"
        self.app.register_blueprint(rig_bp)
        self.app.register_blueprint(game_bp)
        self.client = self.app.test_client()
        os.environ["REQUIREMENTS_ENGINE_ENABLED"] = "true"

    @patch('routes.game.get_appdetails')
    def test_automatic_game_evaluation_with_rig(self, mock_appdetails):
        mock_eval = mock_adapter_class.return_value.evaluate_production_endpoint
        mock_eval.return_value = {
            "verdict": "pass",
            "components": [],
            "notes": []
        }
        
        # 1. Set the rig
        self.client.put("/api/rig", json={
            "cpu_external_id": "cpu-test",
            "gpu_external_id": "gpu-test",
            "ram_gb": 16
        })
        
        # 2. Check compatibility without providing hardware in payload
        res = self.client.post("/api/game/123/compatibility", json={})
        self.assertEqual(res.status_code, 200)
        
        # 3. Verify that NimlyxAdapter was called with the Rig data
        mock_eval.assert_called_with("123", "cpu-test", "gpu-test", 16)
        
        # 4. Verify Steam network was completely blocked/not called
        mock_appdetails.assert_not_called()

    def test_manual_override_with_rig_saved(self):
        mock_eval = mock_adapter_class.return_value.evaluate_production_endpoint
        mock_eval.return_value = {"verdict": "pass", "components": []}
        
        # Set rig
        self.client.put("/api/rig", json={
            "cpu_external_id": "cpu-test",
            "gpu_external_id": "gpu-test",
            "ram_gb": 16
        })
        
        # Override with manual payload
        res = self.client.post("/api/game/123/compatibility", json={
            "cpu_external_id": "cpu-override",
            "gpu_external_id": "gpu-override",
            "ram_gb": 32
        })
        self.assertEqual(res.status_code, 200)
        
        # The override should take precedence
        mock_eval.assert_called_with("123", "cpu-override", "gpu-override", 32)
        
        # But Rig should remain unchanged
        rig_res = self.client.get("/api/rig")
        self.assertEqual(rig_res.get_json()["cpu_external_id"], "cpu-test")
