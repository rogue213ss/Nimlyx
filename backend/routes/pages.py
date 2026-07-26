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
import time
import requests
from flask import Blueprint, render_template

from region import get_region_code
from steam import fetch_browse_category, fetch_verified_new_releases
from formatters import format_price
from services.hero.builder import build_hero_lineup
from services.hero.picks import select_worth_buying
from steam_images import default_header_image, build_image_candidates

pages_bp = Blueprint("pages", __name__)
logger = logging.getLogger(__name__)

# ----------------------------------------------------------------
# Hero-lineup cache — STOPGAP, not the real design. See prior note:
# build_hero_lineup() makes ~2 live Steam calls per surviving
# candidate; this in-memory per-region TTL cache stands in for a
# real scheduled build (Phase 4) until services/builds/ exists.
# ----------------------------------------------------------------
_HERO_CACHE = {}
_HERO_CACHE_TTL_SECONDS = 900  # 15 minutes


def _get_hero_lineup(cc):
    cached = _HERO_CACHE.get(cc)
    if cached and (time.time() - cached["fetched_at"]) < _HERO_CACHE_TTL_SECONDS:
        return cached["selected"], cached["all_candidates"]

    selected, all_candidates = build_hero_lineup(cc=cc)
    _HERO_CACHE[cc] = {
        "selected": selected,
        "all_candidates": all_candidates,
        "fetched_at": time.time(),
    }
    return selected, all_candidates


# ----------------------------------------------------------------
# New-releases cache — same STOPGAP reasoning as the hero cache
# above. fetch_verified_new_releases() makes one live appdetails
# call per candidate (up to candidate_pool of them) purely to check
# each one's real release date; that's real API cost worth paying
# once per TTL window, not on every homepage hit.
# ----------------------------------------------------------------
_NEW_RELEASES_CACHE = {}
_NEW_RELEASES_CACHE_TTL_SECONDS = 1800  # 30 minutes


def _get_verified_new_releases(cc):
    cached = _NEW_RELEASES_CACHE.get(cc)
    if cached and (time.time() - cached["fetched_at"]) < _NEW_RELEASES_CACHE_TTL_SECONDS:
        return cached["games"]

    games = fetch_verified_new_releases(limit=5, cc=cc)
    _NEW_RELEASES_CACHE[cc] = {
        "games": games,
        "fetched_at": time.time(),
    }
    return games


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
                    "analyze_url": f"/search?q={g.get('name', '')}",
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
                "analyze_url": f"/search?q={g.get('name', '')}",
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
                "analyze_url": f"/search?q={g['name']}",
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
        )

    except requests.exceptions.RequestException:
        logger.exception("Homepage request failed entirely — Steam unreachable or timed out.")
        return render_template(
            "index.html",
            featured_games=[],
            nimlyx_picks=[],
            trending_games=[],
            new_release_games=[],
        )


@pages_bp.route("/discover")
def discover():
    return render_template("discover.html")


@pages_bp.route("/search")
def search_page():
    return render_template("search.html")