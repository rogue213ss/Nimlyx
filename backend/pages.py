"""
HOMEPAGE — server-side rendered, plus the two client-rendered
pages (/discover, /search) that just hand off to their JS.

Section list matches the locked homepage layout: Hero + Insight
callout, Nimlyx Picks (interactive), Discover promo, Trending Today,
New Releases, Footer. Biggest Deals / Free to Play / Why Nimlyx were
dropped from the homepage in this revision — not deleted from the
codebase, just no longer rendered here. Their data (specials_raw)
is no longer fetched on this route at all, which also trims one
Steam round-trip off every homepage load.
"""
import logging
import threading
import time
import requests
from flask import Blueprint, render_template, jsonify

from region import get_region_code
from steam import fetch_browse_category, fetch_verified_new_releases, fetch_homepage_row
from formatters import format_price
from services.hero.builder import build_hero_lineup
from services.hero.picks import select_worth_buying
from services.analysis.score_cache import get_cached_score
from services.hardware.homepage_classifier import classify_igpu_only, to_homepage_card
from services.hardware.verified_potato_pool import get_verified_potato_tiers
from steam_images import default_header_image, build_image_candidates

pages_bp = Blueprint("pages", __name__)
logger = logging.getLogger(__name__)

# ----------------------------------------------------------------
# Hero-lineup cache — serve-stale-while-revalidating.
#
# build_hero_lineup() makes ~2 live Steam calls per surviving
# candidate (100+ round-trips on a full pool). Blocking a request on
# that — the previous TTL-cache version — is what made the homepage
# feel heavy after the revamp, and made it outright fail on Render's
# free tier (cold container start + cold hero build stacking into a
# request timeout).
#
# New behavior:
#   - Cache hit, fresh:  return immediately, zero Steam calls.
#   - Cache hit, stale:  return the stale-but-REAL data immediately
#     (never fake — just not the newest build), and kick off a
#     background rebuild for the NEXT visitor. This request never
#     waits on it.
#   - Cache miss entirely (first request since process start): return
#     (None, None). home()'s existing fallback branch already handles
#     this honestly — real top-sellers data, insight bar correctly
#     hidden — this just reuses that tested path instead of ever
#     blocking a request on a full build.
#
# Only one background rebuild per region runs at a time; repeated
# requests during a rebuild don't pile up duplicate builds. This is
# still an in-memory, per-process stopgap — a redeploy or a second
# worker process starts cold again — but it's the actual bottleneck
# fix; a persistent/shared cache (Phase 4) is a separate step if
# deploys turn out to be frequent enough to matter.
# ----------------------------------------------------------------
_HERO_CACHE = {}
_HERO_CACHE_LOCK = threading.Lock()
_HERO_CACHE_TTL_SECONDS = 900  # 15 minutes
_HERO_BUILD_IN_PROGRESS = set()


def _rebuild_hero_cache(cc):
    """Runs in a background thread — never blocks a request. Any
    failure here just leaves the existing cache entry (or nothing, on
    a first build) in place; it's logged, and the next stale/miss
    simply tries again later."""
    try:
        selected, all_candidates = build_hero_lineup(cc=cc)
        with _HERO_CACHE_LOCK:
            _HERO_CACHE[cc] = {
                "selected": selected,
                "all_candidates": all_candidates,
                "fetched_at": time.time(),
            }
    except Exception:
        logger.exception("Background hero rebuild failed for region %s.", cc)
    finally:
        with _HERO_CACHE_LOCK:
            _HERO_BUILD_IN_PROGRESS.discard(cc)


def _get_hero_lineup(cc):
    with _HERO_CACHE_LOCK:
        cached = _HERO_CACHE.get(cc)
        building = cc in _HERO_BUILD_IN_PROGRESS

    if cached is not None:
        is_stale = (time.time() - cached["fetched_at"]) >= _HERO_CACHE_TTL_SECONDS
        if is_stale and not building:
            with _HERO_CACHE_LOCK:
                _HERO_BUILD_IN_PROGRESS.add(cc)
            threading.Thread(target=_rebuild_hero_cache, args=(cc,), daemon=True).start()
        return cached["selected"], cached["all_candidates"]

    # True cold start — nothing cached yet for this region at all.
    if not building:
        with _HERO_CACHE_LOCK:
            _HERO_BUILD_IN_PROGRESS.add(cc)
        threading.Thread(target=_rebuild_hero_cache, args=(cc,), daemon=True).start()

    return None, None


