"""TechPowerUp hardware API adapter.

STATUS -- GPU path fully wired and verified against a real response:

    GET https://www.techpowerup.com/gpu-specs/api/v1/cards?q=<name>

Confirmed response envelope:
    {"status": "success", "matches": N, "totalQueried": N, "results": [...]}
Each result is either a full spec dict (manufacturer, name, released,
chip, memSize, etc.) or a free-tier gating placeholder:
    {"_type": "withheld", "message": "...license..."}

IMPORTANT -- free-tier result gating: a single query can match several
devices (board variants, mobile/desktop versions, etc.) but only
returns ONE full record; the rest come back withheld regardless of how
broad or narrow the query is. This means an unfiltered "fetch
everything" call is NOT the right shape for bulk seeding -- it mostly
returns withheld placeholders. The reliable path is
fetch_many_by_name(), which queries once PER SPECIFIC MODEL NAME (each
specific query's primary match comes back in full). This means Sprint
6 still needs a curated list of target model names to search for --
that's a much smaller ask than compiling full specs by hand (the API
supplies everything else), but it's still an open item -- see chat.

CPU endpoint: NOT confirmed. The GPU path uses a "gpu-specs" prefix; a
"cpu-specs/api/v1/..." equivalent is a reasonable guess but unverified,
so it's left unimplemented rather than assumed correct.

Everything downstream (coverage.py, tier_scoring.py, alias_rules.py,
import_seed.py) is built and tested against the normalized contract
below and needs no changes now that this file is wired up.
"""

import time

import requests

GPU_ENDPOINT = "https://www.techpowerup.com/gpu-specs/api/v1/cards"

# CPU endpoint not yet confirmed -- see module docstring. Left as None
# so calling fetch_and_normalize("cpu") fails clearly (NotImplementedError
# below) instead of silently guessing a URL that might 404 or, worse,
# might exist but return something completely unrelated.
CPU_ENDPOINT = None

# Courtesy delay between requests -- this is a one-time seed run, not
# a hot loop, so there's no performance reason to hammer their server;
# matches the spirit of "reasonable rate limits" mentioned on their
# licensing page even though no explicit limit was published.
_REQUEST_DELAY_SECONDS = 1.0

NORMALIZED_DEVICE_SHAPE = """
Each device from fetch_and_normalize() is a dict:
{
    "external_id": str or None,   # TechPowerUp's own stable ID, if the API provides one
    "type": "gpu" or "cpu",
    "manufacturer": str,          # "NVIDIA" / "AMD" / "Intel"
    "model_name": str,            # canonical name, UNCHANGED from source,
                                   # e.g. "NVIDIA GeForce RTX 3060"
    "vram_mb": int or None,       # GPUs only
    "release_year": int or None,
}
"""


def _fetch_raw_gpu_page(name_query=None):
    """Makes the actual HTTP request against the real, confirmed
    endpoint. Returns the raw parsed JSON response (the full envelope
    -- {"status", "matches", "results": [...], ...} -- not just the
    results list, so fetch_and_normalize can see status/matches too).
    """
    params = {}
    if name_query:
        params["q"] = name_query  # confirmed param name: q, not "name"
    resp = requests.get(GPU_ENDPOINT, params=params, timeout=20)
    resp.raise_for_status()
    return resp.json()


def _parse_release_year(released_str):
    """"Oct 12th, 2022" -> 2022. Returns None (never raises) for
    missing/malformed dates -- release_year is a nice-to-have field,
    never worth failing an otherwise-good import over."""
    if not released_str or not isinstance(released_str, str):
        return None
    try:
        # Year is reliably the last comma-separated segment in every
        # observed format ("Mon Ddd(th|st|nd|rd), YYYY").
        year_part = released_str.split(",")[-1].strip()
        year = int(year_part)
        if 1990 <= year <= 2100:  # sanity bound, not a real validation
            return year
        return None
    except (ValueError, IndexError):
        return None


def _map_raw_gpu_entry(raw_entry):
    """Maps one entry from the confirmed response shape onto
    NORMALIZED_DEVICE_SHAPE. Returns None (not an error) for withheld
    entries (free-tier gating -- {"_type": "withheld", ...}, no usable
    fields) or any entry missing the fields this import actually
    needs -- callers filter out Nones rather than treating a withheld
    placeholder as a device with blank data.

    model_name is built as "{manufacturer} {name}" (e.g. "NVIDIA" +
    "GeForce RTX 4090" -> "NVIDIA GeForce RTX 4090") to match the
    canonical format used throughout this pipeline (coverage.py,
    tier_scoring.py, alias_rules.py, hardware_aliases.json) -- the
    API's own "name" field omits the manufacturer prefix.
    """
    if not isinstance(raw_entry, dict) or raw_entry.get("_type") == "withheld":
        return None

    manufacturer = raw_entry.get("manufacturer")
    name = raw_entry.get("name")
    if not manufacturer or not name:
        return None

    model_name = name if name.lower().startswith(manufacturer.lower()) else f"{manufacturer} {name}"

    return {
        "external_id": str(raw_entry["id"]) if raw_entry.get("id") is not None else None,
        "type": "gpu",
        "manufacturer": manufacturer,
        "model_name": model_name,
        "vram_mb": raw_entry.get("memSize"),
        "release_year": _parse_release_year(raw_entry.get("released")),
    }


def fetch_and_normalize(device_type, name_query=None):
    """device_type: "gpu" or "cpu". name_query: a specific model name
    to search for (recommended -- see module docstring on free-tier
    result withholding for broad/unfiltered queries). Returns a list
    of dicts matching NORMALIZED_DEVICE_SHAPE, with withheld/
    unmappable entries silently filtered out (not errors -- expected
    free-tier behavior, see _map_raw_gpu_entry).
    """
    if device_type == "gpu":
        raw = _fetch_raw_gpu_page(name_query=name_query)
        time.sleep(_REQUEST_DELAY_SECONDS)
        results = raw.get("results", []) if isinstance(raw, dict) else []
        return [d for d in (_map_raw_gpu_entry(entry) for entry in results) if d is not None]

    if device_type == "cpu":
        if not CPU_ENDPOINT:
            raise NotImplementedError(
                "CPU endpoint not yet confirmed -- see this module's docstring."
            )

    raise ValueError(f"Unknown device_type: {device_type!r}")


def fetch_many_by_name(device_type, names):
    """Convenience wrapper for the realistic import shape: given a
    curated list of specific model names to search for (see module
    docstring -- broad unfiltered queries are gated by the free tier),
    fetches each one individually and flattens the results. This is
    what import_seed.py's main() should actually call, once a target
    name list exists (Sprint 6's remaining open item -- see chat).
    Skips (doesn't crash on) any single name's request failure so one
    bad/unmatched query doesn't abort the whole batch; returns
    whatever succeeded.
    """
    all_devices = []
    for name in names or []:
        try:
            all_devices.extend(fetch_and_normalize(device_type, name_query=name))
        except Exception:
            continue
    return all_devices