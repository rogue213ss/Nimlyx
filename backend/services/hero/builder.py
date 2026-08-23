"""
BUILDER — owns the full pipeline from raw candidate pool to a
selected hero lineup:

    build_candidate_pool()   [pool.py]
            |
            v
    enrich_pool()            [this file — appdetails + reviews, concurrent]
            |
            v
    generate_candidates()    [services/insights/engine.py]
            |
            v
    select_heroes()          [selector.py]
            |
            v
    (selected heroes, all candidates for manifest)

This is the single entry point (build_hero_lineup) everything else —
the eventual scheduled job, a manual "rebuild now" route, a debug
script — should call. Nothing outside this file should need to know
the pipeline has five steps.
"""

from concurrent.futures import ThreadPoolExecutor

from steam import get_appdetails, get_review_summary
from services.hero.pool import build_candidate_pool
from services.insights.engine import generate_candidates
from services.hero.selector import select_heroes

# Enrichment does 2 Steam calls per game (appdetails + reviews). This
# many games in parallel keeps a ~30-60 game pool from taking forever
# without hammering Steam hard enough to get rate-limited.
ENRICH_WORKERS = 8


def _enrich_one(scraped_game, cc):
    """Fetches appdetails + review summary for one scraped game and
    merges them into the shape every Insight Provider expects. Returns
    None if appdetails fails entirely — a game we can't get real data
    for can't honestly be a hero, no matter how it looked in the
    scrape.
    """
    app_id = scraped_game.get("id")
    if not app_id:
        return None

    raw = get_appdetails(app_id, cc)
    if raw is None:
        # Region-unavailable fallback, same pattern as /api/find —
        # a game missing in the visitor's own region shouldn't be
        # silently dropped from the pool if it exists at all.
        raw = get_appdetails(app_id, "US")
    if raw is None:
        return None

    raw["review_summary"] = get_review_summary(app_id, cc)

    # Keep the original scrape's `sources` field (top_seller /
    # new_release / special) — providers don't use it yet, but it's
    # cheap to carry forward and may become a confidence signal later.
    raw["sources"] = scraped_game.get("sources", [])
    raw["scraped_image"] = scraped_game.get("image")

    return raw


def enrich_pool(pool, cc="US"):
    """pool: list of raw scraped games from build_candidate_pool().
    Returns a list of enriched appdetails dicts (+ review_summary),
    dropping any game whose appdetails lookup failed outright in both
    the requested region and the US fallback.
    """
    if not pool:
        return []

    with ThreadPoolExecutor(max_workers=ENRICH_WORKERS) as executor:
        results = list(executor.map(lambda g: _enrich_one(g, cc), pool))

    return [r for r in results if r is not None]


def build_hero_lineup(cc="US", per_category_count=60):
    """Runs the full pipeline and returns (selected, all_candidates).

    `selected` is the ordered hero lineup ready for the frontend.
    `all_candidates` is every HeroCandidate considered, winners and
    losers alike — this is what a Phase 4 build manifest will be
    written from.
    """
    raw_pool = build_candidate_pool(cc=cc, per_category_count=per_category_count)
    enriched = enrich_pool(raw_pool, cc=cc)
    candidates = generate_candidates(enriched)
    selected, all_candidates = select_heroes(candidates)

    return selected, all_candidates
