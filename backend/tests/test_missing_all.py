import os
import pytest
from app import app

def test_missing_all_hardware():
    app.config['TESTING'] = True
    os.environ['REQUIREMENTS_ENGINE_ENABLED'] = 'True'
    with app.test_client() as client:
        resp = client.post("/api/game/1091500/compatibility", json={})
        print(resp.get_json())
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['verdict'] == 'unknown'
        for comp in data['components']:
            assert comp['meets_minimum'] is None

if __name__ == '__main__':
    test_missing_all_hardware()
