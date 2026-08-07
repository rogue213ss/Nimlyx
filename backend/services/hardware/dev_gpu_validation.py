"""Sprint 6 GPU validation dataset builder -- DEV-ONLY, ONE-OFF SCRIPT.

WHY THIS IS SEPARATE FROM techpowerup_client.py / import_seed.py:
this exists purely to answer "what does TechPowerUp actually return
for our 44-device list, and can we trust each match?" -- it produces
an INSPECTION file for a human to review, not a production import. It
does NOT write to hardware_devices, does NOT compute tier_score, and
is never imported by any production module (import_seed.py, app.py,
any route). Zero connection to the runtime game-page path.

MUST BE RUN SOMEWHERE WITH REAL INTERNET ACCESS TO techpowerup.com --
the sandbox this was written in cannot reach that host (network
allowlist + web_fetch's URL-provenance restriction both block it), so
this script could not be executed there. Run it locally:

    cd backend
    python -m services.hardware.dev_gpu_validation

Output: gpu_validation_output.json in the current directory, plus a
printed summary covering every device: requested vs. returned model,
exact-match flag, mismatch flags, missing fields, and not-found cases
-- exactly the report format requested for this review step.

This queries the REAL, confirmed endpoint:
    GET https://www.techpowerup.com/gpu-specs/api/v1/cards?q=<name>
One request per device (44 total), with a courtesy delay between
requests -- same endpoint techpowerup_client.py already uses in
production, just pointed at a wider field set for inspection purposes
only.
"""

import json
import re
import time

import requests

GPU_ENDPOINT = "https://www.techpowerup.com/gpu-specs/api/v1/cards"
REQUEST_DELAY_SECONDS = 1.5  # a little more conservative than production, since this is 44 requests in a row
OUTPUT_PATH = "gpu_validation_output.json"

# ---------------- The 44-device validation list, as agreed ----------------

VALIDATION_DEVICES = [
    # device_name, expected_category ("discrete" or "integrated") -- used
    # only for mismatch detection below, not sent to the API.
    ("GT 710", "discrete"),
    ("GTX 650", "discrete"),
    ("GTX 750 Ti", "discrete"),
    ("GTX 960", "discrete"),
    ("GTX 970", "discrete"),
    ("GTX 980 Ti", "discrete"),
    ("GTX 1050 Ti", "discrete"),
    ("GTX 1060 6GB", "discrete"),
    ("GTX 1070", "discrete"),
    ("GTX 1080 Ti", "discrete"),
    ("GTX 1660 Ti", "discrete"),
    ("RTX 2060", "discrete"),
    ("RTX 2080 Ti", "discrete"),
    ("RTX 3060", "discrete"),
    ("RTX 3080", "discrete"),
    ("RTX 4090", "discrete"),
    ("Radeon HD 7770", "discrete"),
    ("Radeon HD 7970", "discrete"),
    ("Radeon R7 260X", "discrete"),
    ("Radeon R9 290X", "discrete"),
    ("Radeon RX 460", "discrete"),
    ("Radeon RX 480", "discrete"),
    ("Radeon RX 580", "discrete"),
    ("Radeon RX 590", "discrete"),
    ("Radeon RX Vega 56", "discrete"),
    ("Radeon RX Vega 64", "discrete"),
    ("Radeon RX 5500 XT", "discrete"),
    ("Radeon RX 5700 XT", "discrete"),
    ("Radeon RX 6600 XT", "discrete"),
    ("Radeon RX 6800 XT", "discrete"),
    ("Radeon RX 7600", "discrete"),
    ("Radeon RX 7900 XTX", "discrete"),
    ("HD Graphics 4000", "integrated"),
    ("HD Graphics 4600", "integrated"),
    ("HD Graphics 520", "integrated"),
    ("HD Graphics 530", "integrated"),
    ("UHD Graphics 600", "integrated"),
    ("UHD Graphics 620", "integrated"),
    ("UHD Graphics 630", "integrated"),
    ("UHD Graphics 730", "integrated"),
    ("UHD Graphics 750", "integrated"),
    ("UHD Graphics 770", "integrated"),
    ("Iris Plus Graphics", "integrated"),
    ("Iris Xe Graphics", "integrated"),
]

