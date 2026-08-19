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
from services.hardware.homepage_classifier import classify_homepage_hardware
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


@pages_bp.route("/")
def home():
    try:
        cc = get_region_code()
        top_sellers_raw = fetch_browse_category("topsellers", count=100, cc=cc)
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

        # ---------------- INTEGRATED GPU + POTATO FRIENDLY ----------------
        # Real classification, not a placeholder badge. Runs against two
        # merged candidate sources:
        #   1. all_candidates -- the hero engine's pool (today's top
        #      sellers/new releases/specials), reused here at zero extra
        #      cost.
        #   2. potato_candidates -- a SEPARATE, dedicated pool of budget-
        #      priced catalog games (services/hero/potato_pool.py). The
        #      hero pool alone was nearly empty of anything that could
        #      classify into 🥔/🔧/💀, since the games those tiers are
        #      looking for are structurally not this week's top sellers.
        # Deduped by app_id (hero pool wins on overlap -- it's already
        # popularity-ranked, so preferring it costs nothing).
        # A game whose requirements don't resolve is left out entirely --
        # never defaulted in. See services/hardware/homepage_classifier.py
        # and services/hardware/potato_classifier.py.
        try:
            potato_candidates = _get_potato_pool(cc)
        except Exception:
            logger.exception("Potato pool fetch failed for region %s", cc)
            potato_candidates = []

        _hardware_pool_ids = {str(c.app_id) for c in all_candidates if c.app_id}
        hardware_pool = list(all_candidates) + [
            c for c in potato_candidates if c.app_id and str(c.app_id) not in _hardware_pool_ids
        ]

        try:
            igpu_games, potato_friendly, potato_tweaks, potato_extreme = classify_homepage_hardware(
                hardware_pool, seen_ids, limit=14
            )
        except Exception:
            logger.exception("Homepage hardware classification failed for region %s", cc)
            igpu_games, potato_friendly, potato_tweaks, potato_extreme = [], [], [], []
        for g in igpu_games:
            seen_ids.add(str(g["id"]))
        for g in potato_friendly:
            seen_ids.add(str(g["id"]))
        for g in potato_tweaks:
            seen_ids.add(str(g["id"]))
        for g in potato_extreme:
            seen_ids.add(str(g["id"]))
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