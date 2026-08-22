"""
REGION / CURRENCY — resolves which Steam "cc" (country code) to use
for a given request. Priority:
  1. Manual override cookie (set via the region picker in the UI)
  2. IP geolocation (best-effort, cached per IP for this process)
  3. "US" fallback
Steam prices/formats everything server-side once you pass the right
cc — no currency-symbol logic needed on our end.
"""
from flask import Blueprint, jsonify, request
import requests

region_bp = Blueprint("region", __name__)

REGION_OPTIONS = [
    {"code": "US", "label": "United States (USD)"},
    {"code": "PK", "label": "Pakistan (PKR)"},
    {"code": "GB", "label": "United Kingdom (GBP)"},
    {"code": "IN", "label": "India (INR)"},
    {"code": "DE", "label": "Germany (EUR)"},
    {"code": "CA", "label": "Canada (CAD)"},
    {"code": "AU", "label": "Australia (AUD)"},
    {"code": "AE", "label": "UAE (AED)"},
    {"code": "TR", "label": "Turkey (TRY)"},
    {"code": "JP", "label": "Japan (JPY)"},
    {"code": "BR", "label": "Brazil (BRL)"},
]
REGION_CODES = {opt["code"] for opt in REGION_OPTIONS}

_geoip_cache = {}


def get_client_ip():
    """Devtunnels/reverse proxies put the real client IP in
    X-Forwarded-For; fall back to the raw socket address."""
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.remote_addr


import threading
_geoip_lock = threading.Lock()
_geoip_in_progress = set()

def _fetch_geo_ip(ip):
    try:
        resp = requests.get(
            f"http://ip-api.com/json/{ip}?fields=status,countryCode",
            timeout=3,
        )
        data = resp.json()
        if data.get("status") == "success":
            with _geoip_lock:
                _geoip_cache[ip] = data.get("countryCode")
    except (requests.exceptions.RequestException, ValueError):
        with _geoip_lock:
            # Cache None briefly or permanently? Let's cache 'US' to prevent retrying constantly
            _geoip_cache[ip] = "US"
    finally:
        with _geoip_lock:
            _geoip_in_progress.discard(ip)

def geo_lookup_cc(ip):
    """Best-effort IP -> ISO country code lookup via ip-api.com's free
    tier. Returns None on cold start (caller falls back to US), kicks
    off a background fetch so the NEXT request from this IP gets the
    real region. Never blocks the page load."""
    if not ip or ip in ("127.0.0.1", "localhost", "::1"):
        return None
    if ip.startswith("10.") or ip.startswith("192.168.") or ip.startswith("172."):
        return None

    with _geoip_lock:
        if ip in _geoip_cache:
            return _geoip_cache[ip]
        building = ip in _geoip_in_progress

    if not building:
        with _geoip_lock:
            _geoip_in_progress.add(ip)
        threading.Thread(target=_fetch_geo_ip, args=(ip,), daemon=True).start()

    return None


def get_region_code():
    """The cc to use for this request: manual cookie override first,
    otherwise IP geolocation, otherwise 'US'."""
    cookie_cc = (request.cookies.get("nimlyx_cc") or "").upper()
    if cookie_cc in REGION_CODES:
        return cookie_cc

    detected = geo_lookup_cc(get_client_ip())
    return (detected or "US").upper()


@region_bp.route("/api/region")
def get_region():
    cookie_cc = (request.cookies.get("nimlyx_cc") or "").upper()
    detected = (geo_lookup_cc(get_client_ip()) or "US").upper()
    return jsonify({
        "active": cookie_cc if cookie_cc in REGION_CODES else detected,
        "detected": detected,
        "is_manual": cookie_cc in REGION_CODES,
        "options": REGION_OPTIONS,
    })


@region_bp.route("/api/region/<code>", methods=["POST"])
def set_region(code):
    code = code.strip().upper()
    if code not in REGION_CODES:
        return jsonify({"error": "Unsupported region code"}), 400
    resp = jsonify({"region": code})
    resp.set_cookie("nimlyx_cc", code, max_age=60 * 60 * 24 * 365, samesite="Lax")
    return resp


@region_bp.route("/api/region/reset", methods=["POST"])
def reset_region():
    resp = jsonify({"region": "auto"})
    resp.delete_cookie("nimlyx_cc")
    return resp