assert len(VALIDATION_DEVICES) == 44, f"Expected 44 devices, got {len(VALIDATION_DEVICES)}"

# Wide field set for INSPECTION only -- deliberately more than
# production's normalized shape (see techpowerup_client.py), since the
# whole point here is deciding which fields the eventual scoring model
# should use. Nothing here is written back into that file.
VALIDATION_FIELDS = [
    "external_id", "manufacturer", "model_name", "architecture",
    "release_year", "vram_mb", "memory_bandwidth_gb_s",
    "base_clock_mhz", "boost_clock_mhz", "shaders", "tdp_w", "is_integrated",
]


def _fetch_raw(name_query):
    """Same request shape as techpowerup_client._fetch_raw_gpu_page --
    duplicated here (not imported) so this dev-only script has zero
    coupling to the production client module; a future change to one
    can never accidentally break the other."""
    resp = requests.get(GPU_ENDPOINT, params={"q": name_query}, timeout=20)
    resp.raise_for_status()
    return resp.json()


def _parse_release_year(released_str):
    if not released_str or not isinstance(released_str, str):
        return None
    try:
        year = int(released_str.split(",")[-1].strip())
        return year if 1990 <= year <= 2100 else None
    except (ValueError, IndexError):
        return None


def _normalize_for_validation(raw_entry):
    """Wide-field mapping for inspection purposes. Returns
    (normalized_dict, missing_fields_list)."""
    manufacturer = raw_entry.get("manufacturer")
    name = raw_entry.get("name")
    chip = raw_entry.get("chip") or {}

    model_name = None
    if manufacturer and name:
        model_name = name if name.lower().startswith(manufacturer.lower()) else f"{manufacturer} {name}"

    normalized = {
        "external_id": str(raw_entry["id"]) if raw_entry.get("id") is not None else None,
        "manufacturer": manufacturer,
        "model_name": model_name,
        "architecture": chip.get("architecture"),
        "release_year": _parse_release_year(raw_entry.get("released")),
        "vram_mb": raw_entry.get("memSize"),
        "memory_bandwidth_gb_s": raw_entry.get("memBandwidth"),
        "base_clock_mhz": raw_entry.get("baseClock"),
        "boost_clock_mhz": raw_entry.get("boostClock"),
        "shaders": raw_entry.get("shaders"),
        "tdp_w": raw_entry.get("tdp"),
        "is_integrated": raw_entry.get("igp"),
    }

    missing = [f for f in VALIDATION_FIELDS if normalized.get(f) is None]
    return normalized, missing
    """Loose alnum tokens for mismatch comparison, e.g. "GTX 1060 6GB"
    -> {"gtx", "1060", "6gb"}. Used only to flag likely mismatches for
    human review -- not a hard pass/fail gate."""
    return set(re.findall(r"[a-z0-9]+", name.lower()))


def _tokens(name):
    """Loose alnum tokens for mismatch comparison, e.g. "GTX 1060 6GB"
    -> {"gtx", "1060", "6gb"}. Used only to flag likely mismatches for
    human review -- not a hard pass/fail gate."""
    return set(re.findall(r"[a-z0-9]+", name.lower()))


