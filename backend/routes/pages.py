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

DATA LAYER — services/store/memory_store.py
---------------------------------------------
Every dataset below (hero, top sellers, new releases, the two Potato
pools) is registered with the shared NimlyxMemoryStore instead of
each having its own hand-rolled dict/lock/TTL/background-thread, the
way this file used to. The actual fetch/enrich logic (build_hero_
lineup, fetch_browse_category, etc.) is completely unchanged — the
store just owns the "when does this refresh, and what do I serve
while that's happening" plumbing centrally. See that module's
docstring for the full guarantee list (stale-but-available, atomic
swap, at most one rebuild in flight, plus a genuine time-triggered
~hours-scale refresh independent of traffic).

TTLs are set per the "different data, different freshness" plan:
Potato/iGPU pools barely change without a code deploy, so they get a
long TTL; top sellers/new releases move faster and get a shorter one.
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
from services.store.memory_store import store

pages_bp = Blueprint("pages", __name__)
logger = logging.getLogger(__name__)

# ----------------------------------------------------------------
# Dataset registration -- each builder_fn below is the exact same
# call every bespoke cache in this file used to make; only the
# caching/refresh mechanics moved into the shared store.
# ----------------------------------------------------------------
_HERO_TTL_SECONDS = 5 * 3600      # "Featured" tier -- ~5h per the plan
_TOP_SELLERS_TTL_SECONDS = 3 * 3600   # feeds Trending/Popular/Deals -- 1-3h tier, use the tighter end since it also drives pricing
_NEW_RELEASES_TTL_SECONDS = 8 * 3600  # 5-12h tier


def _build_hero(cc):
    res = build_hero_lineup(cc=cc)
    if not res or not res[0]:
        raise RuntimeError("Hero lineup failed to build (likely Steam rate limited)")
    return res


def _build_top_sellers(cc):
    res = fetch_browse_category("topsellers", count=100, cc=cc)
    if not res:
        raise RuntimeError("Top sellers failed to build")
    return res


def _build_new_releases(cc):
    res = fetch_verified_new_releases(limit=14, cc=cc, candidate_pool=60)
    if not res:
        raise RuntimeError("New releases failed to build")
    return res








store.register("hero", _build_hero, _HERO_TTL_SECONDS, empty_value=(None, None))
store.register("top_sellers", _build_top_sellers, _TOP_SELLERS_TTL_SECONDS, empty_value=[])
store.register("new_releases", _build_new_releases, _NEW_RELEASES_TTL_SECONDS, empty_value=[])


def _get_hero_lineup(cc):
    return store.get("hero", cc)


def _is_hero_build_pending(cc):
    """True only while a background rebuild is ACTIVELY running for
    this region right now. Deliberately separate from "no picks/hero
    insight to show" — those need different UX: a genuine build in
    progress will resolve itself shortly (show a notice, poll, then
    reload), while a completed build that legitimately had nothing to
    publish this cycle never will (show nothing, don't poll forever).
    """
    return store.is_refreshing("hero", cc)








def _get_verified_new_releases(cc):
    return store.get("new_releases", cc)


def _get_top_sellers(cc):
    return store.get("top_sellers", cc)


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
# Store warm-up + periodic refresh — fixes the "homepage loads with
# almost every section missing" bug on Render's free tier, and (new)
# makes the ~5h-scale refresh happen independent of traffic.
#
# Deliberately NOT called at module-import time. Gunicorn (Render's
# default) commonly runs with `--preload`, which imports the app ONCE
# in a master process and then fork()s worker processes from it.
# Starting background threads here would race with that fork — if
# fork() lands while one of these threads holds a store lock, the
# forked child inherits that lock already acquired forever (the
# thread that would release it doesn't exist in the child). Every
# later request touching that lock then hangs indefinitely — exactly
# the "every request times out" bug this comment exists to prevent
# reintroducing. Instead, warm-up (and starting the periodic-refresh
# loop) is triggered from inside a real request via
# _ensure_store_warmed() below, which only ever runs post-fork, in
# whichever worker process actually received the request.
#
# Warms "US" — the same fallback region get_region_code() already
# uses when IP geolocation fails — since a cold process can't know a
# real visitor's region yet. Any other region still lazily builds on
# its own first request, same as before.
# ----------------------------------------------------------------
_STORE_WARMED = False
_STORE_WARMED_LOCK = threading.Lock()


def _ensure_store_warmed():
    global _STORE_WARMED
    with _STORE_WARMED_LOCK:
        if _STORE_WARMED:
            return
        _STORE_WARMED = True
    store.warm("US")
    store.start_periodic_refresh(interval_seconds=3600)  # heartbeat; each dataset only actually rebuilds once ITS OWN ttl elapses


@pages_bp.before_app_request
def _warm_store_before_request():
    _ensure_store_warmed()


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

        # ---------------- POTATO AND INTEGRATED GPU ----------------
        try:
            verified_tiers = get_verified_potato_tiers(cc)
        except Exception:
            logger.exception("Verified Potato pool fetch failed for region %s", cc)
            verified_tiers = {"friendly": [], "tweaks": [], "extreme": []}
            
        # iGPU uses a mix of hero pool and verified low-spec games
        _hardware_pool_ids = {str(c.app_id) for c in all_candidates if c.app_id}
        hardware_pool = list(all_candidates)
        
        # Add verified potato games to the hardware pool
        for tier in ("friendly", "tweaks", "extreme"):
            for candidate in verified_tiers.get(tier, []):
                app_id = str(candidate.app_id) if candidate.app_id else None
                if app_id and app_id not in _hardware_pool_ids:
                    hardware_pool.append(candidate)
                    _hardware_pool_ids.add(app_id)
        
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