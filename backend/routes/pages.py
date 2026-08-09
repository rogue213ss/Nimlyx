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
from steam import fetch_browse_category, fetch_verified_new_releases
from formatters import format_price
from services.hero.builder import build_hero_lineup
from services.hero.picks import select_worth_buying
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
        games = fetch_verified_new_releases(limit=5, cc=cc)
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
    return fallback or default_header_image(appid)


@pages_bp.route("/")
def home():
    try:
        cc = get_region_code()
        top_sellers_raw = fetch_browse_category("topsellers", cc=cc)

        # ---------------- HERO + NIMLYX PICKS ----------------
        # Both come from the same Insight Engine build: the hero
        # carousel is the winning HeroCandidates, Picks is the
        # leftover ones that were still good enough to publish.
        try:
            selected_heroes, all_candidates = _get_hero_lineup(cc)
        except Exception:
            logger.exception(
                "Hero engine build failed for region %s — falling back to "
                "plain top-sellers with no insight text. This is the exact "
                "condition that produces an empty/hidden insight bar.", cc
            )
            selected_heroes, all_candidates = [], []

        # _get_hero_lineup() returns (None, None) on a true cold start
        # (nothing cached yet, background build just kicked off) —
        # normalize to empty so select_worth_buying() below always
        # gets an iterable, never a None it wasn't built to handle.
        if selected_heroes is None:
            selected_heroes = []
        if all_candidates is None:
            all_candidates = []

        # Checked AFTER _get_hero_lineup() specifically -- that call is
        # what sets the in-progress flag on a cold start or stale
        # cache, so this reflects the true current state for this
        # exact request.
        hero_pending = _is_hero_build_pending(cc)

        if selected_heroes:
            featured_games = []
            for candidate in selected_heroes:
                hero = candidate.to_hero_dict()
                # hero["image"] is already guaranteed (curated/IGDB
                # override or Steam's real header_image/header.jpg —
                # see HeroCandidate.to_hero_dict); no need to re-guess
                # it here the way hero_image_url() used to.
                featured_games.append({
                    "id": hero["app_id"],
                    "name": hero["name"],
                    "header_image": hero["image"],
                    "image_candidates": hero["image_candidates"],
                    "analyze_url": hero["url"],
                    "insight": hero["insight"],
                    "why_it_matters": hero["why_it_matters"],
                })
        else:
            # Fallback if the pool came back empty or every provider
            # had nothing honest to say this build — keeps the hero
            # carousel populated with something real either way.
            featured_games = [
                {
                    "id": g.get("id"),
                    "name": g.get("name"),
                    "header_image": hero_image_url(g.get("id"), g.get("image")),
                    "image_candidates": build_image_candidates(g.get("id")),
                    # Same fix as HeroCandidate._build_base_dict -- g["id"]
                    # is Steam's own top-sellers app_id, already right
                    # here; don't discard it for a name-based re-lookup.
                    "analyze_url": f"/search?app_id={g.get('id')}",
                    "insight": "",
                    "why_it_matters": "",
                }
                for g in top_sellers_raw[:5]
            ]

        nimlyx_picks = [c.to_pick_dict() for c in select_worth_buying(all_candidates)]

        # ---------------- TRENDING TODAY ----------------
        # Real Steam top-seller ordering, rendered as large landscape
        # cards instead of the old small grid — same underlying data
        # as the previous "Top Sellers" section, new visual treatment.
        trending_games = [
            {
                "id": g.get("id"),
                "name": g.get("name"),
                "header_image": hero_image_url(g.get("id"), g.get("image")),
                "image_candidates": build_image_candidates(g.get("id")),
                # Same fix as HeroCandidate._build_base_dict -- link by
                # the app_id Steam's top-sellers list already gave us.
                "analyze_url": f"/search?app_id={g.get('id')}",
                "rank": i + 1,
                "price": format_price(g.get("final_price")),
            }
            for i, g in enumerate(top_sellers_raw[:6])
        ]

        # ---------------- NEW RELEASES ----------------
        # Every field here is real, verified against Steam's own
        # appdetails release_date for that exact game -- see
        # fetch_verified_new_releases() in steam.py. Games without a
        # trustworthy, parseable, already-released date are dropped
        # rather than padded in with a guess, so this list can come
        # back shorter than 5 -- that's correct, not a bug. Wrapped
        # in its own try/except so a Steam hiccup here degrades to an
        # empty (not fake) section instead of failing the whole page.
        try:
            verified_new_releases = _get_verified_new_releases(cc)
        except Exception:
            logger.exception("New Releases verification failed for region %s.", cc)
            verified_new_releases = []

        new_release_games = [
            {
                "id": g["id"],
                "name": g["name"],
                "header_image": g["image"],
                "image_candidates": build_image_candidates(g["id"]),
                # Same fix as HeroCandidate._build_base_dict -- g["id"]
                # is already the verified app_id fetch_verified_new_releases
                # confirmed the release date against; link straight to it.
                "analyze_url": f"/search?app_id={g['id']}",
                "recency_label": g["recency_label"],
                # No invented "Free" or placeholder price when Steam
                # simply didn't return price data for this region.
                "price": g["price"] or "—",
            }
            for g in verified_new_releases
        ]

        return render_template(
            "index.html",
            featured_games=featured_games,
            nimlyx_picks=nimlyx_picks,
            trending_games=trending_games,
            new_release_games=new_release_games,
            hero_pending=hero_pending,
        )

    except requests.exceptions.RequestException:
        logger.exception("Homepage request failed entirely — Steam unreachable or timed out.")
        return render_template(
            "index.html",
            featured_games=[],
            nimlyx_picks=[],
            trending_games=[],
            new_release_games=[],
            # Steam itself is unreachable here -- a background build
            # isn't quietly finishing somewhere, there's nothing to
            # poll for, so no pending notice.
            hero_pending=False,
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
    try:
        cc = get_region_code()
        top_sellers_raw = fetch_browse_category("topsellers", cc=cc)
        
        trending_games = []
        for g in top_sellers_raw[:10]:
            discount_raw = g.get("discount_percent") or ""
            # Filter non-digits safely if discount_raw is string
            discount_digits = "".join(filter(str.isdigit, str(discount_raw)))
            discount = int(discount_digits) if discount_digits else 0
            
            price_raw = g.get("final_price") or 0
            is_free = price_raw == "0" or price_raw == 0
            
            trending_games.append({
                "app_id": g.get("id"),
                "name": g.get("name"),
                "header_image": hero_image_url(g.get("id"), g.get("image")),
                "image_candidates": build_image_candidates(g.get("id")),
                "analyze_url": f"/search?app_id={g.get('id')}",
                "price_formatted": "Free" if is_free else format_price(price_raw),
                "discount": discount
            })
    except Exception:
        import logging
        logging.getLogger(__name__).exception("Failed to fetch trending games for search page")
        trending_games = []

    return render_template("search.html", trending_games=trending_games)


@pages_bp.route("/about")
def about_page():
    return render_template("about.html")


@pages_bp.route("/privacy")
def privacy_page():
    return render_template("privacy.html")