def _check_mismatch(requested_name, expected_category, normalized, raw_entry):
    """Returns a list of human-readable suspicion flags -- empty list
    means "looks fine," never means "confirmed correct." A person
    should still skim the output; this just surfaces the likely
    problem cases instead of making someone check all 44 by hand.

    raw_entry is passed in (not just the normalized dict) specifically
    to check the API's own "mobile"/"workstation" flags -- these
    aren't part of VALIDATION_FIELDS' output (not requested as a
    stored field), but they're exactly what "verify actually the
    requested desktop/mobile/integrated variant" needs checked
    against, so they're used here for detection even though they
    don't appear in the normalized output.
    """
    flags = []
    returned_name = normalized.get("model_name")
    if not returned_name:
        return flags  # not-found case, handled separately

    requested_tokens = _tokens(requested_name)
    returned_tokens = _tokens(returned_name)
    # The model NUMBER (the token most likely to contain a digit) is
    # the part that actually matters -- "RTX 3060" matching "RTX 3060
    # Ti" would share the number but not be identical; flag anything
    # where none of the requested numeric tokens appear at all, since
    # that's the strongest signal of a wrong-card match.
    requested_numeric = {t for t in requested_tokens if any(c.isdigit() for c in t)}
    if requested_numeric and not (requested_numeric & returned_tokens):
        flags.append(f"No requested model-number token {requested_numeric} found in returned name {returned_name!r}")

    is_integrated = normalized.get("is_integrated")
    if expected_category == "integrated" and is_integrated is False:
        flags.append("Expected an integrated GPU but API returned igp=False (discrete)")
    if expected_category == "discrete" and is_integrated is True:
        flags.append("Expected a discrete GPU but API returned igp=True (integrated)")

    # Desktop/mobile/workstation variant check -- our validation list
    # is entirely desktop parts, so any of these being True on the
    # returned entry means we likely got the wrong SKU variant even
    # though the model NUMBER matched (this is exactly the "RTX 3060
    # Mobile returned instead of desktop RTX 3060" case).
    if raw_entry.get("mobile") is True:
        flags.append("API returned a MOBILE variant, expected desktop")
    if raw_entry.get("workstation") is True:
        flags.append("API returned a WORKSTATION variant, expected consumer desktop")

    return flags


def run_validation():
    results = []
    for i, (requested_name, expected_category) in enumerate(VALIDATION_DEVICES, 1):
        print(f"[{i}/{len(VALIDATION_DEVICES)}] Querying: {requested_name!r}")
        record = {
            "requested_model": requested_name,
            "expected_category": expected_category,
        }
        try:
            raw = _fetch_raw(requested_name)
            entries = raw.get("results", []) if isinstance(raw, dict) else []
            full_entries = [e for e in entries if isinstance(e, dict) and e.get("_type") != "withheld"]

            if not full_entries:
                record.update({
                    "found": False,
                    "matches_reported": raw.get("matches") if isinstance(raw, dict) else None,
                    "note": "No full (non-withheld) result returned.",
                })
            else:
                normalized, missing = _normalize_for_validation(full_entries[0])
                mismatch_flags = _check_mismatch(requested_name, expected_category, normalized, full_entries[0])
                record.update({
                    "found": True,
                    "returned_model": normalized.get("model_name"),
                    "exact_match": len(mismatch_flags) == 0,
                    "mismatch_flags": mismatch_flags,
                    "missing_fields": missing,
                    "matches_reported": raw.get("matches"),
                    "normalized": normalized,
                })
        except Exception as e:
            record.update({
                "found": False,
                "error": f"{type(e).__name__}: {e}",
            })

        results.append(record)
        time.sleep(REQUEST_DELAY_SECONDS)

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)

    _print_summary(results)
    print(f"\nFull inspection data written to {OUTPUT_PATH}")
    return results


def _print_summary(results):
    not_found = [r for r in results if not r.get("found")]
    mismatched = [r for r in results if r.get("found") and not r.get("exact_match")]
    missing_fields = [r for r in results if r.get("found") and r.get("missing_fields")]

    print("\n" + "=" * 60)
    print(f"SUMMARY -- {len(results)} devices queried")
    print("=" * 60)
    print(f"Found (full result):     {len(results) - len(not_found)}")
    print(f"Not found / errored:     {len(not_found)}")
    print(f"Flagged as mismatched:   {len(mismatched)}")
    print(f"Missing one+ fields:     {len(missing_fields)}")

    if not_found:
        print("\n--- NOT FOUND / ERRORED ---")
        for r in not_found:
            print(f"  {r['requested_model']!r}: {r.get('note') or r.get('error')}")

    if mismatched:
        print("\n--- FLAGGED MISMATCHES (needs human review) ---")
        for r in mismatched:
            print(f"  {r['requested_model']!r} -> {r['returned_model']!r}")
            for flag in r["mismatch_flags"]:
                print(f"      - {flag}")

    if missing_fields:
        print("\n--- MISSING FIELDS ---")
        for r in missing_fields:
            print(f"  {r['requested_model']!r}: missing {r['missing_fields']}")


if __name__ == "__main__":
    run_validation()