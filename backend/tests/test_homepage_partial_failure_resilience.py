"""
Regression tests for routes/pages.py's home() route resilience.

THE BUG THIS FILE GUARDS AGAINST
-----------------------------------
Before this fix, most sections of the homepage (Hero/Featured,
Nimlyx Picks, Trending, Hidden Gems, New Releases, Popular Right Now,
Biggest Deals) had NO per-section or per-item exception handling at
all -- unlike the Potato/iGPU sections, which already wrapped each
candidate's card-building in its own try/except. A single malformed
item anywhere in those unprotected sections (one game with an
unexpected None/missing field in its Steam-derived data -- entirely
plausible given how many different games flow through this pipeline
every day) raised an uncaught exception that propagated all the way
past `render_template`, and the ONLY safety net at the time was
`except requests.exceptions.RequestException:` -- which does not
match KeyError/AttributeError/TypeError, the actual exception types a
malformed data shape raises. The result: the entire homepage failed
outright (an unhandled 500) over a single bad game, even though every
OTHER section had already computed successfully. This is the most
likely explanation for "the homepage sometimes loads, sometimes
doesn't" reports.

The fix has two layers, both tested here:
  1. Every section that builds cards from a list of Steam-derived
     items now wraps EACH item's card-building in its own try/except
     -- one bad item is skipped and logged, the rest of that section
     (and every other section) renders normally.
  2. The outer safety net was widened from
     `except requests.exceptions.RequestException:` to a plain
     `except Exception:` -- so even a genuinely unforeseen failure
     somewhere degrades to the existing all-empty-sections fallback
     page (still a real, working page) instead of an unhandled crash.
"""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import app as flask_app_module  # noqa: E402


class FakeHeroCandidate:
    """A hero candidate whose to_hero_dict() raises, simulating a
    single game with an unexpected/malformed Steam-derived shape."""

    def __init__(self, name, broken=False):
        self.name = name
        self.app_id = name
        self._broken = broken

    def to_hero_dict(self):
        if self._broken:
            raise KeyError("simulated malformed Steam data for this one game")
        return {
            "app_id": self.name, "name": self.name, "image": "http://example.com/x.jpg",
            "image_candidates": [], "url": f"/search?app_id={self.name}",
            "insight": "", "why_it_matters": "", "steam_url": f"https://store.steampowered.com/app/{self.name}",
        }

    def to_pick_dict(self):
        if self._broken:
            raise KeyError("simulated malformed Steam data for this one game")
        return {
            "app_id": self.name, "name": self.name, "image": "http://example.com/x.jpg",
            "price": "$9.99", "url": f"/search?app_id={self.name}",
        }


def _base_patches():
    """Every homepage data source stubbed to a safe, empty/no-op
    default so these tests isolate the resilience behavior under
    test, without needing real Steam access."""
    return [
        patch("routes.pages._get_top_sellers", return_value=[]),
        patch("routes.pages._is_hero_build_pending", return_value=False),
        patch("routes.pages._get_potato_pool", return_value=[]),
        patch("routes.pages._get_curated_seed_pool", return_value=[]),
        patch("routes.pages._get_verified_new_releases", return_value=[]),
        patch("routes.pages.get_verified_potato_tiers",
              return_value={"friendly": [], "tweaks": [], "extreme": []}),
        patch("routes.pages.get_region_code", return_value="US"),
        patch("routes.pages.fetch_homepage_row", return_value=[]),
        patch("routes.pages.select_worth_buying", return_value=[]),
    ]


class TestMalformedHeroCandidateDoesNotCrashHomepage(unittest.TestCase):
    def setUp(self):
        self.client = flask_app_module.app.test_client()

    def test_one_broken_hero_among_good_ones_still_renders_the_rest(self):
        heroes = [
            FakeHeroCandidate("good-1"),
            FakeHeroCandidate("broken-1", broken=True),
            FakeHeroCandidate("good-2"),
        ]
        patches = _base_patches()
        for p in patches:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in patches])

        with patch("routes.pages._get_hero_lineup", return_value=(heroes, heroes)):
            response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        html = response.data.decode("utf-8")
        self.assertIn("good-1", html)
        self.assertIn("good-2", html)
        # The broken one must be silently skipped, not shown with
        # fabricated/blank data.
        self.assertNotIn("broken-1", html)

    def test_all_heroes_broken_still_returns_a_real_200_page(self):
        """The worst case for this specific section (every hero
        candidate malformed) must still degrade to a working page,
        not a 500 -- other sections are independent."""
        heroes = [FakeHeroCandidate("broken-1", broken=True), FakeHeroCandidate("broken-2", broken=True)]
        patches = _base_patches()
        for p in patches:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in patches])

        with patch("routes.pages._get_hero_lineup", return_value=(heroes, heroes)):
            response = self.client.get("/")

        self.assertEqual(response.status_code, 200)


class TestGenuinelyUnexpectedFailureDegradesGracefully(unittest.TestCase):
    """The widened outer `except Exception:` -- a total, unforeseen
    failure anywhere in the pipeline (not just a RequestException)
    must still return the existing all-empty-sections fallback page,
    not an unhandled 500."""

    def setUp(self):
        self.client = flask_app_module.app.test_client()

    def test_non_request_exception_in_hero_lineup_still_returns_200(self):
        patches = _base_patches()
        for p in patches:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in patches])

        # A plain, non-network exception (KeyError) raised somewhere
        # this test doesn't specifically target every individual
        # try/except for -- simulates "something genuinely
        # unforeseen" reaching the outer handler.
        with patch("routes.pages._get_hero_lineup", side_effect=KeyError("totally unexpected")):
            response = self.client.get("/")

        self.assertEqual(response.status_code, 200)

    def test_type_error_in_top_sellers_still_returns_200(self):
        patches = [p for p in _base_patches() if "_get_top_sellers" not in str(p)]
        for p in patches:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in patches])

        with patch("routes.pages._get_top_sellers", side_effect=TypeError("totally unexpected")), \
             patch("routes.pages._get_hero_lineup", return_value=([], [])):
            response = self.client.get("/")

        self.assertEqual(response.status_code, 200)


if __name__ == "__main__":
    unittest.main()
