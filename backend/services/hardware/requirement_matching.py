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
#
# ROOT CAUSE FIX: this originally only split on the literal word "or".
# In practice Steam's free-text CPU/GPU requirement strings just as
# often list alternatives with commas and/or slashes instead of "or"
# -- e.g. "Intel Core i5-2400S @ 2.5 GHz, AMD FX-4320 @ 4 GHz,
# equivalent" or "NVIDIA GeForce GTX 970 / GTX 1060, AMD R9 390 /
# RX 480 (4GB VRAM with Shader Model 5.0, better)". Splitting only on
# "or" left the ENTIRE string as one unsplittable blob, which could
# never normalize to match a single catalog record -- that's what
# produced "Unable to determine" even for hardware that genuinely is
# in the catalog (e.g. the i7-3770 in that second example). This
# never weakens matching: every fragment still goes through the same
# exact-key-after-normalization comparison as before, so nothing is
# guessed -- more of the SAME deterministic check is just now applied
# to the individual devices Steam actually listed.

_OR_SPLIT_RE = re.compile(r"\bor\b", re.IGNORECASE)
_ALT_DELIM_RE = re.compile(r"[,/]")

# Parenthetical spec-annotation noise ("(4GB VRAM with Shader Model
# 5.0, better)") -- removed whole, before delimiter splitting, so a
# comma INSIDE the annotation can't be mistaken for an alternative
# separator. Only parens that look like a spec annotation (contain a
# digit, or GB/MB/VRAM/Shader) are stripped; other parenthetical text
# is left alone rather than assumed to be noise.
_ANNOTATION_PARENS_RE = re.compile(
    r"\(([^()]*(?:\d|GB|MB|VRAM|Shader)[^()]*)\)",
    re.IGNORECASE,
)

# Trailing qualifier words Steam appends after a real device list
# ("...FX-8350 @ 4 GHz, better", "...HD 7850 2GB, equivalent") --
# these describe the comparison, they are not a hardware name, and
# comma-splitting would otherwise turn them into a bogus "unresolved
# alternative" that clutters notes without meaning anything.
_QUALIFIER_FRAGMENTS = {
    "equivalent", "better", "similar", "comparable",
    "or better", "or equivalent", "or similar", "or comparable",
    "or higher", "higher", "or newer", "newer",
}


def split_alternatives(text):
    """'GTX 660 2GB or Radeon HD 7850 2GB' -> ['GTX 660 2GB', 'Radeon HD 7850 2GB'].
    Also splits on commas and slashes, since Steam lists alternatives
    both ways ('GTX 970 / GTX 1060', 'X, Y, equivalent'), and drops
    trailing qualifier words that aren't a device name (see
    _QUALIFIER_FRAGMENTS). A single-device string with no delimiter
    returns a one-item list. Empty/whitespace-only input returns an
    empty list. Never raises."""
    if not text or not isinstance(text, str):
        return []

    no_annotations = _ANNOTATION_PARENS_RE.sub("", text)

    parts = []
    for or_part in _OR_SPLIT_RE.split(no_annotations):
        parts.extend(_ALT_DELIM_RE.split(or_part))

    cleaned = [p.strip().strip(".").strip() for p in parts]
    return [p for p in cleaned if p and p.lower() not in _QUALIFIER_FRAGMENTS]


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
_CPU_STRIP_WORDS = {"INTEL", "AMD", "CORE", "PROCESSOR", "EIGHT-CORE", "SIX-CORE", "QUAD-CORE", "DUAL-CORE"}
# NOTE: originally just the three company names. That left the
# catalog's own GPU `name` field (which is ALWAYS brand-prefixed,
# e.g. "Radeon RX 480", "GeForce RTX 5050") permanently mismatched
# against any query that used the company name instead of the brand
# name (e.g. "AMD RX 480", "NVIDIA RTX 5050") -- both legitimate,
# common Steam/user phrasings. GEFORCE/RADEON are stripped from BOTH
# sides for the same reason the company names are: they're brand
# noise, not part of the model identity, and stripping them
# symmetrically is what makes "AMD RX 480" and "Radeon RX 480"
# collapse to the same key. Any resulting collision (e.g. two
# differently-branded families reducing to an identical remainder)
# is still caught by the existing ambiguous-key exclusion in
# _cpu_catalog_index/_gpu_catalog_index below -- this change doesn't
# weaken that guarantee.
_GPU_STRIP_WORDS = {"NVIDIA", "AMD", "INTEL", "GEFORCE", "RADEON"}

