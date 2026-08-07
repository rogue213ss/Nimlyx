"""One-off diagnostic probe -- NOT the validation run, NOT production.

Purpose: dev_gpu_validation.py's full 44-device run showed every query
after #12 failing with an identical JSONDecodeError. That error alone
doesn't tell us WHAT the server is actually sending back (HTTP 200 +
HTML challenge page? 429? 403? a JSON quota-error body that just has
a different shape than expected?). This script exists purely to
capture that raw evidence, on a handful of requests, so a human can
look at it and figure out the actual mechanism before we design
anything around it.

Deliberately tiny: default is 5 requests, spaced 10s apart (not the
44-device / 1.5s pattern that seemed to trigger the block last time).
Goal is to get a diagnosis cheaply, not to complete the seed run.

Zero coupling to dev_gpu_validation.py or techpowerup_client.py --
same reasoning dev_gpu_validation.py already documents for staying
decoupled from the production client: this is throwaway inspection
code, nothing here should ever be imported elsewhere.

MUST BE RUN SOMEWHERE WITH REAL INTERNET ACCESS TO techpowerup.com.
This sandbox cannot reach that host (confirmed: egress blocked,
"Host not in allowlist: www.techpowerup.com"), so this could not be
executed here. Run it locally:

    cd backend
    python -m services.hardware.diag_probe

Output: prints a report per request to stdout, and writes the same
data to diag_probe_output.json for reference.
"""

import json
import time

import requests

GPU_ENDPOINT = "https://www.techpowerup.com/gpu-specs/api/v1/cards"
OUTPUT_PATH = "diag_probe_output.json"

# Small, deliberately spaced-out probe set. Mix of a query that
# succeeded last time (GTX 970) and ones that hit the JSONDecodeError
# (RTX 2080 Ti, RTX 3060) -- if GTX 970 now ALSO fails, that tells us
# this isn't about which specific query, it's a time-based or
# session-based block that's still in effect.
PROBE_QUERIES = [
    "GTX 970",
    "RTX 2080 Ti",
    "RTX 3060",
    "RTX 4090",
    "Radeon RX 6800 XT",
]

# Wait between requests. Generous on purpose for a 5-request probe --
# the point is to remove pacing as a variable while we figure out the
# actual mechanism, not to optimize for speed.
REQUEST_DELAY_SECONDS = 10.0

# Deliberately descriptive, honest User-Agent identifying the request
# rather than relying on requests' default UA string.
HEADERS = {
    "User-Agent": (
        "Nimlyx-Dev-Diagnostic/0.1 "
        "(+internal tool, evaluating TechPowerUp API access for hardware "
        "seed data; contact: <add project contact email before running "
        "against production if TechPowerUp asks>)"
    ),
    "Accept": "application/json",
}

# Headers worth capturing specifically if present -- these are the
# ones that would tell us definitively "this is rate limiting" vs.
# something else.
RATE_LIMIT_HEADER_NAMES = [
    "Retry-After",
    "X-RateLimit-Limit",
    "X-RateLimit-Remaining",
    "X-RateLimit-Reset",
    "RateLimit-Limit",
    "RateLimit-Remaining",
    "RateLimit-Reset",
    "X-Robots-Tag",
    "Server",
    "CF-RAY",  # Cloudflare -- presence alone is informative
    "cf-mitigated",
]


def _probe_one(request_number, name_query):
    record = {
        "request_number": request_number,
        "query": name_query,
    }
    start = time.monotonic()
    try:
        resp = requests.get(
            GPU_ENDPOINT,
            params={"q": name_query},
            headers=HEADERS,
            timeout=20,
        )
        elapsed = time.monotonic() - start

        record["http_status"] = resp.status_code
        record["elapsed_seconds"] = round(elapsed, 3)
        record["content_type"] = resp.headers.get("Content-Type")
        record["body_length"] = len(resp.content)
        record["body_preview_first_500_chars"] = resp.text[:500]

        rate_limit_headers = {
            h: resp.headers[h] for h in RATE_LIMIT_HEADER_NAMES if h in resp.headers
        }
        record["rate_limit_relevant_headers"] = rate_limit_headers
        record["all_response_headers"] = dict(resp.headers)

        try:
            parsed = resp.json()
            record["json_parse_succeeded"] = True
            record["json_top_level_keys"] = (
                list(parsed.keys()) if isinstance(parsed, dict) else None
            )
        except Exception as e:
            record["json_parse_succeeded"] = False
            record["json_parse_error"] = f"{type(e).__name__}: {e}"

    except requests.exceptions.RequestException as e:
        elapsed = time.monotonic() - start
        record["elapsed_seconds"] = round(elapsed, 3)
        record["request_exception"] = f"{type(e).__name__}: {e}"

    return record


def run_probe():
    results = []
    for i, query in enumerate(PROBE_QUERIES, 1):
        print(f"[{i}/{len(PROBE_QUERIES)}] Probing: {query!r}")
        record = _probe_one(i, query)
        results.append(record)

        status = record.get("http_status", "N/A (request exception)")
        ctype = record.get("content_type", "N/A")
        parsed_ok = record.get("json_parse_succeeded", "N/A")
        print(f"    HTTP {status} | Content-Type: {ctype} | JSON parsed: {parsed_ok} "
              f"| elapsed: {record.get('elapsed_seconds')}s")
        if record.get("rate_limit_relevant_headers"):
            print(f"    Rate-limit-relevant headers: {record['rate_limit_relevant_headers']}")
        if not parsed_ok and parsed_ok != "N/A":
            preview = record["body_preview_first_500_chars"].replace("\n", "\\n")
            print(f"    Body preview: {preview[:200]}...")

        if i < len(PROBE_QUERIES):
            time.sleep(REQUEST_DELAY_SECONDS)

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)

    print(f"\nFull diagnostic data written to {OUTPUT_PATH}")
    print("\nNext step: inspect the output above/in the file and match against:")
    print("  - HTTP 200 + non-JSON body containing 'captcha'/'challenge'/'cloudflare' "
          "-> bot-mitigation HTML challenge")
    print("  - HTTP 429 -> explicit rate limiting (check Retry-After)")
    print("  - HTTP 403 -> blocked/forbidden (check body for reason)")
    print("  - HTTP 200 + JSON body with an error/quota field -> API-level quota response")
    print("  - Something else -> paste this output for review before deciding next steps")
    return results


if __name__ == "__main__":
    run_probe()
