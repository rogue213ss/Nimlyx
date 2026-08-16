import time
import requests
import sys

base_url = "http://127.0.0.1:5000"

def measure(url, name):
    print(f"--- Measuring {name} ---")
    start = time.time()
    try:
        r = requests.get(base_url + url)
        duration = time.time() - start
        size = len(r.content)
        print(f"URL: {url}")
        print(f"Status: {r.status_code}")
        print(f"Time: {duration:.3f}s")
        print(f"Size: {size / 1024:.1f} KB")
        return duration
    except Exception as e:
        print(f"Error: {e}")
        return None

print("Starting tests...")

# 1. Measure /api/featured
t1 = measure("/api/featured", "/api/featured (first request)")
t2 = measure("/api/featured", "/api/featured (second request - checks for caching)")

# 2. Measure /api/search-results/
t3 = measure("/api/search-results/portal", "/api/search-results/portal (first request)")
t4 = measure("/api/search-results/portal", "/api/search-results/portal (second request)")

print("Tests complete.")
