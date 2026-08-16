"""
Requirement matching -- resolves Steam's free-text CPU/GPU requirement
strings (from services.game.requirements.parse_requirements()) to
records in the hardware ranking catalog (services.hardware.rankings_loader),
by external_id.

This is new code, not a modification of anything existing. It exists
because neither pre-existing hardware system solves this problem:

  - The SQL HardwareDevice/alias_rules track was designed for exactly
    this kind of matching, but has no data (see the compatibility-
    engine inspection report) -- there's nothing to match against.
  - rankings_loader.py has real, validated data but no free-text
    matching layer at all; it's keyed by structured external_id.

MATCHING STRATEGY -- deterministic, exact-match-after-normalization,
never fuzzy/guessed:

  1. Split the requirement string on alternatives ("X or Y or Z").
     Steam commonly lists CPU/GPU requirements this way (e.g.
     "NVIDIA GeForce GTX 660 2GB or AMD Radeon HD 7850 2GB").
  2. For each alternative, strip vendor-brand noise words (and, for
     GPUs, trailing memory-size annotations like "2GB") that appear
     in Steam's free text but not in the catalog's own name/model_name
     fields.
  3. Normalize both the cleaned alternative string and every catalog
     name/model_name to the same comparison key (uppercase,
     non-alphanumeric characters stripped) and look for an EXACT key
     match. No substring/fuzzy matching -- a near-miss is treated as
     "could not resolve," never as a guessed match.
  4. If a normalized key collides across more than one catalog record
     (two different real devices happening to normalize identically),
     that key is excluded from the lookup table entirely. An ambiguous
     match is not a match.

Each resolved alternative returns the catalog external_id, vendor,
name, and the relevant ranking score field, ready for compatibility.py
to compare. Unresolved alternatives are returned with
resolved=False -- callers must never treat these as a pass or a fail,
only as missing information.
"""

import re
from functools import lru_cache

from services.hardware.rankings_loader import get_cpus_with_rankings, get_gpus_with_rankings

# ---------------------------------------------------------------------------
# Alternative splitting ("X or Y")
# ---------------------------------------------------------------------------

_OR_SPLIT_RE = re.compile(r"\bor\b", re.IGNORECASE)


def split_alternatives(text):
    """'GTX 660 2GB or Radeon HD 7850 2GB' -> ['GTX 660 2GB', 'Radeon HD 7850 2GB'].
    A single-device string with no 'or' returns a one-item list.
    Empty/whitespace-only input returns an empty list. Never raises."""
    if not text or not isinstance(text, str):
        return []
    parts = [p.strip() for p in _OR_SPLIT_RE.split(text)]
    return [p for p in parts if p]


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------

_NON_ALNUM_RE = re.compile(r"[^A-Z0-9]")

# Vendor/filler words stripped before building the comparison key.
# These appear in Steam's free text but are inconsistent about
# whether they appear at all (see approved requirement #6:
# "Intel Core i5-2500K" / "Intel Core i5 2500K" / "Intel i5-2500K" /
# "Core i5-2500K" must all resolve identically) -- stripping them
# uniformly from BOTH the query string and the catalog's own
# name/model_name at comparison time is what makes all four variants
# collapse to the same key.
_CPU_STRIP_WORDS = {"INTEL", "AMD", "CORE", "PROCESSOR"}
_GPU_STRIP_WORDS = {"NVIDIA", "AMD", "INTEL"}

# Trailing memory-size annotations Steam appends to GPU requirement
# text ("2GB", "(4 GB)", "6GB VRAM") that never appear in the
# catalog's own `name` field and must be stripped before comparison,
# not treated as part of the model identity.
_TRAILING_MEM_RE = re.compile(
    r"\(?\s*\d+(?:\.\d+)?\s*(?:GB|MB)(?:\s*VRAM)?\)?\.?\s*$",
    re.IGNORECASE,
)


def _strip_trailing_memory(text):
    """Repeatedly strips a trailing memory-size annotation -- a small
    bounded loop (max 3 passes) covers realistic double-annotated
    strings without risking an infinite loop on malformed input."""
    for _ in range(3):
        new_text = _TRAILING_MEM_RE.sub("", text).strip()
        if new_text == text:
            break
        text = new_text
    return text


def _strip_words(text, words):
    tokens = text.split()
    kept = [t for t in tokens if t.upper() not in words]
    return " ".join(kept)


def normalize_cpu_key(text):
    """Deterministic comparison key for a CPU name/requirement
    fragment. Same function applied to both catalog model_name values
    and query text, so identical real-world devices always produce
    identical keys regardless of phrasing (see module docstring point
    3)."""
    if not text or not isinstance(text, str):
        return ""
    cleaned = _strip_words(text.strip(), _CPU_STRIP_WORDS)
    return _NON_ALNUM_RE.sub("", cleaned.upper())


def normalize_gpu_key(text):
    """Deterministic comparison key for a GPU name/requirement
    fragment. Strips vendor words and any trailing memory-size
    annotation before building the key, matching the catalog's own
    `name` field shape (e.g. "GeForce GTX 660", no vendor prefix, no
    memory size)."""
    if not text or not isinstance(text, str):
        return ""
    cleaned = _strip_trailing_memory(text.strip())
    cleaned = _strip_words(cleaned, _GPU_STRIP_WORDS)
    return _NON_ALNUM_RE.sub("", cleaned.upper())


