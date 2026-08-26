"""
Tests for services/hardware/verified_potato_pool.py -- turns the
verified database into real, homepage-ready candidates via Steam
enrichment, with a static test database (never the live JSON file, so
these tests don't depend on its current contents) and a mocked
enrich_pool() (never real Steam calls).

Covers the deliverable's required regression list:
  8. Steam search ranking does not affect Potato discovery -- there is
     no search here at all; games are looked up by App ID directly.
  6 (end-to-end). A game with demanding official Steam requirements
     still appears in its VERIFIED tier -- enrich_pool() here returns
     real (mocked) pc_requirements text that would fail the dynamic
     classifier, and the resulting candidate still lands in the
     verified tier regardless.
  11. Missing Steam metadata does not erase the verified
      classification -- covered via the stale-cache-fallback path.
  10 (pool layer). Duplicate App IDs across tiers are handled safely
     -- first tier encountered wins, not a crash or a silent
     overwrite that could invert a classification.
  9. Load More can access games beyond the first 14 -- covered
     structurally: this module has no page-size concept at all, it
     returns every renderable verified game; the 14-cap only exists at
     the call site (routes/pages.py), tested there.
"""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import services.hardware.verified_potato_pool as pool_mod  # noqa: E402
from services.hardware.verified_potato_db import VerifiedPotatoEntry  # noqa: E402


def _entry(app_id, name, tier):
    return VerifiedPotatoEntry(
        app_id=app_id, name=name, tier=tier, raw_classification=tier, confidence="High",
        evidence={}, minimum_requirements={}, recommended_requirements={},
    )


def _fake_enrich_factory(fail_ids=frozenset()):
    """Simulates enrich_pool(): drops any row whose id is in
    `fail_ids` (simulating a Steam appdetails failure), enriches the
    rest with the DEMANDING pc_requirements text below -- deliberately
    something the dynamic classifier would reject or push to Extreme,
    to prove tier assignment here never re-derives from it."""
    demanding_requirements = {
        "minimum": (
            "<strong>Minimum:</strong><ul class='bb_ul'>"
            "<li><strong>Processor:</strong> Intel Core i9-9900K<br></li>"
            "<li><strong>Memory:</strong> 32 GB RAM<br></li>"
            "<li><strong>Graphics:</strong> NVIDIA GeForce RTX 3080<br></li>"
            "</ul>"
        )
    }

    def _fake_enrich(rows, cc="US"):
        return [
            {
                "steam_appid": row["id"], "name": row["name"],
                "header_image": f"https://cdn.example/{row['id']}.jpg",
                "price_overview": {"final": 999, "discount_percent": 0, "currency": "USD"},
                "is_free": False, "pc_requirements": demanding_requirements,
            }
            for row in rows if row["id"] not in fail_ids
        ]

    return _fake_enrich


class TestFormatEvidenceForCard(unittest.TestCase):
    """format_evidence_for_card() -- the Potato page's "why this game
    is in this tier" summary. Never fabricates: placeholder values the
    research JSON itself uses to mean "unknown"/"none needed" must be
    omitted, not displayed as if they were real findings."""

    def test_real_dying_light_evidence_produces_expected_summary(self):
        evidence = {
            "average_fps": "22", "fps_range": "15-30", "resolution": "720p or lower",
            "graphics_settings": "Lowest possible", "special_tweaks": "Low-End Mods from Nexus Mods",
            "config_modifications": "Disable shadows via config file", "evidence_quality": "High",
            "notes": "Struggles heavily on native settings.",
        }
        result = pool_mod.format_evidence_for_card(evidence)
        self.assertEqual(result["summary"], "22 FPS · 720p or lower · Lowest possible")
        self.assertEqual(result["tweak"], "Low-End Mods from Nexus Mods")
        self.assertEqual(result["quality"], "High")

    def test_no_tweak_needed_produces_no_tweak_field(self):
        evidence = {
            "average_fps": "60", "resolution": "1080p", "graphics_settings": "Native",
            "special_tweaks": "None", "config_modifications": "None",
        }
        result = pool_mod.format_evidence_for_card(evidence)
        self.assertIsNone(result["tweak"])
        self.assertEqual(result["summary"], "60 FPS · 1080p · Native")

    def test_placeholder_values_never_shown(self):
        evidence = {"average_fps": "Unknown", "resolution": "N/A", "graphics_settings": "", "tested_ram": "Unknown"}
        result = pool_mod.format_evidence_for_card(evidence)
        self.assertIsNone(result["summary"])

    def test_missing_evidence_block_does_not_raise(self):
        result = pool_mod.format_evidence_for_card(None)
        self.assertIsNone(result["summary"])
        self.assertIsNone(result["tweak"])

    def test_fps_range_used_when_average_fps_missing(self):
        result = pool_mod.format_evidence_for_card({"fps_range": "15-30"})
        self.assertEqual(result["summary"], "15-30 FPS")


