"""
CANDIDATE POOL — Phase 1 of the homepage insight engine.

Merges Steam's top sellers, new releases, and specials into one
deduplicated pool of games eligible to be considered for a hero slot.
This file does NOT generate insights or pick heroes — it only decides
who's ALLOWED to compete. Insight Providers (Phase 2) and the Selector
(Phase 3) run on top of whatever this returns.

Eligibility floor exists so an obscure, low-signal game can't win a
hero slot just because it happened to have one dramatic-looking stat
(e.g. a 90% discount on a game nobody's heard of with 3 reviews).
Quality of the *pool* protects quality of the *homepage* — see
docs/homepage-engine.md, principle: "curated, not exhaustive."
"""

from steam import fetch_browse_category

# A game must have a real Steam listing (id + name) to even be
# considered — this alone filters out malformed scrape rows, not
# actual quality. Real quality filtering (review count, etc.) happens
# in Phase 2 once appdetails/review data is pulled per-candidate,
# since fetch_browse_category's scrape doesn't carry review counts.
MIN_NAME_LENGTH = 1


def _is_valid_candidate(game):
    """Bare-minimum sanity check on a scraped game row. Not the real
    eligibility floor (that needs review/sales data Phase 2 fetches
    per-candidate) — just enough to drop obviously broken rows before
    they enter the pool at all."""
    if not game.get("id"):
        return False
    name = (game.get("name") or "").strip()
    if len(name) < MIN_NAME_LENGTH or name == "Unknown":
        return False
    return True


def build_candidate_pool(cc="US", per_category_count=25):
    """Fetches top sellers, new releases, and specials, dedupes by
    app id, and returns one flat list of candidate games.

    Each candidate keeps a `sources` field listing which category
    list(s) it appeared in (a game can be both a top seller AND on
    sale) — useful later for debugging why a game made the pool, and
    potentially as an extra confidence signal for Insight Providers.

    Returns a list of dicts shaped like fetch_browse_category's output,
    plus `sources`. Does not call appdetails/reviews — this is the
    cheap, scrape-only pass. Per-candidate enrichment happens later,
    only for games that survive to Phase 2, so we're not paying for
    appdetails calls on games that never had a shot at a hero slot.
    """
    category_fetches = {
        "top_seller": "topsellers",
        "new_release": "popularnew",
        "special": "specials",
    }

    pool_by_id = {}

    for source_label, steam_category in category_fetches.items():
        try:
            games = fetch_browse_category(steam_category, count=per_category_count, cc=cc)
        except Exception:
            # One category failing (timeout, Steam hiccup) shouldn't
            # take down the whole pool — just proceed with fewer
            # sources. Phase 4's build validation is what catches a
            # pool that ends up too thin as a result.
            games = []

        for game in games:
            if not _is_valid_candidate(game):
                continue

            app_id = game["id"]

            if app_id not in pool_by_id:
                pool_by_id[app_id] = {**game, "sources": [source_label]}
            else:
                if source_label not in pool_by_id[app_id]["sources"]:
                    pool_by_id[app_id]["sources"].append(source_label)

    return list(pool_by_id.values())
