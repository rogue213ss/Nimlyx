import time
import os
import statistics
from app import app
from services.hardware.engine.nimlyx_adapter import NimlyxAdapter

def run_benchmark():
    app.config['TESTING'] = True
    os.environ['REQUIREMENTS_ENGINE_ENABLED'] = 'True'
    
    adapter = NimlyxAdapter()
    
    # warmup
    for _ in range(5):
        adapter.evaluate_production_endpoint(730, "cpu-intelcorei913900k", "nvidia-geforce-rtx-4090", 32.0)
        
    latencies = []
    for _ in range(500):
        t0 = time.perf_counter()
        adapter.evaluate_production_endpoint(730, "cpu-intelcorei913900k", "nvidia-geforce-rtx-4090", 32.0)
        t1 = time.perf_counter()
        latencies.append((t1 - t0) * 1000)
        
    latencies.sort()
    
    p50 = latencies[int(len(latencies) * 0.50)]
    p95 = latencies[int(len(latencies) * 0.95)]
    p99 = latencies[int(len(latencies) * 0.99)]
    
    print(f"P50: {p50:.2f} ms")
    print(f"P95: {p95:.2f} ms")
    print(f"P99: {p99:.2f} ms")

if __name__ == '__main__':
    run_benchmark()
