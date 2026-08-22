"""
VERIFIED POTATO DATABASE — loader for
data/potato/verified_potato_games.json, the researched, authoritative
source of truth for Nimlyx's Potato ecosystem (🥔/🔧/💀).

WHY THIS EXISTS (replacing dynamic Steam-requirement discovery)
-------------------------------------------------------------------
The previous architecture tried to DISCOVER Potato games by pulling a
Steam candidate pool, parsing each game's officially published
minimum/recommended requirements, and running those through a
gap-ratio classifier (services/hardware/potato_classifier.py). That
approach has a real, structural ceiling: a game's official Steam
requirements are a legal/marketing floor set by the publisher, not a
measurement of what the engine actually does on real low-end
hardware. Games like Dying Light, Fallout 4, and Skyrim Special
Edition are well-documented (YouTube benchmarks, Steam community
threads) as genuinely playable on hardware their official minimum
spec would suggest is hopeless — and the reverse also happens, where
a game's minimum spec looks reasonable but real testing shows it
struggling badly. No amount of ratio-threshold tuning against
official spec text can close that gap, because the signal the
classifier depends on (Steam's published spec) simply isn't measuring
the thing the Potato ecosystem promises ("how far can we push weak
hardware").

This module is the fix: it loads a researched dataset where each
entry's tier was determined by real-world evidence (see the
`real_world_evidence` block on every record — tested hardware, FPS
range, settings used, source), not by reading Steam's spec sheet.

WHAT THIS MODULE DOES NOT DO
-------------------------------
- Does not fetch anything from Steam. Steam metadata (art, price,
  store link, current requirements text for display/context) is a
  SEPARATE enrichment step -- see services/hardware/verified_potato_pool.py.
- Does not re-run or second-guess the dynamic classifier
  (services/hardware/potato_classifier.py) against these entries.
  That classifier is kept in the codebase for future candidate
  research/validation (see its own module docstring), but its output
  is never allowed to override a verified tier from this file.
- Does not invent or guess at any field. Every field this loader reads
  (steam_app_id, game_name, classification, confidence,
  real_world_evidence, steam_minimum_requirements,
  steam_recommended_requirements) was verified present on all 110
  records in the source JSON before this loader was written -- a
  record missing one of the required fields is logged and skipped,
  never patched with a fabricated default.

SCHEMA (as verified against the actual JSON, not assumed)
-------------------------------------------------------------
Top-level: a JSON array of objects, each shaped:
    {
      "steam_app_id": "220" | "N/A",
      "game_name": "Half-Life 2",
      "steam_minimum_requirements": {"gpu": ..., "cpu": ..., "ram": ...},
      "steam_recommended_requirements": {"gpu": ..., "cpu": ..., "ram": ...},
      "real_world_evidence": {
          "tested_gpu": ..., "tested_cpu": ..., "tested_ram": ...,
          "fps_range": ..., "average_fps": ..., "resolution": ...,
          "graphics_settings": ..., "special_tweaks": ...,
          "launch_parameters": ..., "config_modifications": ...,
          "source_url": ..., "source_type": ..., "evidence_quality": ...,
          "notes": ...
      },
      "classification": "Potato Friendly" | "Potato + Tweaks" |
                         "Extreme Tweaks" | "Excluded",
      "confidence": "High" | "Medium"
    }

`classification` maps to this codebase's existing tier vocabulary via
CLASSIFICATION_TO_TIER below -- "Excluded" has no tier (deliberately:
these are games the research explicitly determined do NOT belong in
the Potato ecosystem, e.g. The Witcher 3 at 5-15 FPS sub-720p on
minimum settings -- kept in the dataset as documented negative
evidence, not surfaced on any homepage row).

"steam_app_id": "N/A" means the title isn't sold on Steam at all
(checked against this exact dataset: Need for Speed: Most Wanted
(2005)/Carbon, Valorant, Overwatch 2, League of Legends, Minecraft
Java Edition, Roblox). Since every downstream card needs real Steam
metadata (art/price/store link) that can only come from a Steam app
id, these entries are excluded from `iter_renderable_entries()` --
but NOT dropped from the loaded dataset entirely, so a maintainer
inspecting `load_verified_potato_games()` can still see exactly which
researched titles exist and why they never render.
"""

import json
import logging
import os

logger = logging.getLogger(__name__)

_DB_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "data", "potato", "verified_potato_games.json")

