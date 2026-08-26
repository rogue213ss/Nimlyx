"""
Tests for services/hardware/verified_potato_db.py -- the loader/parser
for the researched, authoritative Potato database
(data/potato/verified_potato_games.json).

Covers the deliverable's required regression list:
  1. JSON loads successfully.
  2. All valid researched games are recognized.
  3-5. Friendly/Tweaks/Extreme classification mapping is correct.
  6. A game with demanding official Steam requirements can still be
     "friendly"/"tweaks"/"extreme" per the DATABASE -- i.e. this
     loader never looks at steam_minimum_requirements to decide tier,
     only at the `classification` field. (The end-to-end version of
     this claim -- Dying Light specifically overriding what the
     dynamic classifier would say -- is covered in
     test_verified_potato_pool.py, since that's where Steam data and
     the verified tier actually meet.)
  7. Missing RAM does not remove a verified game.
  10. Duplicate App IDs are handled safely (this file: loader keeps
      both records rather than crashing or silently merging; the pool
      layer is where "which one wins" is decided -- see
      test_verified_potato_pool.py).

Also covers the "IMPORTANT SAFETY CHECK" requirement directly: this
loader must not assume field names or invent missing data -- a
malformed record is skipped and logged, never guessed at.
"""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.hardware.verified_potato_db import (  # noqa: E402
    CLASSIFICATION_TO_TIER,
    get_games_by_tier,
    iter_renderable_entries,
    load_verified_potato_games,
)


def _write_temp_db(records):
    f = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8")
    json.dump(records, f)
    f.close()
    return f.name


def _valid_record(app_id="220", name="Half-Life 2", classification="Potato Friendly", ram="4 GB RAM"):
    return {
        "steam_app_id": app_id,
        "game_name": name,
        "steam_minimum_requirements": {"gpu": "NVIDIA GeForce 6600", "cpu": "1.7 GHz", "ram": ram},
        "steam_recommended_requirements": {"gpu": "NVIDIA GeForce 7600", "cpu": "3.0 GHz", "ram": "1 GB RAM"},
        "real_world_evidence": {
            "tested_gpu": "Intel HD Graphics 4400", "fps_range": "45-60", "source_url": "https://example.com",
        },
        "classification": classification,
        "confidence": "High",
    }


class TestLoadingTheRealDatabase(unittest.TestCase):
    """Sanity checks against the actual shipped JSON file (requirement
    1: "JSON loads successfully"), not a synthetic fixture."""

    def test_real_database_loads_without_raising(self):
        entries = load_verified_potato_games()
        self.assertGreater(len(entries), 0)

    def test_real_database_has_all_three_tiers_represented(self):
        entries = load_verified_potato_games()
        tiers_present = {e.tier for e in entries if e.tier is not None}
        self.assertEqual(tiers_present, {"friendly", "tweaks", "extreme"})

    def test_real_database_dying_light_is_extreme(self):
        """Requirement 6, made concrete with the flagship example from
        the task: Dying Light's real minimum GPU (per this exact JSON)
        looks demanding, but its `classification` field is
        authoritative regardless -- this loader never consults
        steam_minimum_requirements to decide tier."""
        entries = load_verified_potato_games()
        dying_light = next((e for e in entries if e.name == "Dying Light"), None)
        self.assertIsNotNone(dying_light)
        self.assertEqual(dying_light.tier, "extreme")


class TestClassificationMapping(unittest.TestCase):
    """Requirements 3-5: Friendly/Tweaks/Extreme games map to the
    right internal tier key, and "Excluded" maps to no tier at all."""

    def test_potato_friendly_maps_to_friendly(self):
        self.assertEqual(CLASSIFICATION_TO_TIER["Potato Friendly"], "friendly")

    def test_potato_tweaks_maps_to_tweaks(self):
        self.assertEqual(CLASSIFICATION_TO_TIER["Potato + Tweaks"], "tweaks")

    def test_extreme_tweaks_maps_to_extreme(self):
        self.assertEqual(CLASSIFICATION_TO_TIER["Extreme Tweaks"], "extreme")

    def test_excluded_maps_to_no_tier(self):
        self.assertNotIn("Excluded", CLASSIFICATION_TO_TIER)

    def test_end_to_end_tier_assignment_from_a_temp_db(self):
        path = _write_temp_db([
            _valid_record("1", "Friendly Game", "Potato Friendly"),
            _valid_record("2", "Tweaks Game", "Potato + Tweaks"),
            _valid_record("3", "Extreme Game", "Extreme Tweaks"),
            _valid_record("4", "Excluded Game", "Excluded"),
        ])
        try:
            entries = load_verified_potato_games(path)
            self.assertEqual(get_games_by_tier(entries, "friendly")[0].name, "Friendly Game")
            self.assertEqual(get_games_by_tier(entries, "tweaks")[0].name, "Tweaks Game")
            self.assertEqual(get_games_by_tier(entries, "extreme")[0].name, "Extreme Game")
            excluded = next(e for e in entries if e.name == "Excluded Game")
            self.assertIsNone(excluded.tier)
            # Excluded from every tier query, but NOT dropped from the
            # loaded dataset entirely (still inspectable).
            all_names = {e.name for e in entries}
            self.assertIn("Excluded Game", all_names)
        finally:
            os.unlink(path)


