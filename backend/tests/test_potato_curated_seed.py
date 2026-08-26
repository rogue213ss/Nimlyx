"""
Regression tests for services/hero/potato_curated_seed.py -- the
guaranteed-included candidate list resolved from the user's researched
game names.

Per the module's own contract (see its docstring), what's guarded here
is:
  - names resolve against REAL Steam search, never a hardcoded app id
  - a name that doesn't exist on Steam is silently skipped, not faked
  - one failed lookup doesn't take the rest of the list down
  - the curated pool feeds the SAME classify_potato_tier_all()
    pipeline as every other source -- no tier is ever assigned here

Nothing in this file asserts what tier any specific game lands in --
that's real Steam data's job, checked elsewhere
(test_potato_classifier.py / test_potato_ecosystem_research.py).

NOTE (verified-database migration): this module's build_curated_seed_pool()
is unchanged and still fully tested below. The one thing removed from
this file is a test of `_get_merged_hardware_pool()` in
routes/potato.py -- that function no longer exists there. The /potato
page now sources exclusively from the verified database
(services/hardware/verified_potato_pool.py); routes/pages.py's home()
still calls `_get_curated_seed_pool()` directly for the Integrated GPU
section (moved there from routes/potato.py -- see routes/pages.py),
but there's no longer a three-way merge to test since /potato doesn't
merge dynamic pools at all any more.
"""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import services.hero.potato_curated_seed as seed_mod  # noqa: E402


def _fake_search_factory(unavailable=()):
    """Simulates fetch_search_by_term(): returns a genuine-looking
    result for any name not in `unavailable`, mirroring how a real
    Steam-unlisted title (e.g. Diablo III, Minecraft Java) returns an
    empty result set rather than an error."""
    def fake_search(term, count=5, cc="US"):
        if term in unavailable:
            return []
        return [{"id": f"id-{term}", "name": term}]
    return fake_search


def _fake_enrich(pool, cc="US"):
    """Simulates enrich_pool(): attaches a resolvable minimum GPU so
    downstream classification has something real to work with."""
    out = []
    for g in pool:
        g2 = dict(g)
        g2["pc_requirements"] = {
            "minimum": "<li><strong>Graphics:</strong> Intel HD Graphics 2000<br></li>"
        }
        out.append(g2)
    return out


class TestCuratedSeedNames(unittest.TestCase):
    def test_no_duplicate_names_in_the_final_list(self):
        """CURATED_SEED_NAMES is a deduped union of all three of the
        user's original lists -- a title appearing in more than one
        tier list (e.g. Far Cry 4, Dragon Age: Inquisition, Valheim)
        must only appear once here."""
        self.assertEqual(len(seed_mod.CURATED_SEED_NAMES), len(set(seed_mod.CURATED_SEED_NAMES)))

    def test_known_steam_unavailable_titles_are_still_listed(self):
        """Diablo III and Minecraft Java are deliberately kept in the
        list (flagged in the module docstring) rather than quietly
        removed, so it's visible *why* they never resolve."""
        self.assertIn("Diablo III", seed_mod.CURATED_SEED_NAMES)
        self.assertIn("Minecraft Java", seed_mod.CURATED_SEED_NAMES)


class TestBuildCuratedSeedPool(unittest.TestCase):
    def test_resolves_names_to_real_search_results_not_hardcoded_ids(self):
        with patch.object(seed_mod, "fetch_search_by_term", side_effect=_fake_search_factory()), \
             patch.object(seed_mod, "enrich_pool", side_effect=_fake_enrich):
            pool = seed_mod.build_curated_seed_pool(cc="US")

        self.assertEqual(len(pool), len(seed_mod.CURATED_SEED_NAMES))
        self.assertTrue(all(c.category == "potato_curated_seed" for c in pool))

    def test_steam_unavailable_titles_are_skipped_not_fabricated(self):
        with patch.object(
            seed_mod, "fetch_search_by_term",
            side_effect=_fake_search_factory(unavailable={"Diablo III", "Minecraft Java"}),
        ), patch.object(seed_mod, "enrich_pool", side_effect=_fake_enrich):
            pool = seed_mod.build_curated_seed_pool(cc="US")

        names = {c.game["name"] for c in pool}
        self.assertNotIn("Diablo III", names)
        self.assertNotIn("Minecraft Java", names)
        # Everything else should still resolve.
        self.assertEqual(len(pool), len(seed_mod.CURATED_SEED_NAMES) - 2)

    def test_one_failed_lookup_does_not_drop_the_rest(self):
        def flaky_search(term, count=5, cc="US"):
            if term == "Valheim":
                raise ConnectionError("Steam search unreachable")
            return [{"id": f"id-{term}", "name": term}]

        with patch.object(seed_mod, "fetch_search_by_term", side_effect=flaky_search), \
             patch.object(seed_mod, "enrich_pool", side_effect=_fake_enrich):
            pool = seed_mod.build_curated_seed_pool(cc="US")

        names = {c.game["name"] for c in pool}
        self.assertNotIn("Valheim", names)
        self.assertGreater(len(pool), len(seed_mod.CURATED_SEED_NAMES) - 5)

    def test_no_tier_or_badge_is_assigned_by_this_module(self):
        """The whole point: this module produces candidates, never a
        classification. HeroCandidate objects from here carry no
        pre-assigned tier -- that only happens later, in
        classify_potato_tier_all()."""
        with patch.object(seed_mod, "fetch_search_by_term", side_effect=_fake_search_factory()), \
             patch.object(seed_mod, "enrich_pool", side_effect=_fake_enrich):
            pool = seed_mod.build_curated_seed_pool(cc="US")

        for candidate in pool:
            self.assertIsNone(getattr(candidate, "tier", None))
            self.assertIsNone(getattr(candidate, "hardware_badge", None))



if __name__ == "__main__":
    unittest.main()