def _is_hero_build_pending(cc):
    """True only while a background rebuild is ACTIVELY running for
    this region right now. Deliberately separate from "no picks/hero
    insight to show" — those need different UX: a genuine build in
    progress will resolve itself shortly (show a notice, poll, then
    reload), while a completed build that legitimately had nothing to
    publish this cycle never will (show nothing, don't poll forever).
    """
    with _HERO_CACHE_LOCK:
        return cc in _HERO_BUILD_IN_PROGRESS


# ----------------------------------------------------------------
# Potato-pool cache — same serve-stale-while-revalidating pattern as
# the hero cache above, deliberately kept as a SEPARATE cache/lock/
# background thread rather than folded into _HERO_CACHE: this pool
# answers a different question (which older/budget games exist at
# all) than the hero pool (which of today's popular games deserve a
# hero slot), and a slow/failed build of one should never block or
# invalidate the other. See services/hero/potato_pool.py for why this
# pool exists and what it scrapes.
# ----------------------------------------------------------------
_POTATO_CACHE = {}
_POTATO_CACHE_LOCK = threading.Lock()
_POTATO_CACHE_TTL_SECONDS = 1800  # 30 minutes -- this pool changes far
# less often than the hero pool (Steam's budget-priced catalog doesn't
# turn over hour to hour the way top sellers/new releases do), so a
# longer TTL means fewer redundant ~60-120-game enrichment sweeps.
_POTATO_BUILD_IN_PROGRESS = set()


def _rebuild_potato_cache(cc):
    """Runs in a background thread — never blocks a request. Mirrors
    _rebuild_hero_cache()'s failure handling: any error here just
    leaves the existing cache entry (or nothing, on a first build) in
    place, logged, and the next stale/miss simply tries again later."""
    try:
        from services.hero.potato_pool import build_potato_candidate_pool
        candidates = build_potato_candidate_pool(cc=cc)
        with _POTATO_CACHE_LOCK:
            _POTATO_CACHE[cc] = {
                "candidates": candidates,
                "fetched_at": time.time(),
            }
    except Exception:
        logger.exception("Background potato pool rebuild failed for region %s.", cc)
    finally:
        with _POTATO_CACHE_LOCK:
            _POTATO_BUILD_IN_PROGRESS.discard(cc)


def _get_potato_pool(cc):
    """Same three-outcome shape as _get_hero_lineup(): fresh hit
    returns immediately; stale hit returns the stale-but-real list
    immediately and kicks off a background rebuild; a true cold start
    (nothing cached yet) returns [] and starts the first build in the
    background. A cold-start [] here is never worse than today's
    behavior — the Potato/iGPU sections simply fall back to whatever
    the hero pool alone can find, exactly as before this pool
    existed, until the first background build finishes."""
    with _POTATO_CACHE_LOCK:
        cached = _POTATO_CACHE.get(cc)
        building = cc in _POTATO_BUILD_IN_PROGRESS

    if cached is not None:
        is_stale = (time.time() - cached["fetched_at"]) >= _POTATO_CACHE_TTL_SECONDS
        if is_stale and not building:
            with _POTATO_CACHE_LOCK:
                _POTATO_BUILD_IN_PROGRESS.add(cc)
            threading.Thread(target=_rebuild_potato_cache, args=(cc,), daemon=True).start()
        return cached["candidates"]

    if not building:
        with _POTATO_CACHE_LOCK:
            _POTATO_BUILD_IN_PROGRESS.add(cc)
        threading.Thread(target=_rebuild_potato_cache, args=(cc,), daemon=True).start()

    return []


