"""
VERIFIED POTATO POOL — turns the researched database
(services/hardware/verified_potato_db.py) into real, homepage-ready
candidates.

PIPELINE
--------
    load_verified_potato_games()  [verified_potato_db.py -- static,
                                    local JSON, tier already decided]
            |
            v
    build rows keyed by Steam App ID (the JSON's own app id is the
    primary identity -- never re-searched by name, so a DLC/remaster/
    wrong-edition Steam search mismatch can't happen; see module
    docstring "STEAM APP IDS" in the original task for why)
            |
            v
    enrich_pool()  [services/hero/builder.py -- REUSED, not
                    duplicated: the exact same appdetails + review
                    fetch every other candidate pool in this codebase
                    uses]
            |
            v
    HeroCandidate objects, grouped by the JSON's verified tier
    (never recomputed from the enriched pc_requirements -- Steam's
    requirements text is enrichment/display data here, not a
    gatekeeper)

CACHING -- WHY IT'S CENTRALIZED HERE, NOT PER-ROUTE-FILE
------------------------------------------------------------
Every other cache in this codebase (hero pool, dynamic potato budget
pool, curated seed pool) lives in whichever single route file
consumes it (routes/pages.py or routes/potato.py), following the
serve-stale-while-revalidating pattern established there. This pool
is consumed by BOTH routes/pages.py's homepage AND routes/potato.py's
"view more" page. Duplicating the cache setup in both files would mean
two independent background threads re-enriching the same ~84 games on
their own schedules -- double the Steam calls for identical data, and
a real risk of the homepage and /potato page briefly disagreeing about
which games are in which tier. Centralizing the cache here (still the
exact same lock/TTL/background-thread shape as every other cache in
this codebase, just owned by the data module both callers import
instead of copy-pasted into each) avoids both problems.

STALE-STEAM-METADATA FALLBACK
------------------------------
`enrich_pool()` silently drops any game whose Steam appdetails call
fails outright (see its own docstring in services/hero/builder.py) --
correct default for the hero pool (a game with no real data can't
honestly be a hero), but wrong here: a verified Potato game must not
disappear from its row just because Steam hiccuped on one request. So
a rebuild here merges freshly-enriched games over the PREVIOUS cached
batch rather than replacing it outright -- any verified game that
fails to enrich this cycle keeps showing its last successfully-fetched
Steam metadata (art/price/store link) until a future rebuild succeeds
for it. The verified tier itself is never at risk either way, since it
never came from the Steam call in the first place.

NO NEW EXPENSIVE STEAM DISCOVERY SWEEP
-----------------------------------------
This does exactly one enrich_pool() pass over the ~84 renderable
verified games (2 Steam calls each, same as any other enrichment) --
no catalog search, no candidate discovery, no per-request Steam calls.
Steam is used here purely as instructed: art, title metadata, pricing,
current requirements text for display -- never as the gatekeeper for
which tier a game belongs to.
"""

import logging

from services.hardware.verified_potato_db import get_games_by_tier, load_verified_potato_games
from services.hero.builder import enrich_pool
from services.hero.candidate import HeroCandidate
from services.store.memory_store import store

logger = logging.getLogger(__name__)

TIERS = ("friendly", "tweaks", "extreme")

_CACHE_TTL_SECONDS = 24 * 3600  # the verified tier never changes
# without a code deploy (it's static, versioned research data); this
# TTL only governs how often Steam's price/discount/art metadata gets
# refreshed for display, so it doesn't need to be aggressive -- Potato
# /iGPU tier per the store's TTL plan.

# Loaded once at import time -- static local JSON, no need to re-read
# the file on every request. A future admin workflow that needs to
# hot-reload edited research data can call
# verified_potato_db.load_verified_potato_games() directly; this
# module's cache is specifically about the Steam ENRICHMENT step, not
# the JSON parse (which is already trivially cheap).
_ALL_ENTRIES = load_verified_potato_games()


# Values the research JSON uses to mean "we don't actually know" or
# "nothing special was needed" -- never rendered to the person as if
# they were real findings. Everything else in a record's
# real_world_evidence block is real researched data and passes
# through as-is (never reworded/invented).
_EVIDENCE_PLACEHOLDER_VALUES = {"", "unknown", "n/a", "none", "none listed", "not specified"}


def _meaningful(value):
    if not value:
        return None
    text = str(value).strip()
    if not text or text.lower() in _EVIDENCE_PLACEHOLDER_VALUES:
        return None
    return text