def detect_gpu_vendor_hint(text):
    """Best-effort vendor hint from the requirement text itself, used
    only as a fallback for logging/notes -- the AUTHORITATIVE vendor
    for a resolved match always comes from the catalog record itself
    (see resolve_gpu_alternative below), never from this heuristic.
    Returns 'NVIDIA' / 'AMD' / 'Intel' / None."""
    if not text:
        return None
    upper = text.upper()
    if "NVIDIA" in upper or "GEFORCE" in upper or "RTX" in upper or "GTX" in upper:
        return "NVIDIA"
    if "AMD" in upper or "RADEON" in upper:
        return "AMD"
    if "INTEL" in upper or "ARC" in upper or "UHD" in upper or "IRIS" in upper:
        return "Intel"
    return None


# ---------------------------------------------------------------------------
# Catalog indices (built once, from rankings_loader -- read-only)
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def _cpu_catalog_index():
    """Maps normalize_cpu_key(model_name) -> external_id, EXCLUDING any
    key that more than one distinct CPU record normalizes to (an
    ambiguous key is removed entirely rather than arbitrarily picking
    one -- see module docstring point 4)."""
    records = get_cpus_with_rankings()
    key_to_ids = {}
    for r in records:
        key = normalize_cpu_key(r["model_name"])
        if not key:
            continue
        key_to_ids.setdefault(key, set()).add(r["external_id"])

    return {key: next(iter(ids)) for key, ids in key_to_ids.items() if len(ids) == 1}


@lru_cache(maxsize=1)
def _gpu_catalog_index():
    """Same as _cpu_catalog_index but for GPUs, keyed on `name`."""
    records = get_gpus_with_rankings()
    key_to_ids = {}
    for r in records:
        key = normalize_gpu_key(r["name"])
        if not key:
            continue
        key_to_ids.setdefault(key, set()).add(r["external_id"])

    return {key: next(iter(ids)) for key, ids in key_to_ids.items() if len(ids) == 1}


@lru_cache(maxsize=1)
def _cpu_by_id():
    return {r["external_id"]: r for r in get_cpus_with_rankings()}


@lru_cache(maxsize=1)
def _gpu_by_id():
    return {r["external_id"]: r for r in get_gpus_with_rankings()}


def clear_catalog_cache():
    """Test/dev helper -- clears the lru_cache'd catalog indices so a
    freshly-generated ranking file is picked up without restarting the
    process. Not called anywhere in normal request handling."""
    _cpu_catalog_index.cache_clear()
    _gpu_catalog_index.cache_clear()
    _cpu_by_id.cache_clear()
    _gpu_by_id.cache_clear()


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------

class ResolvedAlternative:
    """One resolved (or unresolved) alternative from a requirement
    string's alternative list. `resolved=False` must always be treated
    by callers as missing information, never as a failing comparison
    -- an unresolved requirement is not the same thing as hardware
    that doesn't meet a requirement."""

    def __init__(self, raw_text, resolved, external_id=None, name=None,
                 vendor=None, score=None):
        self.raw_text = raw_text
        self.resolved = resolved
        self.external_id = external_id
        self.name = name
        self.vendor = vendor
        self.score = score  # performance_score (CPU) or compute_capability_score (GPU); may be None even when resolved, if the catalog record itself has a null score

    def __repr__(self):
        if not self.resolved:
            return f"ResolvedAlternative(unresolved: {self.raw_text!r})"
        return f"ResolvedAlternative({self.name!r}, vendor={self.vendor}, score={self.score})"


def resolve_cpu_requirement(text):
    """Returns a list[ResolvedAlternative] for a CPU requirement
    string (may contain 'or' alternatives). Empty input returns []."""
    alternatives = split_alternatives(text)
    index = _cpu_catalog_index()
    by_id = _cpu_by_id()

    results = []
    for raw in alternatives:
        key = normalize_cpu_key(raw)
        external_id = index.get(key) if key else None
        if not external_id:
            results.append(ResolvedAlternative(raw, resolved=False))
            continue
        record = by_id[external_id]
        score = record["ranking"]["performance_score"] if record["ranking"] else None
        results.append(ResolvedAlternative(
            raw, resolved=True, external_id=external_id,
            name=record["model_name"], vendor=record["manufacturer"], score=score,
        ))
    return results


def resolve_gpu_requirement(text):
    """Returns a list[ResolvedAlternative] for a GPU requirement
    string (may contain 'or' alternatives). Empty input returns []."""
    alternatives = split_alternatives(text)
    index = _gpu_catalog_index()
    by_id = _gpu_by_id()

    results = []
    for raw in alternatives:
        key = normalize_gpu_key(raw)
        external_id = index.get(key) if key else None
        if not external_id:
            results.append(ResolvedAlternative(raw, resolved=False))
            continue
        record = by_id[external_id]
        score = record["ranking"]["compute_capability_score"] if record["ranking"] else None
        results.append(ResolvedAlternative(
            raw, resolved=True, external_id=external_id,
            name=record["name"], vendor=record["vendor"], score=score,
        ))
    return results
