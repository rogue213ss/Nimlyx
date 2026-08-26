import os
import sys

backend_dir = r'C:\Users\berli\OneDrive\Desktop\Nimlyx\backend'
sys.path.insert(0, backend_dir)

import unittest
import time
import threading
from unittest.mock import patch, MagicMock

import steam
from steam import _safe_steam_get, SteamCircuitBreakerException

class TestSteamGlobalRateLimiter(unittest.TestCase):
    def setUp(self):
        # Reset globals before each test
        steam.STEAM_REQUESTS_PER_SECOND = 2.0
        steam.STEAM_MAX_CONCURRENCY = 2
        steam.STEAM_429_COOLDOWN = 1.0
        steam._last_request_time = 0.0
        steam._cooldown_until = 0.0
        
        # Fresh lock and semaphore
        steam._steam_global_lock = threading.Lock()
        steam._steam_concurrency_sem = threading.Semaphore(steam.STEAM_MAX_CONCURRENCY)
        
    @patch('steam._session.request')
    def test_rate_limiter_prevents_bursts(self, mock_request):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_request.return_value = mock_resp
        
        start_time = time.time()
        for _ in range(3):
            _safe_steam_get("http://test")
            
        elapsed = time.time() - start_time
        # Tolerances
        self.assertGreaterEqual(elapsed, 0.9)
        self.assertEqual(mock_request.call_count, 3)
        
    @patch('steam._session.request')
    def test_429_triggers_global_cooldown(self, mock_request):
        mock_resp = MagicMock()
        mock_resp.status_code = 429
        mock_request.return_value = mock_resp
        
        # First request triggers 429
        with self.assertRaises(SteamCircuitBreakerException):
            _safe_steam_get("http://test1")
            
        self.assertGreater(steam._cooldown_until, time.time())
        
        # Second request must be blocked immediately WITHOUT calling requests
        with self.assertRaises(SteamCircuitBreakerException):
            _safe_steam_get("http://test2")
            
        # Only the first request actually hit the mock
        self.assertEqual(mock_request.call_count, 1)

    @patch('steam._session.request')
    def test_concurrency_limiter(self, mock_request):
        def slow_request(*args, **kwargs):
            time.sleep(0.5)
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            return mock_resp
            
        mock_request.side_effect = slow_request
        
        results = []
        def worker():
            try:
                _safe_steam_get("http://test")
                results.append("ok")
            except Exception as e:
                results.append(str(e))
                
        threads = [threading.Thread(target=worker) for _ in range(3)]
        
        steam.STEAM_REQUESTS_PER_SECOND = 0
        
        start_time = time.time()
        for t in threads:
            t.start()
        for t in threads:
            t.join()
            
        self.assertEqual(len(results), 3)
        self.assertEqual(mock_request.call_count, 3)
        
        # Thread 1 and 2 start at 0s, finish at 0.5s.
        # Thread 3 starts at 0.5s, finishes at 1.0s.
        # Total time should be ~1.0s.
        elapsed = time.time() - start_time
        self.assertGreaterEqual(elapsed, 0.9)

if __name__ == '__main__':
    unittest.main()