CLASSIFICATION_TO_TIER = {
    "Potato Friendly": "friendly",
    "Potato + Tweaks": "tweaks",
    "Extreme Tweaks": "extreme",
    # "Excluded" is intentionally absent -- those entries never map to
    # a tier (see module docstring).
}

REQUIRED_FIELDS = (
    "steam_app_id",
    "game_name",
    "classification",
    "confidence",
    "real_world_evidence",
    "steam_minimum_requirements",
    "steam_recommended_requirements",
)


class VerifiedPotatoEntry:
    """One researched record. `tier` is None for "Excluded" entries or
    any classification string this loader doesn't recognize (logged,
    never guessed at) -- callers filter on `tier is not None` rather
    than re-deriving it."""

    __slots__ = (
        "app_id", "name", "tier", "raw_classification", "confidence",
        "evidence", "minimum_requirements", "recommended_requirements",
    )

    def __init__(self, app_id, name, tier, raw_classification, confidence,
                 evidence, minimum_requirements, recommended_requirements):
        self.app_id = app_id  # int or None (None == "N/A", not sold on Steam)
        self.name = name
        self.tier = tier
        self.raw_classification = raw_classification
        self.confidence = confidence
        self.evidence = evidence
        self.minimum_requirements = minimum_requirements
        self.recommended_requirements = recommended_requirements

    def __repr__(self):
        return f"<VerifiedPotatoEntry {self.name!r} app_id={self.app_id} tier={self.tier!r}>"


def _parse_app_id(raw_value):
    """"N/A" (or anything else non-numeric) -> None. Never guesses a
    number out of a malformed string."""
    if raw_value is None:
        return None
    text = str(raw_value).strip()
    if not text.isdigit():
        return None
    return int(text)


def _parse_entry(record, index):
    missing = [field for field in REQUIRED_FIELDS if field not in record]
    if missing:
        logger.warning(
            "Verified Potato DB record #%d missing required field(s) %s -- skipped, not guessed.",
            index, missing,
        )
        return None

    name = (record.get("game_name") or "").strip()
    if not name:
        logger.warning("Verified Potato DB record #%d has an empty game_name -- skipped.", index)
        return None

    raw_classification = record.get("classification")
    tier = CLASSIFICATION_TO_TIER.get(raw_classification)
    if tier is None and raw_classification != "Excluded":
        logger.warning(
            "Verified Potato DB record #%d (%s) has an unrecognized classification %r -- "
            "no tier assumed, entry kept but will never render.",
            index, name, raw_classification,
        )

    return VerifiedPotatoEntry(
        app_id=_parse_app_id(record.get("steam_app_id")),
        name=name,
        tier=tier,
        raw_classification=raw_classification,
        confidence=record.get("confidence"),
        evidence=record.get("real_world_evidence") or {},
        minimum_requirements=record.get("steam_minimum_requirements") or {},
        recommended_requirements=record.get("steam_recommended_requirements") or {},
    )


def load_verified_potato_games(path=None):
    """Loads and parses every record in the JSON. Never raises for a
    single malformed record (logged + skipped instead, per
    REQUIRED_FIELDS above); DOES raise if the file itself is missing
    or isn't valid JSON at all -- a missing/corrupt database file is a
    deploy-time problem that should fail loudly, not silently degrade
    into an empty Potato ecosystem.

    Duplicate app ids (test requirement: "handled safely") are kept
    as separate entries here -- deduplication happens one layer up,
    in verified_potato_pool.py, where it belongs alongside the Steam
    enrichment step (that's also where "which duplicate wins" is a
    meaningful question; at the raw-load layer, surfacing every
    record un-deduped is the more honest, debuggable default)."""
    db_path = path or _DB_PATH
    with open(db_path, "r", encoding="utf-8") as f:
        raw_records = json.load(f)

    entries = []
    for index, record in enumerate(raw_records):
        entry = _parse_entry(record, index)
        if entry is not None:
            entries.append(entry)
    return entries


def iter_renderable_entries(entries):
    """Entries that CAN actually appear on a homepage card: have a
    real Steam app id (excludes "N/A" -- not sold on Steam at all) and
    a recognized tier (excludes "Excluded" and any unrecognized
    classification string)."""
    for entry in entries:
        if entry.app_id is not None and entry.tier is not None:
            yield entry


def get_games_by_tier(entries, tier):
    return [e for e in iter_renderable_entries(entries) if e.tier == tier]