def format_evidence_for_card(evidence):
    """Turns one entry's `real_world_evidence` block (see
    verified_potato_db.py's schema docstring) into the compact fields
    the Potato page's cards actually render -- computed once here so
    templates/potato.html, static/js/potato.js's cardMarkup(), and any
    future consumer render byte-for-byte the same summary instead of
    three independent re-implementations of "how do I abbreviate this
    evidence block" drifting apart from each other.

    Never fabricates: a field that's missing or one of the JSON's own
    "we don't know"/"none needed" placeholder values (see
    _EVIDENCE_PLACEHOLDER_VALUES) is simply omitted from the output,
    not replaced with an invented default.
    """
    evidence = evidence or {}
    fps = _meaningful(evidence.get("average_fps")) or _meaningful(evidence.get("fps_range"))
    resolution = _meaningful(evidence.get("resolution"))
    settings = _meaningful(evidence.get("graphics_settings"))
    tweak = _meaningful(evidence.get("special_tweaks")) or _meaningful(evidence.get("config_modifications"))
    notes = _meaningful(evidence.get("notes"))
    quality = _meaningful(evidence.get("evidence_quality"))

    summary_parts = []
    if fps:
        summary_parts.append(f"{fps} FPS" if fps.replace("-", "").isdigit() else fps)
    if resolution:
        summary_parts.append(resolution)
    if settings:
        summary_parts.append(settings)

    return {
        "summary": " · ".join(summary_parts) if summary_parts else None,
        "tweak": tweak,
        "notes": notes,
        "quality": quality,
    }


def _build_tier_candidates(cc):
    """Enriches every renderable verified entry, grouped by tier.
    Reads the store's CURRENT (possibly stale) cached value for this
    key as `previous_by_app_id` -- safe to call from inside this
    builder: the store already marked this (key, cc) as `refreshing`
    before invoking us, so this get() cannot recurse into a second
    rebuild, it just hands back whatever's currently cached (or the
    empty dict on a true cold start) -- used to fall back to
    stale-but-real Steam metadata for any entry that fails to enrich
    this round, per the module docstring above."""
    cached_tiers = store.get("verified_potato_tiers", cc)
    previous_by_app_id = {}
    for tier in TIERS:
        for candidate in cached_tiers.get(tier, []):
            if candidate.app_id:
                previous_by_app_id[candidate.app_id] = candidate

    rows_by_app_id = {}
    entry_by_app_id = {}
    for tier in TIERS:
        for entry in get_games_by_tier(_ALL_ENTRIES, tier):
            if entry.app_id in rows_by_app_id:
                # Real duplicate app id across the verified DB --
                # keep the first entry encountered (friendly, since
                # TIERS is iterated in that order) and log the rest
                # rather than silently overwriting or crashing. There
                # were none in the shipped dataset, but a future
                # research update could introduce one.
                logger.warning(
                    "Verified Potato DB: app_id %s ('%s') already claimed by tier '%s' -- "
                    "duplicate entry '%s' (tier '%s') skipped.",
                    entry.app_id, entry_by_app_id[entry.app_id].name, entry_by_app_id[entry.app_id].tier,
                    entry.name, entry.tier,
                )
                continue
            rows_by_app_id[entry.app_id] = {"id": entry.app_id, "name": entry.name, "sources": ["verified_potato_db"]}
            entry_by_app_id[entry.app_id] = entry

    enriched_games = enrich_pool(list(rows_by_app_id.values()), cc=cc)
    enriched_by_app_id = {g.get("steam_appid") or g.get("id"): g for g in enriched_games}

    tier_candidates = {tier: [] for tier in TIERS}
    fell_back_count = 0
    dropped_count = 0

    for app_id, entry in entry_by_app_id.items():
        game = enriched_by_app_id.get(app_id)
        if game is None:
            previous_candidate = previous_by_app_id.get(app_id)
            if previous_candidate is not None:
                game = previous_candidate.game
                fell_back_count += 1
            else:
                # Never enriched successfully, ever -- no real Steam
                # data to build a card from. Not fabricated; simply
                # not rendered until a future rebuild succeeds.
                dropped_count += 1
                continue

        # Evidence comes entirely from the verified DB, never from
        # Steam -- always (re)computed fresh from the CURRENT entry
        # here, even on the stale-Steam-metadata fallback path above,
        # since a research data update should show up immediately
        # without waiting on Steam to also succeed.
        game = dict(game)
        game["verified_evidence"] = format_evidence_for_card(entry.evidence)

        tier_candidates[entry.tier].append(HeroCandidate(
            game=game,
            category="verified_potato",
            confidence=1.0,
            insight="",
            why_it_matters="",
        ))

    if fell_back_count or dropped_count:
        logger.warning(
            "Verified Potato pool enrichment for region %s: %d game(s) fell back to stale "
            "cached metadata, %d game(s) dropped (never successfully enriched).",
            cc, fell_back_count, dropped_count,
        )

    return tier_candidates


store.register("verified_potato_tiers", _build_tier_candidates, _CACHE_TTL_SECONDS, empty_value={tier: [] for tier in TIERS})


def get_verified_potato_tiers(cc="US"):
    """Returns {"friendly": [HeroCandidate, ...], "tweaks": [...],
    "extreme": [...]} for the requested region. Backed by the shared
    NimlyxMemoryStore -- same three-outcome serve-stale-while-
    revalidating shape as every other dataset there: fresh hit returns
    immediately; stale hit returns the stale-but-real data immediately
    and kicks off a background rebuild; true cold start returns empty
    lists and starts the first build in the background (never worse
    than before this pool existed -- callers should treat empty lists
    the same way they'd treat "hero pool still building")."""
    return store.get("verified_potato_tiers", cc)
