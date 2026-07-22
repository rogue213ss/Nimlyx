"""
steam_images.py — premium Steam artwork pipeline for Nimlyx.

    App ID -> Steam App Details API -> every artwork asset
           -> cached -> best one picked per placement -> sent to frontend

The backend decides which image wins: get_cached_artwork() returns
every raw field PLUS a ready-to-use "best_image", so a template or
discover.js never has to choose between large_image/header_image/
library_capsule itself — it just reads game.best_image.

Drop this file next to app.py. Nothing in app.py has to change for it
to work — wire it in wherever the app is currently doing manual URL
patching (search app.py for "capsule_231x87" and "library_hero.jpg";
those are the two spots this replaces).
"""

import time
import requests

STEAM_APPDETAILS_URL = "https://store.steampowered.com/api/appdetails"
STEAM_STORESEARCH_URL = "https://store.steampowered.com/api/storesearch/"
STEAM_CDN = "https://cdn.akamai.steamstatic.com/steam/apps"
STEAM_LIBRARY_CDN = "https://shared.akamai.steamstatic.com/store_item_assets/steam/apps"

# Artwork almost never changes after a game ships, so a long TTL is
# safe — this is the "Cache it" step in the pipeline.
ARTWORK_CACHE_TTL_SECONDS = 60 * 60 * 24  # 24h
_artwork_cache = {}  # {app_id: (artwork_dict, expires_at_epoch_seconds)}


def default_header_image(app_id):
    """Steam's classic store header image (460x215) — built straight from
    the CDN naming convention, same as capsule_small/capsule_large below.
    No API call required, so unlike best_image (which needs appdetails to
    succeed), this is available even when Steam's appdetails endpoint is
    down, slow, or rate-limited. This is the actual "100% guaranteed"
    fallback: every listed game has this asset, and getting it costs
    nothing but a string format."""
    if not app_id:
        return None
    return f"{STEAM_CDN}/{app_id}/header.jpg"


def _asset_exists(url, timeout=3):
    """Cheap existence check for library_hero — the one asset Steam
    doesn't build for every game. OFF by default (see
    verify_library_hero below): a Discover page rendering 100 cards
    would otherwise fire 100 appdetails calls *and* 100 HEAD checks,
    doubling the request count for one response. Only turn this on
    for a low-volume path (e.g. a single analyze-page lookup) where
    an extra round trip doesn't matter."""
    try:
        resp = requests.head(url, timeout=timeout, allow_redirects=True)
        return resp.status_code == 200
    except requests.exceptions.RequestException:
        return False


def fetch_app_artwork(app_id, verify_library_hero=False):
    """Steam App Details API -> every artwork asset available for one
    game, in a single shape. header_image/background come straight
    from appdetails' own JSON (most reliable — Steam is telling you
    directly). The capsule and library sizes aren't in that JSON, so
    they're built from Steam's CDN naming convention instead — the
    same trick this app already uses for library_hero.jpg, just
    applied consistently instead of hand-replacing capsule strings.

    library_hero isn't guaranteed to exist for every game, but by
    default this sends the constructed URL unverified — one appdetails
    call per game instead of two. Point <img> tags using it at the
    frontend's own onerror fallback (e.g. onerror="this.src=
    header_image") rather than paying for a server-side HEAD check on
    every card. Pass verify_library_hero=True only for low-volume,
    one-off lookups where an extra request doesn't matter."""
    if not app_id:
        return None

    try:
        response = requests.get(
            STEAM_APPDETAILS_URL,
            params={"appids": app_id, "l": "english"},
            timeout=10,
        )
        response.raise_for_status()
        entry = response.json().get(str(app_id))
    except (requests.exceptions.RequestException, ValueError):
        return None

    if not entry or not entry.get("success"):
        return None

    raw = entry.get("data") or {}

    library_hero_url = f"{STEAM_LIBRARY_CDN}/{app_id}/library_hero.jpg"
    if verify_library_hero and not _asset_exists(library_hero_url):
        library_hero_url = None

    return {
        "capsule_small": f"{STEAM_CDN}/{app_id}/capsule_231x87.jpg",
        "capsule_large": f"{STEAM_CDN}/{app_id}/capsule_616x353.jpg",
        "header_image": raw.get("header_image"),
        "background": raw.get("background_raw") or raw.get("background"),
        "library_hero": library_hero_url,          # unverified unless asked; may 404
        "library_capsule": f"{STEAM_LIBRARY_CDN}/{app_id}/library_600x900.jpg",  # portrait
    }


def get_cached_artwork(app_id, use_case="discover", verify_library_hero=False):
    """Same as fetch_app_artwork, but skips Steam entirely on repeat
    lookups within ARTWORK_CACHE_TTL_SECONDS, and adds a ready-to-use
    best_image field so the frontend never has to choose between
    large_image/header_image/library_capsule itself — it just reads
    game.best_image. The cache stores only the raw fields (the
    expensive part); best_image is picked fresh per call from that
    cached data, so requesting the same app_id for two different
    placements (say, discover then analyze) doesn't cost a second
    Steam lookup, just a second cheap dict pick.

    Plain in-process dict for now, matching how the rest of app.py
    works today — swap the two lines marked below for Flask-Caching/
    Redis later without touching any caller."""
    now = time.time()
    cached = _artwork_cache.get(app_id)
    if cached and cached[1] > now:
        raw = cached[0]                                           # <- cache read
    else:
        raw = fetch_app_artwork(app_id, verify_library_hero=verify_library_hero)
        if not raw:
            return None
        _artwork_cache[app_id] = (raw, now + ARTWORK_CACHE_TTL_SECONDS)  # <- cache write

    return {**raw, "best_image": pick_best_artwork(raw, use_case)}


def pick_best_artwork(artwork, use_case="discover"):
    """'Choose the best one' — a fallback chain per placement, matching
    the breakdown you gave:
        homepage -> wide banner      (library_hero first)
        discover -> premium hero     (portrait library capsule first)
        analyze  -> background hero  (background first)
    Always falls through to header_image last, since that's the one
    field Steam guarantees for every listed game."""
    if not artwork:
        return None

    chains = {
        "homepage": ("library_hero", "background", "capsule_large", "header_image"),
        "discover": ("library_capsule", "header_image", "capsule_large"),
        "analyze": ("background", "library_hero", "header_image"),
    }
    for field in chains.get(use_case, ("header_image",)):
        if artwork.get(field):
            return artwork[field]
    return None


def get_artwork_by_name(game_name, use_case="discover", verify_library_hero=False):
    """The full pipeline straight from your diagram: Steam Search ->
    App ID -> artwork. Mirrors the same storesearch call find_game()
    already makes, so this is a drop-in for anywhere you only have a
    game name, not an app_id, on hand."""
    try:
        response = requests.get(
            STEAM_STORESEARCH_URL,
            params={"term": game_name, "l": "english", "cc": "US"},
            timeout=10,
        )
        response.raise_for_status()
        items = response.json().get("items", [])
    except (requests.exceptions.RequestException, ValueError):
        return None

    if not items:
        return None

    app_id = items[0]["id"]
    return get_cached_artwork(app_id, use_case=use_case, verify_library_hero=verify_library_hero)