"""
Regression tests for the homepage-goes-empty-on-refresh bug.

Root cause: home() (backend/routes/pages.py) called
fetch_browse_category("topsellers", ...) directly and synchronously.
That function's own cache is TTL-only (no stale fallback), so once it
expired, a Steam timeout / 429 / 5xx propagated as an unhandled
requests.exceptions.RequestException all the way out of home(), which
wiped every already-successfully-built section (hero, potato pool,
new releases) back to an empty homepage.

The fix adds a serve-stale-while-revalidating cache for top sellers
(_get_top_sellers / _rebuild_top_sellers_cache in routes/pages.py),
matching the pattern already used for hero/potato/new-releases. These
tests cover that cache directly rather than driving the full Flask
route + Jinja render, since the cache behavior (not the template) is
what was broken.

Covers:
  1. Steam request succeeds -> normal behavior (data cached and returned).
  2. Steam returns 429/5xx -> homepage does not crash.
  3. Steam request times out -> homepage does not crash.
  4. Existing cache + failed refresh -> old cache remains (never
     replaced with [] or None).
  5. One Steam category (top sellers) failing doesn't affect an
     independent cache (e.g. new releases) -- other sections still render.
  6. No cache + Steam failure -> graceful [] fallback, not a crash.

Run with:
    python -m pytest backend/tests/test_homepage_resilience.py -v
"""
import os
import sys
import time
import unittest
from unittest.mock import patch

import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import routes.pages as pages  # noqa: E402


class TopSellersResilienceTests(unittest.TestCase):
    def setUp(self):
        # Each test gets a clean slate -- these caches are
        # module-level/in-process, so tests must not leak state.
        pages._TOP_SELLERS_CACHE = {}
        pages._TOP_SELLERS_BUILD_IN_PROGRESS = set()
        self.cc = "US"

    def _wait_for_background_build(self, timeout=2.0):
        """Background rebuilds run on a daemon thread; give it a beat
        to finish before asserting on cache state."""
        deadline = time.time() + timeout
        while self.cc in pages._TOP_SELLERS_BUILD_IN_PROGRESS and time.time() < deadline:
            time.sleep(0.01)

    # 1. Steam request succeeds -> normal behavior.
    def test_successful_fetch_populates_cache_and_returns_data(self):
        fake_games = [{"id": "123", "name": "Real Game"}]
        with patch.object(pages, "fetch_browse_category", return_value=fake_games) as mocked:
            pages._rebuild_top_sellers_cache(self.cc)
            mocked.assert_called_once_with("topsellers", count=100, cc=self.cc)

        result = pages._get_top_sellers(self.cc)
        self.assertEqual(result, fake_games)

    # 2. Steam returns 429/5xx -> homepage does not crash.
    def test_http_error_does_not_raise(self):
        http_error = requests.exceptions.HTTPError("429 Client Error: Too Many Requests")
        with patch.object(pages, "fetch_browse_category", side_effect=http_error):
            try:
                pages._rebuild_top_sellers_cache(self.cc)
            except Exception as exc:  # pragma: no cover - failure path
                self.fail(f"_rebuild_top_sellers_cache raised on HTTP error: {exc!r}")

    # 3. Steam request times out -> homepage does not crash.
    def test_timeout_does_not_raise(self):
        with patch.object(
            pages, "fetch_browse_category", side_effect=requests.exceptions.Timeout("timed out")
        ):
            try:
                pages._rebuild_top_sellers_cache(self.cc)
            except Exception as exc:  # pragma: no cover - failure path
                self.fail(f"_rebuild_top_sellers_cache raised on timeout: {exc!r}")

    # 4. Existing cache + failed refresh -> old cache remains.
    def test_stale_cache_survives_failed_refresh(self):
        good_games = [{"id": "999", "name": "Previously Fetched Game"}]
        with patch.object(pages, "fetch_browse_category", return_value=good_games):
            pages._rebuild_top_sellers_cache(self.cc)

        # Force the cached entry to look stale so _get_top_sellers()
        # triggers a background refresh.
        pages._TOP_SELLERS_CACHE[self.cc]["fetched_at"] = (
            time.time() - pages._TOP_SELLERS_CACHE_TTL_SECONDS - 1
        )

        with patch.object(
            pages, "fetch_browse_category", side_effect=requests.exceptions.ConnectionError("down")
        ):
            # First call: returns stale-but-real data immediately and
            # kicks off a background rebuild that will fail.
            result = pages._get_top_sellers(self.cc)
            self.assertEqual(result, good_games)
            self._wait_for_background_build()

        # The failed background refresh must NOT have replaced the
        # cache with [] or None -- the old, valid data must remain.
        self.assertEqual(pages._TOP_SELLERS_CACHE[self.cc]["games"], good_games)
        self.assertEqual(pages._get_top_sellers(self.cc), good_games)

    # 5. One Steam category fails but other cached homepage data
    #    (e.g. new releases, which has its own independent cache)
    #    still renders.
    def test_top_sellers_failure_does_not_affect_new_releases_cache(self):
        pages._NEW_RELEASES_CACHE = {}
        pages._NEW_RELEASES_BUILD_IN_PROGRESS = set()
        good_new_releases = [{"id": "42", "name": "Fresh Release"}]
        with patch.object(pages, "fetch_verified_new_releases", return_value=good_new_releases):
            pages._rebuild_new_releases_cache(self.cc)

        with patch.object(
            pages, "fetch_browse_category", side_effect=requests.exceptions.HTTPError("500")
        ):
            pages._rebuild_top_sellers_cache(self.cc)

        # Top sellers stayed empty/uncached (never fetched successfully),
        # but new releases -- an independent data source -- is untouched.
        self.assertEqual(pages._get_top_sellers(self.cc), [])
        self.assertEqual(pages._NEW_RELEASES_CACHE[self.cc]["games"], good_new_releases)

    # 6. No cache + Steam failure -> graceful fallback instead of a crash.
    def test_cold_start_with_steam_failure_returns_empty_list_not_crash(self):
        with patch.object(
            pages, "fetch_browse_category", side_effect=requests.exceptions.Timeout("timed out")
        ):
            try:
                result = pages._get_top_sellers(self.cc)
            except Exception as exc:  # pragma: no cover - failure path
                self.fail(f"_get_top_sellers raised on cold start + Steam failure: {exc!r}")
            self.assertEqual(result, [])
            self._wait_for_background_build()

        # Still nothing valid cached -- honest empty state, not a crash,
        # and not silently replaced with fabricated data.
        self.assertNotIn(self.cc, pages._TOP_SELLERS_CACHE)


if __name__ == "__main__":
    unittest.main()