class TestMissingRamNeverRemovesAGame(unittest.TestCase):
    """Requirement 7: RAM is secondary evidence -- missing/null RAM
    must not exclude a verified game from its tier."""

    def test_null_ram_still_renders(self):
        record = _valid_record("500", "No RAM Listed", "Potato Friendly")
        record["steam_minimum_requirements"]["ram"] = None
        path = _write_temp_db([record])
        try:
            entries = load_verified_potato_games(path)
            self.assertEqual(len(entries), 1)
            self.assertEqual(entries[0].tier, "friendly")
            self.assertIn(entries[0], list(iter_renderable_entries(entries)))
        finally:
            os.unlink(path)

    def test_missing_ram_key_entirely_still_renders(self):
        record = _valid_record("501", "No RAM Key", "Potato Friendly")
        del record["steam_minimum_requirements"]["ram"]
        path = _write_temp_db([record])
        try:
            entries = load_verified_potato_games(path)
            self.assertEqual(len(entries), 1)
            self.assertEqual(entries[0].tier, "friendly")
        finally:
            os.unlink(path)


class TestAppIdParsing(unittest.TestCase):
    def test_na_app_id_parses_to_none(self):
        path = _write_temp_db([_valid_record("N/A", "Not On Steam", "Potato Friendly")])
        try:
            entries = load_verified_potato_games(path)
            self.assertIsNone(entries[0].app_id)
        finally:
            os.unlink(path)

    def test_na_app_id_is_excluded_from_renderable_entries(self):
        """A game not sold on Steam can never get real Steam metadata
        (art/price/store link), so it's kept in the loaded dataset but
        never yielded by iter_renderable_entries()."""
        path = _write_temp_db([
            _valid_record("N/A", "Not On Steam", "Potato Friendly"),
            _valid_record("220", "On Steam", "Potato Friendly"),
        ])
        try:
            entries = load_verified_potato_games(path)
            renderable_names = {e.name for e in iter_renderable_entries(entries)}
            self.assertNotIn("Not On Steam", renderable_names)
            self.assertIn("On Steam", renderable_names)
        finally:
            os.unlink(path)

    def test_numeric_string_app_id_parses_to_int(self):
        path = _write_temp_db([_valid_record("239140", "Dying Light", "Extreme Tweaks")])
        try:
            entries = load_verified_potato_games(path)
            self.assertEqual(entries[0].app_id, 239140)
            self.assertIsInstance(entries[0].app_id, int)
        finally:
            os.unlink(path)


class TestDuplicateAppIdsAreHandledSafely(unittest.TestCase):
    """Requirement 10. The loader itself doesn't dedupe (see its
    docstring for why: dedup belongs at the enrichment layer, where
    "which duplicate wins" is a meaningful question) -- but it must
    never crash or silently corrupt data when the same app id appears
    twice."""

    def test_loading_a_duplicate_app_id_does_not_raise(self):
        path = _write_temp_db([
            _valid_record("220", "Half-Life 2", "Potato Friendly"),
            _valid_record("220", "Half-Life 2 (dup entry)", "Potato + Tweaks"),
        ])
        try:
            entries = load_verified_potato_games(path)  # must not raise
            self.assertEqual(len(entries), 2)
            self.assertEqual({e.app_id for e in entries}, {220})
        finally:
            os.unlink(path)


class TestMalformedRecordsAreSkippedNotGuessed(unittest.TestCase):
    """The 'IMPORTANT SAFETY CHECK' requirement: never assume field
    names, never invent missing data. A malformed record is dropped
    (logged), and every OTHER valid record in the same file still
    loads correctly."""

    def test_record_missing_required_field_is_skipped(self):
        good = _valid_record("220", "Good Game", "Potato Friendly")
        broken = _valid_record("221", "Broken Game", "Potato Friendly")
        del broken["real_world_evidence"]
        path = _write_temp_db([good, broken])
        try:
            entries = load_verified_potato_games(path)
            names = {e.name for e in entries}
            self.assertIn("Good Game", names)
            self.assertNotIn("Broken Game", names)
        finally:
            os.unlink(path)

    def test_record_with_empty_name_is_skipped(self):
        broken = _valid_record("222", "", "Potato Friendly")
        path = _write_temp_db([broken])
        try:
            entries = load_verified_potato_games(path)
            self.assertEqual(entries, [])
        finally:
            os.unlink(path)

    def test_unrecognized_classification_gets_no_tier_but_is_not_dropped(self):
        """A future typo/new category in the research data should
        never crash the site or silently get mapped to a guessed
        tier -- it just never renders anywhere, same as "Excluded"."""
        record = _valid_record("223", "Weird Classification Game", "Somewhat Potato-ish")
        path = _write_temp_db([record])
        try:
            entries = load_verified_potato_games(path)
            self.assertEqual(len(entries), 1)
            self.assertIsNone(entries[0].tier)
            self.assertEqual(entries[0].raw_classification, "Somewhat Potato-ish")
        finally:
            os.unlink(path)


if __name__ == "__main__":
    unittest.main()