# ----------------------------------------------------------------
# Curated seed cache -- same serve-stale-while-revalidating pattern as
# the caches above. Moved here from routes/potato.py (which used to
# own it) now that the /potato "view more" page sources exclusively
# from the verified database and no longer needs this pool -- the
# Integrated GPU section below (still dynamically classified) is this
# cache's only remaining consumer. build_curated_seed_pool() does ~80
# individual Steam search lookups plus appdetails enrichment per call
# -- far too slow to run inline on every homepage request, and a
# failed refresh must never replace a working cached pool with an
# empty one (same "never let a failed Steam call empty out working
# data" rule as the rest of the site).
# ----------------------------------------------------------------
_CURATED_SEED_CACHE = {}
_CURATED_SEED_CACHE_LOCK = threading.Lock()
_CURATED_SEED_CACHE_TTL_SECONDS = 3600  # names rarely change; requirements do, hourly is plenty
_CURATED_SEED_BUILD_IN_PROGRESS = set()


def _rebuild_curated_seed_cache(cc):
    try:
        from services.hero.potato_curated_seed import build_curated_seed_pool
        pool = build_curated_seed_pool(cc=cc)
        with _CURATED_SEED_CACHE_LOCK:
            _CURATED_SEED_CACHE[cc] = {"pool": pool, "fetched_at": time.time()}
    except Exception:
        logger.exception("Curated seed pool rebuild failed for region %s.", cc)
    finally:
        with _CURATED_SEED_CACHE_LOCK:
            _CURATED_SEED_BUILD_IN_PROGRESS.discard(cc)


def _get_curated_seed_pool(cc):
    with _CURATED_SEED_CACHE_LOCK:
        cached = _CURATED_SEED_CACHE.get(cc)
        building = cc in _CURATED_SEED_BUILD_IN_PROGRESS

    if cached is not None:
        is_stale = (time.time() - cached["fetched_at"]) >= _CURATED_SEED_CACHE_TTL_SECONDS
        if is_stale and not building:
            with _CURATED_SEED_CACHE_LOCK:
                _CURATED_SEED_BUILD_IN_PROGRESS.add(cc)
            threading.Thread(target=_rebuild_curated_seed_cache, args=(cc,), daemon=True).start()
        return cached["pool"]

    if not building:
        with _CURATED_SEED_CACHE_LOCK:
            _CURATED_SEED_BUILD_IN_PROGRESS.add(cc)
        threading.Thread(target=_rebuild_curated_seed_cache, args=(cc,), daemon=True).start()

    return []


# ----------------------------------------------------------------
# New-releases cache — same serve-stale-while-revalidating pattern
# as the hero cache above, same reasoning: fetch_verified_new_
# releases() makes one live appdetails call per candidate purely to
# check each one's real release date, which is real API cost worth
# paying in the background, not inside a request.
# ----------------------------------------------------------------
_NEW_RELEASES_CACHE = {}
_NEW_RELEASES_CACHE_LOCK = threading.Lock()
_NEW_RELEASES_CACHE_TTL_SECONDS = 1800  # 30 minutes
_NEW_RELEASES_BUILD_IN_PROGRESS = set()


def _rebuild_new_releases_cache(cc):
    try:
        games = fetch_verified_new_releases(limit=14, cc=cc, candidate_pool=60)
        with _NEW_RELEASES_CACHE_LOCK:
            _NEW_RELEASES_CACHE[cc] = {"games": games, "fetched_at": time.time()}
    except Exception:
        logger.exception("Background new-releases rebuild failed for region %s.", cc)
    finally:
        with _NEW_RELEASES_CACHE_LOCK:
            _NEW_RELEASES_BUILD_IN_PROGRESS.discard(cc)


def _get_verified_new_releases(cc):
    with _NEW_RELEASES_CACHE_LOCK:
        cached = _NEW_RELEASES_CACHE.get(cc)
        building = cc in _NEW_RELEASES_BUILD_IN_PROGRESS

    if cached is not None:
        is_stale = (time.time() - cached["fetched_at"]) >= _NEW_RELEASES_CACHE_TTL_SECONDS
        if is_stale and not building:
            with _NEW_RELEASES_CACHE_LOCK:
                _NEW_RELEASES_BUILD_IN_PROGRESS.add(cc)
            threading.Thread(target=_rebuild_new_releases_cache, args=(cc,), daemon=True).start()
        return cached["games"]

    # True cold start — nothing cached yet. Kick off a background
    # build and return an empty list for THIS request; the New
    # Releases section already guards on `{% if new_release_games %}`
    # and simply doesn't render when empty, same honest-degradation
    # approach as the hero fallback.
    if not building:
        with _NEW_RELEASES_CACHE_LOCK:
            _NEW_RELEASES_BUILD_IN_PROGRESS.add(cc)
        threading.Thread(target=_rebuild_new_releases_cache, args=(cc,), daemon=True).start()

    return []


