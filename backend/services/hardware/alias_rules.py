"""Alias generation for hardware_devices rows -- the strings a future
compatibility engine will match against Steam's free-text requirement
lines (e.g. "GeForce RTX 3060 or better").

Two sources, merged:

  1. GENERATED -- deterministic, rule-based, produced automatically
     from the canonical model_name (see generate_aliases()).
  2. MANUAL -- hand-curated overrides/additions in the sibling
     hardware_aliases.json file (see load_manual_aliases()).

The importer (import_seed.py) calls merge_aliases(model_name,
generated) which loads hardware_aliases.json FRESH from disk every
time -- editing that JSON file to add/correct aliases for a device
never requires touching this module or the importer. That's the
whole point of keeping it a separate file per the Sprint 6 spec.

SAFETY RULE -- no ambiguous short aliases: a bare number like "3060"
or "5600" can match a completely unrelated product (Steam's own
requirement text is free-form; "5600" could mean a Ryzen 5 5600 CPU
or plenty of other things depending on context). generate_aliases()
enforces this via _is_safe_alias() -- every candidate must start with
a recognizable letter-prefix (RTX/RX/GTX/UHD/i5/Ryzen/FX/etc), never
a bare digit run. Manual aliases in the JSON file are trusted as-is
(a human deliberately chose them) and are NOT filtered by this guard
-- but the starter file's own docstring/example steers away from
unsafe entries too.
"""

import json
import os
import re

_ALIASES_JSON_PATH = os.path.join(os.path.dirname(__file__), "hardware_aliases.json")

# Brand/manufacturer prefix tokens stripped one at a time from the
# front of the canonical name to produce shorter, still-unambiguous
# candidates. Order matters -- e.g. for "NVIDIA GeForce RTX 3060" we
# want to be able to produce BOTH "GeForce RTX 3060" (strip just
# "NVIDIA") and "RTX 3060" (strip "NVIDIA GeForce") as two separate
# candidates, not just the fully-stripped one.
_STRIPPABLE_PREFIXES = ["NVIDIA", "AMD", "Intel", "GeForce", "Radeon", "Core"]

# A candidate is only safe if its first token contains at least one
# letter -- this is what blocks a bare "3060"/"5600"/"4090" from ever
# being generated, per the explicit spec requirement.
_FIRST_TOKEN_HAS_LETTER_RE = re.compile(r"^[A-Za-z]")


def _is_safe_alias(candidate):
    """False for anything that would be an ambiguous bare-number
    alias. True requires the first word to start with a letter (RTX,
    RX, GTX, UHD, i5, Ryzen, FX, Arc, ...) -- a number-first string
    like "3060" or "5600 X" is rejected outright."""
    candidate = candidate.strip()
    if not candidate:
        return False
    first_token = candidate.split()[0]
    return bool(_FIRST_TOKEN_HAS_LETTER_RE.match(first_token))


def _no_space_variant(candidate):
    """"RTX 3060" -> "RTX3060", "RX 6600 XT" -> "RX6600 XT" (only the
    FIRST space, between the series prefix and its number, is
    collapsed -- collapsing every space in a multi-word name like
    "RX 6600 XT" -> "RX6600XT" is also useful and produced separately
    below; collapsing only the first space avoids mangling suffix
    words like "Ti"/"XT"/"SUPER" into the run)."""
    parts = candidate.split(" ", 1)
    if len(parts) != 2:
        return None
    return parts[0] + parts[1].split(" ", 1)[0] + (
        (" " + parts[1].split(" ", 1)[1]) if " " in parts[1] else ""
    )


def _fully_compressed_variant(candidate):
    """"RX 6600 XT" -> "RX6600XT" -- every space removed. Only
    generated for candidates with 3 or fewer tokens, since compressing
    a long multi-word name rarely produces anything Steam's
    requirement text would actually contain."""
    if len(candidate.split()) > 3:
        return None
    return candidate.replace(" ", "")


def generate_aliases(model_name):
    """The deterministic half of alias generation. Returns a list of
    SAFE candidate aliases derived from model_name -- never includes
    model_name itself (that's already the canonical identifier, no
    need to duplicate it into aliases), never includes a bare-number
    candidate. Never raises -- bad input just yields []."""
    if not model_name or not isinstance(model_name, str):
        return []

    candidates = set()
    remaining = model_name.strip()

    # Progressively strip known brand prefixes off the front,
    # capturing each intermediate form as its own candidate.
    while True:
        stripped_this_round = False
        for prefix in _STRIPPABLE_PREFIXES:
            if remaining.lower().startswith(prefix.lower() + " "):
                remaining = remaining[len(prefix):].strip()
                if remaining and remaining.lower() != model_name.lower():
                    candidates.add(remaining)
                stripped_this_round = True
                break  # restart prefix scan against the newly-shortened string
        if not stripped_this_round:
            break

    # No-space and fully-compressed variants of every stripped form
    # found so far (captures things like "RTX3060", "RX6600XT").
    for candidate in list(candidates):
        for variant_fn in (_no_space_variant, _fully_compressed_variant):
            variant = variant_fn(candidate)
            if variant and variant != candidate:
                candidates.add(variant)

    return sorted(c for c in candidates if _is_safe_alias(c) and c.lower() != model_name.lower())


def load_manual_aliases():
    """Reads hardware_aliases.json fresh off disk every call --
    editing that file never requires touching this function or the
    importer. Returns {} (not an error) if the file is missing,
    empty, or malformed -- a bad manual-overrides file should degrade
    to "no manual aliases this run," never crash the importer."""
    try:
        if not os.path.exists(_ALIASES_JSON_PATH):
            return {}
        with open(_ALIASES_JSON_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return {}
        return {
            k: list(v) for k, v in data.items()
            if isinstance(v, list)
        }
    except Exception:
        return {}


def merge_aliases(model_name, generated_aliases):
    """The importer's actual entry point. Unions generated_aliases
    with any manual entries for this exact model_name from
    hardware_aliases.json -- manual entries are trusted as-is (not
    re-run through _is_safe_alias; a human curated them deliberately)
    and are never lost even if a future generator change would no
    longer produce the same candidates. Case-sensitive exact match on
    model_name against the JSON file's keys -- keeps this predictable
    rather than doing fuzzy matching that could silently attach the
    wrong aliases to the wrong device.

    Returns a deduped, sorted list. Never raises.
    """
    try:
        manual = load_manual_aliases().get(model_name, [])
        merged = set(generated_aliases or []) | set(manual)
        return sorted(merged)
    except Exception:
        return list(generated_aliases or [])