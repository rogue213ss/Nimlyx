"""
steam_images.py — Steam artwork helpers for Nimlyx.

Guaranteed vs. candidate, two different jobs:

    default_header_image() / a raw appdetails header_image  ->
        the ONE thing guaranteed to load. Render this immediately,
        server-side, every time. No verification needed or possible
        to skip — Steam serves it for every listed app ID.

    build_image_candidates()  ->
        cheap, UNVERIFIED higher-res URLs (library hero, portrait
        capsule, etc.), built from string formatting only — no HTTP
        call, no guarantee any of them actually exist. These are
        never sent straight to an <img src>. The frontend
        (static/js/image-upgrade.js) tests each one with a real
        Image() load and only swaps it in on a genuine onload,
        falling back to the guaranteed image on onerror. See that
        file for the client half of this contract.

The functions below this point (fetch_app_artwork, get_cached_artwork,
pick_best_artwork, get_artwork_by_name) are the OLDER approach this
replaced: the backend guessing which asset "wins" and serving that
guess directly, verified (if at all) with a server-side HEAD request.
That pattern doubled request volume on card grids and still shipped
unverified URLs to <img> tags whenever verify_library_hero was left
off. Nothing in the app currently calls them — kept around only in
case a genuinely low-volume, single-lookup context (e.g. one
analyze-page fetch) ever wants a single richer appdetails call
server-side. Prefer default_header_image() + build_image_candidates()
for anything rendering more than one card.
"""

import time
import requests
from steam import get_appdetails, fetch_storesearch_api, _safe_steam_get



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
    nothing but a string format.

    Deliberately STEAM_CDN, not STEAM_LIBRARY_CDN: header.jpg under
    STEAM_LIBRARY_CDN (the newer store_item_assets pipeline) does NOT
    exist for every app -- older or smaller listings frequently 404
    there. The classic STEAM_CDN path is the one Steam has generated
    for every store listing since the page was created, which is what
    "guaranteed" actually requires here."""
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
        resp = _safe_steam_get(url, method="HEAD", timeout=timeout, allow_redirects=True)
        return resp.status_code == 200
    except requests.exceptions.RequestException:
        return False


def build_image_candidates(app_id, orientation="landscape", fallback_image=None):
    """Cheap, UNVERIFIED higher-resolution candidate URLs, built purely
    from Steam's CDN naming convention -- zero HTTP calls made here.

    None of these are guaranteed to exist (library_hero in particular
    frequently 404s for games without custom library art). That's the
    point: they're candidates, not a src. The frontend tries each one
    with a real Image() load, and only swaps it in on a genuine
    onload -- see static/js/image-upgrade.js. The guaranteed
    header_image / default_header_image() stays on screen the whole
    time these are being probed, so a card never shows broken art
    while waiting, and never shows it at all if every candidate 404s.

    `orientation` controls candidate ORDER, not which URLs exist.
    image-upgrade.js just picks the first candidate that loads, with
    no idea what shape of box it'll be cropped into -- so for a tall
    slot (a portrait card, or Trending's full-height #1 feature),
    putting the ultra-wide library_hero.jpg (~3:1 panoramic) first
    was actively the worst choice: object-fit:cover was cramming a
    wide banner into a tall box, cropping out most of the actual
    artwork and any character/subject positioned off-center in the
    source image. "landscape" (default) keeps the original order for
    every existing wide/landscape-slot caller (Hero, Deals, New
    Releases, Trending's compact list rows). "portrait" puts
    library_600x900.jpg (a real 2:3 portrait asset) first instead."""
    if not app_id:
        return []
        
    header = default_header_image(app_id)
    
    landscape_order = [
        f"{STEAM_LIBRARY_CDN}/{app_id}/library_hero.jpg",
        f"{STEAM_LIBRARY_CDN}/{app_id}/library_600x900.jpg",
        f"{STEAM_CDN}/{app_id}/capsule_616x353.jpg",
        header,
    ]
    if orientation == "portrait":
        candidates = [
            f"{STEAM_LIBRARY_CDN}/{app_id}/library_600x900.jpg",
            f"{STEAM_CDN}/{app_id}/capsule_616x353.jpg",
            f"{STEAM_LIBRARY_CDN}/{app_id}/library_hero.jpg",
            header,
        ]
    else:
        candidates = landscape_order

    if fallback_image:
        candidates.append(fallback_image)
        
    return candidates


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
        response = _session.get(
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
        response = _session.get(
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