# ----------------------------------------------------------------
# Top-sellers cache -- same serve-stale-while-revalidating pattern as
# the hero/potato/new-releases caches above.
#
# Root cause of the "homepage goes empty on refresh" bug: this was
# previously a direct, synchronous fetch_browse_category("topsellers",
# ...) call inside home() with no local fallback. fetch_browse_category
# has its own short-lived (180s) cache, but that cache is a plain TTL
# cache -- once an entry ages past 180s it returns None and the next
# call hits Steam live again. Steam's search/results endpoint
# occasionally times out or returns 429/5xx (rate limiting, transient
# outages), which raised inside fetch_browse_category via
# response.raise_for_status(). That exception propagated all the way
# up to home()'s outer except requests.exceptions.RequestException,
# which discarded every already-successfully-built section (hero,
# potato pool, new releases -- all independently cached and fine) and
# rendered a fully empty homepage.
#
# Fixed the same way every other homepage data source already handles
# this: fetch on a background thread, serve the last known-good
# (possibly stale) result instantly, and never let a failed refresh
# replace good data with [] or None. See _rebuild_top_sellers_cache
# below -- a failed fetch_func() call there is caught and simply
# leaves the existing cache entry in place.
# ----------------------------------------------------------------
_TOP_SELLERS_CACHE = {}
_TOP_SELLERS_CACHE_LOCK = threading.Lock()
_TOP_SELLERS_CACHE_TTL_SECONDS = 180  # matches fetch_browse_category's own TTL
_TOP_SELLERS_BUILD_IN_PROGRESS = set()


def _rebuild_top_sellers_cache(cc):
    """Runs in a background thread -- never blocks a request. Mirrors
    _rebuild_hero_cache()'s failure handling: if the Steam fetch fails
    (timeout, 429, 5xx, anything raised by raise_for_status()), the
    exception is caught and logged here, and the existing cache entry
    (or nothing, on a first build) is left untouched -- a failed
    refresh must never overwrite valid cached data with [] or None."""
    try:
        games = fetch_browse_category("topsellers", count=100, cc=cc)
        with _TOP_SELLERS_CACHE_LOCK:
            _TOP_SELLERS_CACHE[cc] = {"games": games, "fetched_at": time.time()}
    except Exception:
        logger.exception("Background top-sellers rebuild failed for region %s.", cc)
    finally:
        with _TOP_SELLERS_CACHE_LOCK:
            _TOP_SELLERS_BUILD_IN_PROGRESS.discard(cc)


def _get_top_sellers(cc):
    """Same three-outcome shape as _get_hero_lineup()/_get_potato_pool():
    fresh hit returns immediately; stale hit returns the stale-but-real
    list immediately and kicks off a background rebuild (Steam being
    slow/down right now never blocks or empties this request); a true
    cold start (nothing cached yet, e.g. right after deploy) returns []
    and starts the first build in the background -- every downstream
    section that reads top_sellers_raw already tolerates an empty list
    (they just render fewer/no cards this one time), same honest-
    degradation approach used elsewhere in this file."""
    with _TOP_SELLERS_CACHE_LOCK:
        cached = _TOP_SELLERS_CACHE.get(cc)
        building = cc in _TOP_SELLERS_BUILD_IN_PROGRESS

    if cached is not None:
        is_stale = (time.time() - cached["fetched_at"]) >= _TOP_SELLERS_CACHE_TTL_SECONDS
        if is_stale and not building:
            with _TOP_SELLERS_CACHE_LOCK:
                _TOP_SELLERS_BUILD_IN_PROGRESS.add(cc)
            threading.Thread(target=_rebuild_top_sellers_cache, args=(cc,), daemon=True).start()
        return cached["games"]

    if not building:
        with _TOP_SELLERS_CACHE_LOCK:
            _TOP_SELLERS_BUILD_IN_PROGRESS.add(cc)
        threading.Thread(target=_rebuild_top_sellers_cache, args=(cc,), daemon=True).start()

    return []


