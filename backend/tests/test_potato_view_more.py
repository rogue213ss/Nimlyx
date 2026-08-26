"""
Regression tests for the /potato "view more" page and its pagination
API (routes/potato.py), post verified-database migration.

The dynamic pool merge + classify_potato_tier_all() this route used
to call are gone from here (still tested in isolation --
test_potato_classifier.py / test_potato_ecosystem_research.py -- and
still callable for research). This file now exercises the same
PAGINATION and PLUMBING concerns (routing, offset math, tier
validation, graceful degradation) against
services.hardware.verified_potato_pool.get_verified_potato_tiers()
instead, using synthetic HeroCandidate-shaped objects so nothing here
depends on the live JSON file's actual contents or on reaching Steam.
"""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import app as flask_app_module  # noqa: E402


class FakeCandidate:
    """Minimal stand-in for a HeroCandidate -- just enough surface
    (.app_id, .game, .to_pick_dict()) for to_homepage_card() to work
    against, without needing a real Steam-shaped candidate object."""

    def __init__(self, app_id, name):
        self.app_id = app_id
        self.game = {"id": app_id, "name": name}

    def to_pick_dict(self):
        return {
            "app_id": self.app_id,
            "name": self.game["name"],
            "image": "http://example.com/x.jpg",
            "price": "$9.99",
            "url": f"/game/{self.app_id}",
        }


def _candidates(n, prefix="game"):
    return [FakeCandidate(f"{prefix}-{i}", f"{prefix} game {i}") for i in range(n)]


class TestPotatoApiRoute(unittest.TestCase):
    def setUp(self):
        self.client = flask_app_module.app.test_client()

    def _tiers(self, friendly=(), tweaks=(), extreme=()):
        return {"friendly": list(friendly), "tweaks": list(tweaks), "extreme": list(extreme)}

    def test_page_route_renders_with_load_more_buttons(self):
        with patch("routes.potato.get_verified_potato_tiers",
                   return_value=self._tiers(friendly=_candidates(25))), \
             patch("routes.potato.get_region_code", return_value="US"):
            response = self.client.get("/potato")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Load More", response.data)
        # 25 friendly matches, PAGE_SIZE=20 -> first page has more.
        self.assertNotIn(b'data-tier="friendly" hidden', response.data)

    def test_pagination_offset_and_has_more(self):
        with patch("routes.potato.get_verified_potato_tiers",
                   return_value=self._tiers(friendly=_candidates(45))), \
             patch("routes.potato.get_region_code", return_value="US"):
            first = self.client.get("/api/potato/friendly?offset=0").get_json()
            second = self.client.get("/api/potato/friendly?offset=20").get_json()
            third = self.client.get("/api/potato/friendly?offset=40").get_json()

        self.assertEqual(len(first["games"]), 20)
        self.assertTrue(first["has_more"])
        self.assertEqual(first["next_offset"], 20)

        self.assertEqual(len(second["games"]), 20)
        self.assertTrue(second["has_more"])

        self.assertEqual(len(third["games"]), 5)
        self.assertFalse(third["has_more"])
        self.assertEqual(third["total_matches"], 45)

    def test_unknown_tier_returns_400(self):
        response = self.client.get("/api/potato/definitely-not-a-tier")
        self.assertEqual(response.status_code, 400)
        body = response.get_json()
        self.assertEqual(body["games"], [])

    def test_negative_offset_clamped_to_zero(self):
        with patch("routes.potato.get_verified_potato_tiers",
                   return_value=self._tiers(friendly=_candidates(5))), \
             patch("routes.potato.get_region_code", return_value="US"):
            response = self.client.get("/api/potato/friendly?offset=-50").get_json()

        self.assertEqual(len(response["games"]), 5)

    def test_only_returns_the_requested_tier(self):
        with patch("routes.potato.get_verified_potato_tiers",
                   return_value=self._tiers(friendly=_candidates(5, "f"), extreme=_candidates(3, "e"))), \
             patch("routes.potato.get_region_code", return_value="US"):
            friendly = self.client.get("/api/potato/friendly?offset=0").get_json()
            extreme = self.client.get("/api/potato/extreme?offset=0").get_json()

        self.assertEqual(friendly["total_matches"], 5)
        self.assertEqual(extreme["total_matches"], 3)

    def test_load_more_button_absent_when_tier_fits_on_one_page(self):
        """A tier with fewer games than PAGE_SIZE should render with
        NO Load More button/wrapper at all -- not a hidden one taking
        up empty space."""
        with patch("routes.potato.get_verified_potato_tiers",
                   return_value=self._tiers(friendly=_candidates(5, "f"))), \
             patch("routes.potato.get_region_code", return_value="US"):
            response = self.client.get("/potato")

        html = response.data.decode("utf-8")
        self.assertNotIn("potato-load-more-btn", html)
        self.assertNotIn("potato-load-more-wrap", html)

    def test_load_more_button_present_when_tier_has_more_pages(self):
        with patch("routes.potato.get_verified_potato_tiers",
                   return_value=self._tiers(friendly=_candidates(25, "f"))), \
             patch("routes.potato.get_region_code", return_value="US"):
            response = self.client.get("/potato")

        html = response.data.decode("utf-8")
        self.assertIn('potato-load-more-btn" data-tier="friendly"', html)

    def test_load_more_absent_for_every_tier_when_all_empty(self):
        with patch("routes.potato.get_verified_potato_tiers", return_value=self._tiers()), \
             patch("routes.potato.get_region_code", return_value="US"):
            response = self.client.get("/potato")

        html = response.data.decode("utf-8")
        self.assertEqual(html.count("potato-load-more-wrap"), 0)
        self.assertEqual(html.count("Nothing resolved into this tier yet"), 3)

    def test_empty_pools_return_empty_not_error(self):
        with patch("routes.potato.get_verified_potato_tiers", return_value=self._tiers()), \
             patch("routes.potato.get_region_code", return_value="US"):
            response = self.client.get("/api/potato/friendly?offset=0")

        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertEqual(body["games"], [])
        self.assertFalse(body["has_more"])

    def test_verified_pool_failure_does_not_crash_the_page(self):
        """The verified pool getter itself never raises in practice
        (get_verified_potato_tiers() has no un-caught path), but the
        route wraps its use in try/except anyway -- this guards that
        a total failure there degrades to an empty page, not a 500."""
        with patch("routes.potato.get_verified_potato_tiers", side_effect=Exception("cache exploded")), \
             patch("routes.potato.get_region_code", return_value="US"):
            response = self.client.get("/potato")

        self.assertEqual(response.status_code, 200)

    def test_card_building_failure_for_one_game_does_not_drop_the_rest(self):
        """A malformed candidate (raises inside to_homepage_card())
        must not take out every other game already resolved -- same
        "one bad candidate can't zero everything" contract as the
        homepage's classify_igpu_only()."""
        good = _candidates(3, "good")
        broken = FakeCandidate("broken-1", "Broken Game")
        broken.to_pick_dict = lambda: (_ for _ in ()).throw(ValueError("malformed"))

        with patch("routes.potato.get_verified_potato_tiers",
                   return_value=self._tiers(friendly=good + [broken])), \
             patch("routes.potato.get_region_code", return_value="US"):
            response = self.client.get("/api/potato/friendly?offset=0").get_json()

        self.assertEqual(len(response["games"]), 3)


if __name__ == "__main__":
    unittest.main()