class TestBuildTierCandidates(unittest.TestCase):
    """Exercises _build_tier_candidates() directly -- the pure
    enrich-and-group step, independent of the cache."""

    def setUp(self):
        self.entries_patch = patch.object(
            pool_mod, "_ALL_ENTRIES",
            [
                _entry(1, "Friendly Game", "friendly"),
                _entry(2, "Tweaks Game", "tweaks"),
                _entry(3, "Extreme Game", "extreme"),
            ],
        )
        self.entries_patch.start()
        self.addCleanup(self.entries_patch.stop)

    def test_verified_tier_wins_regardless_of_demanding_steam_requirements(self):
        """Requirement 6, end-to-end: the mocked enrichment here
        returns a pc_requirements block an RTX 3080 / i9-9900K / 32GB
        game -- something the dynamic classifier would classify as
        Excluded, not Extreme. The verified database's tier must still
        be what determines the bucket."""
        with patch.object(pool_mod, "enrich_pool", _fake_enrich_factory()):
            tiers = pool_mod._build_tier_candidates("US", {})

        self.assertEqual([c.name for c in tiers["friendly"]], ["Friendly Game"])
        self.assertEqual([c.name for c in tiers["tweaks"]], ["Tweaks Game"])
        self.assertEqual([c.name for c in tiers["extreme"]], ["Extreme Game"])

    def test_evidence_reaches_the_built_candidates_game_dict(self):
        """The Potato page's evidence display (templates/potato.html,
        static/js/potato.js) reads game.verified_evidence off the
        candidate's game dict via to_homepage_card() -- confirm it's
        actually attached, not just computed and discarded."""
        entries_with_evidence = [
            VerifiedPotatoEntry(
                app_id=1, name="Evidenced Game", tier="extreme", raw_classification="Extreme Tweaks",
                confidence="High", evidence={"average_fps": "22", "resolution": "720p"},
                minimum_requirements={}, recommended_requirements={},
            ),
        ]
        with patch.object(pool_mod, "_ALL_ENTRIES", entries_with_evidence), \
             patch.object(pool_mod, "enrich_pool", _fake_enrich_factory()):
            tiers = pool_mod._build_tier_candidates("US", {})

        candidate = tiers["extreme"][0]
        self.assertIn("verified_evidence", candidate.game)
        self.assertEqual(candidate.game["verified_evidence"]["summary"], "22 FPS · 720p")

    def test_app_id_is_used_directly_no_search_involved(self):
        """Requirement 8: Steam search ranking cannot affect this at
        all -- prove it by asserting enrich_pool() is called with rows
        built straight from the entries' own app_id/name, never routed
        through any search function."""
        captured = {}

        def _capturing_enrich(rows, cc="US"):
            captured["rows"] = rows
            return _fake_enrich_factory()(rows, cc)

        with patch.object(pool_mod, "enrich_pool", _capturing_enrich):
            pool_mod._build_tier_candidates("US", {})

        ids_passed = {row["id"] for row in captured["rows"]}
        self.assertEqual(ids_passed, {1, 2, 3})

    def test_stale_metadata_used_when_steam_enrichment_fails(self):
        """Requirement 11: missing/failed Steam metadata must not
        erase the verified classification -- a game that fails to
        enrich this round falls back to its previous cached card."""
        from services.hero.candidate import HeroCandidate

        previous = {
            3: HeroCandidate(
                game={"steam_appid": 3, "name": "Extreme Game (STALE)", "header_image": "x.jpg",
                      "price_overview": {}, "is_free": False, "pc_requirements": {}},
                category="verified_potato", confidence=1.0, insight="", why_it_matters="",
            )
        }

        with patch.object(pool_mod, "enrich_pool", _fake_enrich_factory(fail_ids={3})):
            tiers = pool_mod._build_tier_candidates("US", previous)

        self.assertEqual(len(tiers["extreme"]), 1)
        self.assertEqual(tiers["extreme"][0].name, "Extreme Game (STALE)")

    def test_never_enriched_game_is_dropped_not_fabricated(self):
        """A game that fails enrichment with NO previous cache to fall
        back on has no real Steam data at all -- correctly absent
        rather than rendered with fabricated placeholder data."""
        with patch.object(pool_mod, "enrich_pool", _fake_enrich_factory(fail_ids={3})):
            tiers = pool_mod._build_tier_candidates("US", {})

        self.assertEqual(tiers["extreme"], [])
        self.assertEqual(len(tiers["friendly"]), 1)
        self.assertEqual(len(tiers["tweaks"]), 1)