def hero_image_url(appid, fallback):
    """
    NIMLYX TRADITION #005 — "Sharp beats cinematic if cinematic
    sometimes doesn't exist." This used to guess capsule_616x353.jpg
    directly as the src for every trending/new-release card — Valve
    generates that asset for "essentially every" app ID, but
    "essentially" still meant occasional blank cards.

    Now: always return something guaranteed to load. `fallback` is
    Steam's own scraped thumbnail (already real, already loaded once
    by the browser that scraped it) when we have it; otherwise fall
    back to the CDN-convention header.jpg, which costs zero API calls
    and Steam serves for every listed app. Sharper art is attempted
    client-side via build_image_candidates() + image-upgrade.js and
    only swapped in on a real, successful load. See
    services/hero/candidate.py for the matching fix on the Picks/Hero
    side.
    """
    return default_header_image(appid)


# ----------------------------------------------------------------
# Startup cache warm-up — fixes the "homepage loads with almost
# every section missing" bug on Render's free tier.
#
# Every cache above used a purely lazy, request-triggered warm-up:
# the FIRST request after a cold start (fresh deploy, or Render's
# free-tier dyno spinning back up after idling) hit a true cache
# miss for every single one of them, got back [] / None instantly,
# and rendered a homepage where only the two unconditional sections
# (Browse by Category, Why Nimlyx) show — hero, picks, trending,
# deals, new releases, iGPU, and all three Potato tiers are each
# individually gated by `{% if ... %}` on data that simply hadn't
# been built yet. The background thread those helpers kicked off
# was real and would have finished a few seconds later, but that
# request had already been rendered and sent.
#
# Fix: start the same background builds the moment this module is
# imported (process boot), instead of waiting for the first visitor
# to trigger them. This can't know a visitor's real region yet, so
# it warms "US" — the same fallback region get_region_code() already
# uses when IP geolocation fails — which covers the large majority
# of cold-boot traffic. Any other region still falls back to the
# existing lazy-build path on its own first request, same as today.
# ----------------------------------------------------------------
def _warm_caches_on_boot(cc="US"):
    for cache_dict, lock, in_progress, rebuild_fn in (
        (_HERO_CACHE, _HERO_CACHE_LOCK, _HERO_BUILD_IN_PROGRESS, _rebuild_hero_cache),
        (_TOP_SELLERS_CACHE, _TOP_SELLERS_CACHE_LOCK, _TOP_SELLERS_BUILD_IN_PROGRESS, _rebuild_top_sellers_cache),
        (_NEW_RELEASES_CACHE, _NEW_RELEASES_CACHE_LOCK, _NEW_RELEASES_BUILD_IN_PROGRESS, _rebuild_new_releases_cache),
        (_POTATO_CACHE, _POTATO_CACHE_LOCK, _POTATO_BUILD_IN_PROGRESS, _rebuild_potato_cache),
        (_CURATED_SEED_CACHE, _CURATED_SEED_CACHE_LOCK, _CURATED_SEED_BUILD_IN_PROGRESS, _rebuild_curated_seed_cache),
    ):
        with lock:
            if cc in cache_dict or cc in in_progress:
                continue
            in_progress.add(cc)
        threading.Thread(target=rebuild_fn, args=(cc,), daemon=True).start()


_warm_caches_on_boot()