# Trailing memory-size annotations Steam appends to GPU requirement
# text ("2GB", "(4 GB)", "6GB VRAM") that never appear in the
# catalog's own `name` field and must be stripped before comparison,
# not treated as part of the model identity.
_TRAILING_MEM_RE = re.compile(
    r"\(?\s*\d+(?:\.\d+)?\s*(?:GB|MB)(?:\s*VRAM)?\)?\.?\s*$",
    re.IGNORECASE,
)

# Trailing "with Shader Model N.N" -- another GPU-requirement
# annotation ("...Radeon HD 7850 2GB VRAM with Shader Model 5.0")
# that's never part of the catalog's own `name` field. Stripped in
# the same repeated-pass loop as the memory annotation, since a
# string can end with both ("...2GB VRAM with Shader Model 5.0").
_TRAILING_SHADER_RE = re.compile(
    r"\bwith\s+shader\s+model\s+\d+(?:\.\d+)?\.?\s*$",
    re.IGNORECASE,
)


def _strip_trailing_memory(text):
    """Repeatedly strips a trailing memory-size and/or shader-model
    annotation -- a small bounded loop (max 4 passes) covers realistic
    multiply-annotated strings without risking an infinite loop on
    malformed input."""
    for _ in range(4):
        new_text = _TRAILING_MEM_RE.sub("", text).strip()
        new_text = _TRAILING_SHADER_RE.sub("", new_text).strip()
        if new_text == text:
            break
        text = new_text
    return text


# Trailing clock-speed annotations Steam appends to CPU requirement
# text ("@ 2.5 GHz", "@ 4 GHz") that never appear in the catalog's
# own `model_name` field -- same reasoning as the GPU memory-size
# strip above, just the CPU-side equivalent noise.
_TRAILING_CLOCK_RE = re.compile(
    r"@\s*\d+(?:\.\d+)?\s*GHz\.?\s*$",
    re.IGNORECASE,
)


def _strip_trailing_clock(text):
    """Repeatedly strips a trailing '@ N GHz' annotation, bounded the
    same way _strip_trailing_memory is."""
    for _ in range(3):
        new_text = _TRAILING_CLOCK_RE.sub("", text).strip()
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
    # Strip trademarks before alphanumeric stripping to avoid leaving 'R' or 'TM'
    cleaned = re.sub(r"\(R\)|\(TM\)|®|™", "", text, flags=re.IGNORECASE)
    cleaned = _strip_trailing_clock(cleaned.strip())
    cleaned = _strip_words(cleaned, _CPU_STRIP_WORDS)
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

_GENERIC_CPU_KEYS = {
    "RYZEN", "CORE", "COREI3", "COREI5", "COREI7", "COREI9",
    "RYZEN3", "RYZEN5", "RYZEN7", "RYZEN9", "PENTIUM", "CELERON",
    "ATHLON", "FX", "EPYC", "XEON", "OPTERON", "THREADRIPPER"
}

@lru_cache(maxsize=1)
def _cpu_catalog_index():
    """Maps normalize_cpu_key(model_name) -> external_id, EXCLUDING any
    key that more than one distinct CPU record normalizes to (an
    ambiguous key is removed entirely rather than arbitrarily picking
    one -- see module docstring point 4). Also indexes aliases and blocks generic families."""
    records = get_cpus_with_rankings()
    key_to_ids = {}
    for r in records:
        key = normalize_cpu_key(r["model_name"])
        if key:
            key_to_ids.setdefault(key, set()).add(r["external_id"])
            
        aliases_str = r.get("aliases", "")
        if aliases_str:
            for alias in aliases_str.split(","):
                akey = normalize_cpu_key(alias.strip())
                if akey:
                    key_to_ids.setdefault(akey, set()).add(r["external_id"])

    # Discard ambiguous keys and explicitly generic families
    valid_index = {}
    for key, ids in key_to_ids.items():
        if len(ids) == 1 and key not in _GENERIC_CPU_KEYS:
            valid_index[key] = next(iter(ids))
    return valid_index


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