class TestDuplicateAppIdsAcrossTiers(unittest.TestCase):
    """Requirement 10, pool layer: if the SAME app id somehow appears
    in two different tiers (a research data error), the pool must not
    crash, must not silently double-count the game, and must not let
    the second occurrence invert the first tier's classification."""

    def test_duplicate_app_id_across_tiers_keeps_first_tier_only(self):
        with patch.object(
            pool_mod, "_ALL_ENTRIES",
            [
                _entry(99, "Contested Game", "friendly"),
                _entry(99, "Contested Game", "extreme"),
            ],
        ), patch.object(pool_mod, "enrich_pool", _fake_enrich_factory()):
            tiers = pool_mod._build_tier_candidates("US", {})

        self.assertEqual(len(tiers["friendly"]), 1)
        self.assertEqual(len(tiers["extreme"]), 0)


class TestGetVerifiedPotatoTiersCaching(unittest.TestCase):
    """The public entry point's three-outcome cache contract: cold
    start returns empty immediately (never blocks the request), a warm
    cache returns real data, and a stale cache still returns the old
    data immediately while a refresh happens in the background."""

    def setUp(self):
        pool_mod._CACHE.clear()
        pool_mod._BUILD_IN_PROGRESS.clear()
        self.entries_patch = patch.object(
            pool_mod, "_ALL_ENTRIES", [_entry(1, "Friendly Game", "friendly")]
        )
        self.entries_patch.start()
        self.addCleanup(self.entries_patch.stop)
        self.addCleanup(pool_mod._CACHE.clear)
        self.addCleanup(pool_mod._BUILD_IN_PROGRESS.clear)

    def test_cold_start_returns_empty_tiers_and_never_raises(self):
        with patch.object(pool_mod, "enrich_pool", _fake_enrich_factory()):
            tiers = pool_mod.get_verified_potato_tiers("US")
        self.assertEqual(tiers, {"friendly": [], "tweaks": [], "extreme": []})

    def test_warm_cache_returns_populated_data(self):
        with patch.object(pool_mod, "enrich_pool", _fake_enrich_factory()):
            pool_mod._rebuild_cache("US")  # synchronous, bypassing the background thread for the test
            tiers = pool_mod.get_verified_potato_tiers("US")
        self.assertEqual([c.name for c in tiers["friendly"]], ["Friendly Game"])


if __name__ == "__main__":
    unittest.main()
