"""
Regression tests for services/hero/potato_pool.py's candidate
sourcing -- specifically the $10/$20/$40 permanent-price sweep bands
that determine which games are even ELIGIBLE to be classified into
the Potato ecosystem (🥔/🔧/💀), before the classifier ever runs.

Context: a research/validation pass (docs/potato_research_matrix.md)
confirmed the classifier itself was already well-calibrated, but that
almost none of the real-world 💀 Extreme candidates it validated
against (Dark Souls III, Dragon Age: Inquisition, The Witcher 3,
Skyrim Special Edition) could ever appear on the live homepage, because
they permanently retail well above the pool's old $10/$20 ceiling.
This is a sourcing gap, not a classifier bug -- these tests guard the
fix (the added $40 band) without touching the classifier itself.
"""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import services.hero.potato_pool as potato_pool  # noqa: E402


class TestBudgetBandsCoverage(unittest.TestCase):
    def test_three_bands_configured_matching_discover_verified_tiers(self):
        """$10 / $20 / $40 -- reusing Discover's own verified
        BUDGET_MAX_PRICE_CENTS tiers (steam.py) rather than inventing
        new price cutoffs."""
        self.assertEqual(potato_pool.BUDGET_BANDS_CENTS, (1000, 2000, 4000))

    def test_forty_dollar_band_is_wide_enough_for_real_extreme_candidates(self):
        """Sanity check against the real prices researched in
        docs/potato_research_matrix.md: Dying Light (~$20-30, already
        surfaced pre-fix) and Skyrim Special Edition (~$40) should now
        fall within the sweep; a $60 full-price modern AAA title like
        Cyberpunk 2077 correctly still falls outside it (that's the
        hero pool's job, not the budget-leaning Potato pool's)."""
        self.assertLessEqual(3999, max(potato_pool.BUDGET_BANDS_CENTS))
        self.assertNotIn(6000, potato_pool.BUDGET_BANDS_CENTS)


class TestBuildPotatoScrapePool(unittest.TestCase):
    def _fake_sweep(self, max_price_cents, count=100, cc="US"):
        return [
            {"id": f"{max_price_cents}-{i}", "name": f"Game {max_price_cents}-{i}"}
            for i in range(2)
        ]

    def test_all_three_bands_are_swept_and_labeled(self):
        with patch.object(potato_pool, "fetch_budget_catalog_sweep", side_effect=self._fake_sweep):
            pool = potato_pool.build_potato_scrape_pool(cc="US")

        sources_seen = {source for game in pool for source in game["sources"]}
        self.assertEqual(
            sources_seen,
            {"budget_under_10", "budget_under_20", "budget_under_40"},
        )
        # 2 fake games per band x 3 bands, all with distinct ids -> no
        # dedup collisions expected in this fake data.
        self.assertEqual(len(pool), 6)

    def test_a_forty_dollar_only_game_is_still_included(self):
        """A game that only appears in the new $40 sweep (i.e. it's
        priced $20.01-$40, so the older $10/$20 bands never would have
        surfaced it) must still make it into the pool -- this is the
        entire point of the fix."""
        def sweep(max_price_cents, count=100, cc="US"):
            if max_price_cents == 4000:
                return [{"id": "999", "name": "Dark Souls III-ish Test Game"}]
            return []

        with patch.object(potato_pool, "fetch_budget_catalog_sweep", side_effect=sweep):
            pool = potato_pool.build_potato_scrape_pool(cc="US")

        ids = {game["id"] for game in pool}
        self.assertIn("999", ids)

    def test_one_band_failing_does_not_drop_the_others(self):
        """Matches the existing per-band try/except: a Steam hiccup on
        one band (e.g. the new $40 sweep) must not take down the
        $10/$20 bands that already worked."""
        def sweep(max_price_cents, count=100, cc="US"):
            if max_price_cents == 4000:
                raise ConnectionError("Steam unreachable")
            return [{"id": f"{max_price_cents}-ok", "name": "Fine Game"}]

        with patch.object(potato_pool, "fetch_budget_catalog_sweep", side_effect=sweep):
            pool = potato_pool.build_potato_scrape_pool(cc="US")

        ids = {game["id"] for game in pool}
        self.assertEqual(ids, {"1000-ok", "2000-ok"})

    def test_dedupes_a_game_appearing_in_multiple_bands(self):
        """A cheaper-than-$10 game legitimately shows up in every band
        (each sweep is <=, not a strict range) -- must be deduped by
        app id with sources merged, not triplicated."""
        def sweep(max_price_cents, count=100, cc="US"):
            return [{"id": "555", "name": "Cheap Classic"}]

        with patch.object(potato_pool, "fetch_budget_catalog_sweep", side_effect=sweep):
            pool = potato_pool.build_potato_scrape_pool(cc="US")

        self.assertEqual(len(pool), 1)
        self.assertEqual(
            set(pool[0]["sources"]),
            {"budget_under_10", "budget_under_20", "budget_under_40"},
        )


if __name__ == "__main__":
    unittest.main()
