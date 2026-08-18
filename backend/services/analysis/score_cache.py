"""
SCORE CACHE — non-blocking Nimlyx Score lookup for homepage surfaces
that don't already fetch review data as part of their own build
(Trending, Deals, Action). Hero and Discover Picks get their score
"for free" from services/hero/candidate.py (review_summary is already
fetched during the hero background build); New Releases gets it the
same way from fetch_verified_new_releases() in steam.py. Neither of
those needed this module.

Trending and the two lazy-loaded feed rows (specials/action) are
different: their existing data sources make ZERO per-game Steam
calls today (a single scrape, no appdetails/appreviews round-trip).
Calling get_review_summary() for every card on the request path would
reintroduce exactly the blocking-Steam-call problem the hero/new-
releases caches were built to avoid.

Same pattern as every other cache in this codebase (see the hero and
new-releases caches in routes/pages.py): a request never blocks.
get_cached_score() returns whatever's already cached (possibly None,
meaning "no score yet") and kicks off a background thread to fetch it
for next time. Scores move slowly, so a generous TTL is fine.
"""

import logging
import threading
import time

from steam import get_review_summary
from services.analysis.wilson_score import compute_nimlyx_score

logger = logging.getLogger(__name__)

_SCORE_CACHE = {}  # app_id (str) -> {"score": dict|None, "fetched_at": float}
_SCORE_CACHE_LOCK = threading.Lock()
_SCORE_CACHE_TTL_SECONDS = 3600  # 1 hour -- review aggregates don't move fast
_SCORE_BUILD_IN_PROGRESS = set()


def _rebuild_score(app_id, cc):
    try:
        summary = get_review_summary(app_id, cc)
        score = None
        if summary:
            score = compute_nimlyx_score(
                total_positive=summary["total_positive"],
                total_reviews=summary["total_reviews"],
            )
        with _SCORE_CACHE_LOCK:
            _SCORE_CACHE[app_id] = {"score": score, "fetched_at": time.time()}
    except Exception:
        logger.exception("Background Nimlyx Score build failed for app_id %s", app_id)
    finally:
        with _SCORE_CACHE_LOCK:
            _SCORE_BUILD_IN_PROGRESS.discard(app_id)


def get_cached_score(app_id, cc="US"):
    """Never blocks, never fabricates. Returns the cached score dict
    (from compute_nimlyx_score) if one exists, or None -- callers
    must render the .nimlyx-score fallback state for None, exactly
    like every other "not yet available" case in this codebase.

    A cold cache means every card shows the fallback the first time
    a region sees it; the background fetch fills it in for
    subsequent requests, same tradeoff as the hero and new-releases
    caches make.
    """
    if not app_id:
        return None
    app_id = str(app_id)

    with _SCORE_CACHE_LOCK:
        cached = _SCORE_CACHE.get(app_id)
        building = app_id in _SCORE_BUILD_IN_PROGRESS

    needs_refresh = cached is None or (time.time() - cached["fetched_at"]) >= _SCORE_CACHE_TTL_SECONDS
    if needs_refresh and not building:
        with _SCORE_CACHE_LOCK:
            _SCORE_BUILD_IN_PROGRESS.add(app_id)
        threading.Thread(target=_rebuild_score, args=(app_id, cc), daemon=True).start()

    return cached["score"] if cached else None
