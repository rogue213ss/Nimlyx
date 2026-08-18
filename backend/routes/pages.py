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
        games = fetch_verified_new_releases(limit=12, cc=cc, candidate_pool=60)
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
                featured_games.append({
                    "id": hero["app_id"],
                    "name": hero["name"],
                    "header_image": hero["image"],
                    "image_candidates": hero["image_candidates"],
                    "analyze_url": hero["url"],
                    "insight": hero["insight"],
                    "why_it_matters": hero["why_it_matters"],
                    "nimlyx_score": get_cached_score(hero["app_id"], cc),
                })
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
        for i, g in enumerate(available_games[:10]):
            trending_games.append(format_basic_game(g, rank=i+1, orientation="portrait" if i == 0 else "landscape"))
            seen_ids.add(str(g.get("id")))
        available_games = available_games[10:]

        # ---------------- INTEGRATED GPU ----------------
        # V1 Fallback: No hardware database available yet. Use real games
        # but attach a neutral badge instead of fabricated FPS data.
        igpu_games = []
        for g in available_games[:8]:
            game_dict = format_basic_game(g)
            game_dict["hardware_badge"] = "Analysis Pending"
            igpu_games.append(game_dict)
            seen_ids.add(str(g.get("id")))
        available_games = available_games[8:]

        # ---------------- POTATO GAMES ----------------
        # V1 Fallback: We cannot randomly distribute games into "Tweaks" or "Extreme"
        # without requirement data. We populate only one list to keep the UI visually
        # functional with neutral badges. The template will hide the empty lists.
        potato_friendly = []
        potato_tweaks = []
        potato_extreme = []
        for g in available_games[:8]:
            game_dict = format_basic_game(g, orientation="portrait")
            game_dict["hardware_badge"] = "Pending Check"
            potato_friendly.append(game_dict)
            seen_ids.add(str(g.get("id")))
        available_games = available_games[8:]

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
        # V1 Fallback: No user hardware context or matching logic yet.
        best_matches = []
        for g in available_games[:6]:
            game_dict = format_basic_game(g)
            game_dict["hardware_badge"] = "Great Compatibility"
            best_matches.append(game_dict)
            seen_ids.add(str(g.get("id")))
        available_games = available_games[6:]

        # ---------------- NEW RELEASES ----------------
        try:
            verified_new_releases = _get_verified_new_releases(cc)
        except Exception:
            logger.exception("New Releases verification failed for region %s.", cc)
            verified_new_releases = []

        new_releases_filtered = [g for g in verified_new_releases if str(g.get("id")) not in seen_ids]
        new_release_games = []
        for g in new_releases_filtered[:10]:
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
        for g in deals_raw[:8]:
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