@pages_bp.route("/")
def home():
    try:
        cc = get_region_code()
        top_sellers_raw = _get_top_sellers(cc)
        seen_ids = set()

        # Helper to format a basic game dict
        def format_basic_game(g, rank=None, orientation="landscape"):
            game = {
                "id": g.get("id"),
                "name": g.get("name"),
                "header_image": hero_image_url(g.get("id"), g.get("image")),
                "image_candidates": build_image_candidates(g.get("id"), orientation=orientation, fallback_image=g.get("image")),
                "analyze_url": f"/search?app_id={g.get('id')}",
                "steam_url": f"https://store.steampowered.com/app/{g.get('id')}" if g.get("id") else "",
                "price": format_price(g.get("final_price")),
                "nimlyx_score": get_cached_score(g.get("id"), cc),
            }
            if rank:
                game["rank"] = rank
            if g.get("discount_percent"):
                game["discount_percent"] = g.get("discount_percent")
            if g.get("original_price"):
                game["original_price"] = g.get("original_price")
            return game

        # ---------------- HERO + NIMLYX PICKS ----------------
        try:
            selected_heroes, all_candidates = _get_hero_lineup(cc)
        except Exception:
            logger.exception("Hero engine build failed for region %s", cc)
            selected_heroes, all_candidates = [], []

        if selected_heroes is None:
            selected_heroes = []
        if all_candidates is None:
            all_candidates = []

        hero_pending = _is_hero_build_pending(cc)

        if selected_heroes:
            featured_games = []
            for candidate in selected_heroes:
                hero = candidate.to_hero_dict()
                # Start from the FULL hero dict (steam_url, genres,
                # discount_percent, price_before, review_desc,
                # review_sentiment, release_date_label, badge_* ...)
                # rather than hand-picking a subset -- a previous
                # version of this loop only copied a few keys across,
                # which silently dropped `steam_url` and left the
                # hero's "View on Steam" button pointing at an empty
                # href (it just reloaded the current page instead of
                # opening the Steam store page).
                game = dict(hero)
                game["id"] = hero["app_id"]
                game["header_image"] = hero["image"]
                game["analyze_url"] = hero["url"]
                game["nimlyx_score"] = get_cached_score(hero["app_id"], cc)
                featured_games.append(game)
        else:
            featured_games = [format_basic_game(g) for g in top_sellers_raw[:5]]
            for f in featured_games:
                f["insight"] = ""
                f["why_it_matters"] = ""
        
        for g in featured_games:
            if g.get("id"):
                seen_ids.add(str(g["id"]))

        nimlyx_picks = [c.to_pick_dict() for c in select_worth_buying(all_candidates)]
        for p in nimlyx_picks:
            if p.get("app_id"):
                seen_ids.add(str(p["app_id"]))

        # ---------------- FILTER REMAINING GAMES ----------------
        available_games = [g for g in top_sellers_raw if str(g.get("id")) not in seen_ids]

        # ---------------- TRENDING TODAY ----------------
        trending_games = []
        for i, g in enumerate(available_games[:14]):
            trending_games.append(format_basic_game(g, rank=i+1, orientation="portrait" if i == 0 else "landscape"))
            seen_ids.add(str(g.get("id")))
        available_games = available_games[14:]

        # ---------------- INTEGRATED GPU ----------------
        # Still the dynamic classifier -- unaffected by the verified-
        # database migration below. Runs against three merged
        # candidate sources (hero pool, budget-price potato pool,
        # curated seed pool) exactly as before.
        try:
            potato_candidates = _get_potato_pool(cc)
        except Exception:
            logger.exception("Potato pool fetch failed for region %s", cc)
            potato_candidates = []

        # 3. curated_seed_candidates -- guaranteed-considered pool of
        #    user-researched titles (services/hero/potato_curated_seed.py).
        #    Neither of the two sources above is guaranteed to surface
        #    any SPECIFIC title on a given day (Steam's search ranking
        #    and a 100-per-band fetch cap both affect what comes back);
        #    this closes that gap for iGPU classification purposes.
        try:
            curated_seed_candidates = _get_curated_seed_pool(cc)
        except Exception:
            logger.exception("Curated seed pool fetch failed for region %s", cc)
            curated_seed_candidates = []

        _hardware_pool_ids = {str(c.app_id) for c in all_candidates if c.app_id}
        hardware_pool = list(all_candidates) + [
            c for c in potato_candidates if c.app_id and str(c.app_id) not in _hardware_pool_ids
        ]
        _hardware_pool_ids.update(str(c.app_id) for c in potato_candidates if c.app_id)
        hardware_pool += [
            c for c in curated_seed_candidates if c.app_id and str(c.app_id) not in _hardware_pool_ids
        ]

        try:
            igpu_games = classify_igpu_only(hardware_pool, seen_ids, limit=14)
        except Exception:
            logger.exception("iGPU classification failed for region %s", cc)
            igpu_games = []
        for g in igpu_games:
            seen_ids.add(str(g["id"]))

        # ---------------- POTATO FRIENDLY / TWEAKS / EXTREME ----------------
        # Sourced from the researched, verified database
        # (data/potato/verified_potato_games.json), NOT from Steam's
        # published requirements -- see
        # services/hardware/verified_potato_db.py and
        # services/hardware/verified_potato_pool.py for why. A game's
        # tier here was decided by real-world low-end testing evidence,
        # not by re-running the dynamic classifier against whatever
        # Steam currently lists as the minimum spec.
        try:
            verified_tiers = get_verified_potato_tiers(cc)
        except Exception:
            logger.exception("Verified Potato pool fetch failed for region %s", cc)
            verified_tiers = {"friendly": [], "tweaks": [], "extreme": []}

        potato_friendly, potato_tweaks, potato_extreme = [], [], []
        # Homepage rows are a PREVIEW, not the full list -- capped
        # noticeably lower than the verified pool's real size (see
        # POTATO_HOMEPAGE_PREVIEW_LIMIT below) specifically so the
        # homepage stays scannable and the /potato page (which has no
        # such cap, just "Load More") is where the full ecosystem
        # actually lives. Tweaks and Extreme in particular render as a
        # vertical list/wrapping grid rather than a horizontal-scroll
        # row, so an uncapped-feeling count there made the homepage
        # very tall.
        POTATO_HOMEPAGE_PREVIEW_LIMIT = 6
        potato_tier_totals = {tier: len(verified_tiers.get(tier, [])) for tier in ("friendly", "tweaks", "extreme")}
        for tier, bucket, badge, orientation in (
            ("friendly", potato_friendly, "Meets Low-End Minimum", "portrait"),
            ("tweaks", potato_tweaks, "Playable With Tweaks", "landscape"),
            ("extreme", potato_extreme, "Extreme Settings Only", "landscape"),
        ):
            for candidate in verified_tiers.get(tier, []):
                app_id = str(candidate.app_id) if candidate.app_id else None
                if not app_id or app_id in seen_ids:
                    continue
                if len(bucket) >= POTATO_HOMEPAGE_PREVIEW_LIMIT:
                    continue
                try:
                    card = to_homepage_card(candidate, badge, orientation=orientation)
                except Exception:
                    logger.exception("Failed to build verified Potato card for app_id=%s", app_id)
                    continue
                bucket.append(card)
                seen_ids.add(app_id)

        # Real count from the verified database, not a fabricated
        # "hundreds of games" gesture -- used by the CTA banner at the
        # bottom of the Potato section to entice the click-through
        # with an accurate number.
        potato_total_count = sum(potato_tier_totals.values())

        available_games = [g for g in available_games if str(g.get("id")) not in seen_ids]

        # ---------------- HIDDEN GEMS ----------------
        # V1 Heuristic: Use games further down the top-sellers list (lower mainstream
        # visibility today) that still managed to rank, to avoid adding new Steam API calls.
        hidden_gems = []
        # Skip down the list a bit to avoid the absolute biggest mainstream games
        gems_pool = available_games[20:] if len(available_games) > 25 else available_games
        for i, g in enumerate(gems_pool[:5]):
            hidden_gems.append(format_basic_game(g, orientation="portrait" if i == 0 else "landscape"))
            seen_ids.add(str(g.get("id")))
        # Remove the ones we used from the main pool
        available_games = [g for g in available_games if str(g.get("id")) not in seen_ids]

        # ---------------- BEST MATCHES ----------------
        # Disabled (not fabricated): "Games Your PC Is Built For" requires
        # actual user hardware to compare against, and nothing in the app
        # persists a chosen CPU/GPU today (the "Can I Run This?" picker on
        # Game Detail is per-request/ephemeral -- never saved). Filling
        # this section from leftover top-sellers, even with a real-sounding
        # badge, would be an unsubstantiated compatibility claim -- exactly
        # what the "Great Compatibility" placeholder was already guilty of.
        # Re-enable once a persisted user hardware profile exists to
        # actually run through evaluate_compatibility(). Section markup
        # stays in index.html (guarded by {% if best_matches %}) so it's
        # a one-line revival, not a rebuild.
        best_matches = []

        # ---------------- NEW RELEASES ----------------
        try:
            verified_new_releases = _get_verified_new_releases(cc)
        except Exception:
            logger.exception("New Releases verification failed for region %s.", cc)
            verified_new_releases = []

        new_releases_filtered = [g for g in verified_new_releases if str(g.get("id")) not in seen_ids]
        new_release_games = []
        for g in new_releases_filtered[:14]:
            new_release_games.append({
                "id": g["id"],
                "name": g["name"],
                "header_image": hero_image_url(g["id"], g.get("image")),
                "image_candidates": build_image_candidates(g["id"], fallback_image=g.get("image")),
                "analyze_url": f"/search?app_id={g['id']}",
                "recency_label": g["recency_label"],
                "price": g["price"] or "—",
                "primary_genre": g.get("primary_genre"),
            })
            seen_ids.add(str(g["id"]))

        # ---------------- POPULAR RIGHT NOW (ACTION) ----------------
        action_raw = fetch_homepage_row("action", cc=cc, seen_ids=seen_ids) or []
        popular_games = []
        for g in action_raw[:10]:
            popular_games.append({
                **g,
                "price": format_price(g.get("price")),
                "nimlyx_score": get_cached_score(g.get("app_id"), cc),
            })
            seen_ids.add(str(g.get("app_id")))

        # ---------------- BIGGEST DEALS (SPECIALS) ----------------
        deals_raw = fetch_homepage_row("specials", cc=cc, seen_ids=seen_ids) or []
        deals_games = []
        for g in deals_raw[:14]:
            deals_games.append({
                **g,
                "price": format_price(g.get("price")),
                "nimlyx_score": get_cached_score(g.get("app_id"), cc),
            })
            seen_ids.add(str(g.get("app_id")))

        return render_template(
            "index.html",
            featured_games=featured_games,
            nimlyx_picks=nimlyx_picks,
            trending_games=trending_games,
            new_release_games=new_release_games,
            popular_games=popular_games,
            deals_games=deals_games,
            igpu_games=igpu_games,
            potato_friendly=potato_friendly,
            potato_tweaks=potato_tweaks,
            potato_extreme=potato_extreme,
            potato_total_count=potato_total_count,
            hidden_gems=hidden_gems,
            best_matches=best_matches,
            hero_pending=hero_pending,
            seen_ids=list(seen_ids),
        )

    except requests.exceptions.RequestException:
        logger.exception("Homepage request failed entirely — Steam unreachable or timed out.")
        return render_template(
            "index.html",
            featured_games=[],
            nimlyx_picks=[],
            trending_games=[],
            new_release_games=[],
            popular_games=[],
            deals_games=[],
            igpu_games=[],
            potato_friendly=[],
            potato_tweaks=[],
            potato_extreme=[],
            potato_total_count=0,
            hidden_gems=[],
            best_matches=[],
            hero_pending=False,
            seen_ids=[],
        )


@pages_bp.route("/api/hero-status")
def hero_status():
    """Polled by static/js/hero-refresh.js while the homepage shows
    the "Preparing fresh insights..." notice. Reports whether a
    background hero build is genuinely still running for the
    visitor's region -- once it flips to false, the poller reloads
    the page so the visitor sees the real, completed build without
    ever touching Refresh themselves.
    """
    cc = get_region_code()
    return jsonify({"pending": _is_hero_build_pending(cc)})


@pages_bp.route("/discover")
def discover():
    return render_template("discover.html")


@pages_bp.route("/search")
def search_page():
    return render_template("search.html")


@pages_bp.route("/about")
def about_page():
    return render_template("about.html")


@pages_bp.route("/privacy")
def privacy_page():
    return render_template("privacy.html")


@pages_bp.route("/terms")
def terms_page():
    return render_template("terms.html")