"""
POTATO CANDIDATE POOL — a dedicated candidate source for the Potato
ecosystem (🥔 Friendly / 🔧 Tweaks / 💀 Extreme), separate from the
hero/insight engine's `all_candidates` pool.

WHY THIS FILE EXISTS
----------------------
`services/hero/pool.py`'s `build_candidate_pool()` feeds Nimlyx's hero
carousel and Nimlyx Picks. It's deliberately built from Steam's
CURRENT top sellers, new releases, and specials -- exactly right for
"what's hot right now" on the homepage.

`classify_homepage_hardware()` (services/hardware/homepage_classifier.py)
was originally wired to reuse that same pool for the Potato ecosystem,
on the reasoning that it was "free" (already fetched, zero extra Steam
calls). That reasoning missed something: the Potato ecosystem
classifies games against a genuinely old reference rig (Intel HD 4400
/ i3-4130 / 8 GB, see homepage_classifier.POTATO_PROFILE), and the
games that actually land in any of its three tiers are, almost by
definition, NOT this week's top sellers or new releases -- they're
older or budget titles. Handing classify_homepage_hardware() a pool
that structurally excludes almost everything it's looking for is why
the live homepage was showing at most one or two iGPU cards and
nothing at all in Potato Friendly/Tweaks/Extreme, independent of how
well-calibrated the classifier itself is.

This module widens that net with a SEPARATE scrape: Steam's catalog
filtered to low, PERMANENT price ceilings (steam.py's
`fetch_budget_catalog_sweep()`, reusing the exact same verified
`BUDGET_MAX_PRICE_CENTS` bands Discover already uses) -- a full-price
new AAA game essentially never sits permanently under $10-20, so this
reliably surfaces older/smaller titles instead of today's trending
list. It does NOT replace `all_candidates` for the hero carousel or
Nimlyx Picks -- those keep using today's popular pool exactly as
before; this is purely an additional source for the Potato ecosystem.

PIPELINE
--------
    build_potato_scrape_pool()   [this file -- budget price sweeps]
            |
            v
    enrich_pool()                 [services/hero/builder.py -- REUSED,
                                    not duplicated: same appdetails +
                                    review_summary fetch the hero pool
                                    uses, so pc_requirements arrives in
                                    the exact same shape]
            |
            v
    build_potato_candidate_pool() [wraps each enriched game in a
                                    HeroCandidate so it duck-types
                                    identically to the hero pool for
                                    classify_homepage_hardware()]

No insight generation or hero selection runs on this pool -- Potato
cards only ever need name/image/price/pc_requirements
(`_to_homepage_card()` in homepage_classifier.py reads exactly those
via `to_pick_dict()`), so running the full insight-provider pipeline
here would be pure wasted Steam calls and CPU for data nothing
displays.
"""

from services.hero.builder import enrich_pool
from services.hero.candidate import HeroCandidate
from steam import fetch_budget_catalog_sweep

# Matches steam.py's BUDGET_MAX_PRICE_CENTS "under-10" / "under-20" /
# "under-40" bands (Discover's own verified budget filter) rather than
# inventing new price cutoffs -- three sweeps, not one, because a
# single low ceiling would skew toward tiny/free indie titles and
# under-represent the "modest AAA" games (GTA V-era titles are often
# $15-20 even years later) the Potato ecosystem also wants to surface.
#
# The $40 band was added after a research/validation pass
# (docs/potato_research_matrix.md) confirmed that the Potato
# ecosystem's most interesting 💀 Extreme candidates -- older AAA
# titles whose official minimum spec exceeds the potato reference on
# paper (Dark Souls III, Dragon Age: Inquisition, The Witcher 3,
# Skyrim Special Edition, Dying Light) -- permanently retail well
# above the previous $10/$20 ceiling (commonly $30-60, even years
# after release; only temporary sales bring them under $20, which the
# hero pool already covers separately). Without this band, the scrape
# structurally excluded almost every real 💀 Extreme candidate,
# independent of how well-calibrated the classifier itself is -- the
# same class of gap that motivated this file's original $10/$20
# sweeps over reusing the hero pool. $40 was chosen over "any-price"
# to keep this a genuinely *budget-leaning* net (matching Discover's
# own existing "under-40" verified band) rather than pulling in
# current full-price new releases, which the hero pool already
# covers.
BUDGET_BANDS_CENTS = (1000, 2000, 4000)  # $10, $20, $40
SWEEP_COUNT_PER_BAND = 100


def build_potato_scrape_pool(cc="US"):
    """Runs the budget catalog sweeps and dedupes by app id -- same
    shape/dedup pattern as build_candidate_pool() in
    services/hero/pool.py (id/name/image/... rows with a `sources`
    list), so it can go through the identical enrich_pool() step.
    """
    pool_by_id = {}

    for max_price_cents in BUDGET_BANDS_CENTS:
        try:
            games = fetch_budget_catalog_sweep(max_price_cents, count=SWEEP_COUNT_PER_BAND, cc=cc)
        except Exception:
            # One price band failing (Steam hiccup/timeout) shouldn't
            # take down the whole pool -- proceed with whatever the
            # other band returned.
            games = []

        source_label = f"budget_under_{max_price_cents // 100}"
        for game in games:
            app_id = game.get("id")
            name = (game.get("name") or "").strip()
            if not app_id or not name or name == "Unknown":
                continue

            if app_id not in pool_by_id:
                pool_by_id[app_id] = {**game, "sources": [source_label]}
            else:
                if source_label not in pool_by_id[app_id]["sources"]:
                    pool_by_id[app_id]["sources"].append(source_label)

    return list(pool_by_id.values())


def build_potato_candidate_pool(cc="US"):
    """Full pipeline: scrape -> enrich (appdetails + pc_requirements)
    -> wrap in HeroCandidate. Returns a list of HeroCandidate objects
    that duck-type identically to the hero pool's `all_candidates` for
    classify_homepage_hardware()'s purposes (`.app_id`, `.game`,
    `.to_pick_dict()`).

    category/confidence/insight/why_it_matters are inert placeholders
    here -- HeroCandidate's badge/insight machinery exists for the
    hero carousel and Nimlyx Picks, and classify_homepage_hardware()'s
    `_to_homepage_card()` never reads them (it supplies its own
    `hardware_badge` instead). `get_badge()` falls back to a generic
    badge for any unrecognized category rather than raising, so this
    placeholder category is safe -- see services/hero/badges.py.
    """
    scraped = build_potato_scrape_pool(cc=cc)
    enriched = enrich_pool(scraped, cc=cc)

    return [
        HeroCandidate(
            game=game,
            category="potato_pool",
            confidence=1.0,
            insight="",
            why_it_matters="",
        )
        for game in enriched
    ]
