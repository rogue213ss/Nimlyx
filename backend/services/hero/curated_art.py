"""
Optional curated artwork for hero-slide games.

Steam's own assets (header_image, library_hero, capsule, etc.) are
fine for search results and browse grids, but the hero carousel is
supposed to look better than Steam's own store page -- so for the
small set of "trophy" titles that actually get featured, it's worth
reaching past Steam's CDN entirely instead of hoping library_hero
happens to exist and look cinematic.

Two sources, checked in order:

  1. A small, hand-maintained map of app_id -> confirmed-working
     artwork URL (CURATED_HERO_ART below). Meant to stay small --
     20 to 50 entries, only for games likely to actually get
     featured -- not a general replacement for Steam's own assets.
     Nothing here is verified at request time (same rule as
     everywhere else in this app: see image-upgrade.js), so only add
     URLs you've personally confirmed load.

  2. IGDB artwork, fetched live and cached, once IGDB credentials are
     configured. Stubbed out below (fetch_igdb_hero_art returns None
     until IGDB_CLIENT_ID / IGDB_CLIENT_SECRET exist), so this module
     works today with zero setup and degrades to the guaranteed Steam
     fallback the caller already has on hand.
"""

import os
import time

import requests

# ----------------------------------------------------------------
# 1. Hand-curated overrides. Keyed by Steam app_id (string).
#    Example:
#        CURATED_HERO_ART = {
#            "570": "https://images.igdb.com/igdb/image/upload/t_1080p/xxxxx.jpg",
#        }
# ----------------------------------------------------------------
CURATED_HERO_ART = {
    # intentionally empty -- add confirmed-working URLs here as
    # featured games come up, or let fetch_igdb_hero_art() below
    # populate this automatically once IGDB credentials are set.
}


def get_curated_hero_image(app_id):
    if app_id is None:
        return None
    return CURATED_HERO_ART.get(str(app_id))


# ----------------------------------------------------------------
# 2. IGDB integration point (not wired up yet -- no credentials).
# ----------------------------------------------------------------
IGDB_TOKEN_URL = "https://id.twitch.tv/oauth2/token"
IGDB_API_BASE = "https://api.igdb.com/v4"

_igdb_token_cache = {"token": None, "expires_at": 0}
_igdb_artwork_cache = {}  # {app_id: (url_or_None, expires_at)}
_IGDB_ARTWORK_CACHE_TTL = 60 * 60 * 24  # 24h, artwork rarely changes


def _igdb_credentials():
    client_id = os.environ.get("IGDB_CLIENT_ID")
    client_secret = os.environ.get("IGDB_CLIENT_SECRET")
    if not client_id or not client_secret:
        return None
    return client_id, client_secret


def _igdb_access_token():
    """Twitch app-access-token flow IGDB sits on top of. Cached until
    shortly before expiry so this isn't a network call on every hero
    build."""
    creds = _igdb_credentials()
    if not creds:
        return None

    now = time.time()
    if _igdb_token_cache["token"] and _igdb_token_cache["expires_at"] > now:
        return _igdb_token_cache["token"]

    client_id, client_secret = creds
    try:
        resp = requests.post(
            IGDB_TOKEN_URL,
            params={
                "client_id": client_id,
                "client_secret": client_secret,
                "grant_type": "client_credentials",
            },
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
    except (requests.exceptions.RequestException, ValueError):
        return None

    token = data.get("access_token")
    expires_in = data.get("expires_in", 0)
    if not token:
        return None

    _igdb_token_cache["token"] = token
    _igdb_token_cache["expires_at"] = now + max(expires_in - 60, 0)
    return token


def fetch_igdb_hero_art(app_id):
    """Resolve a Steam app_id -> IGDB artwork URL, live. Returns None
    (never raises) whenever IGDB isn't configured, the game isn't
    found, or the request fails -- callers always have a safe
    fallback to use instead.

    Not wired into resolve_hero_image() with a live call per request;
    it's cached per app_id for _IGDB_ARTWORK_CACHE_TTL so a repeat
    hero build doesn't re-hit IGDB for the same game.
    """
    if not app_id:
        return None

    now = time.time()
    cached = _igdb_artwork_cache.get(app_id)
    if cached and cached[1] > now:
        return cached[0]

    token = _igdb_access_token()
    creds = _igdb_credentials()
    if not token or not creds:
        return None

    client_id, _ = creds
    headers = {"Client-ID": client_id, "Authorization": f"Bearer {token}"}

    try:
        # Steam app_id -> IGDB game id via IGDB's external_games table
        # (category 1 = Steam).
        lookup = requests.post(
            f"{IGDB_API_BASE}/external_games",
            headers=headers,
            data=f'fields game; where uid = "{app_id}" & category = 1;',
            timeout=10,
        )
        lookup.raise_for_status()
        matches = lookup.json()
        if not matches:
            _igdb_artwork_cache[app_id] = (None, now + _IGDB_ARTWORK_CACHE_TTL)
            return None
        igdb_game_id = matches[0].get("game")

        artwork_resp = requests.post(
            f"{IGDB_API_BASE}/artworks",
            headers=headers,
            data=f"fields image_id; where game = {igdb_game_id}; limit 1;",
            timeout=10,
        )
        artwork_resp.raise_for_status()
        artworks = artwork_resp.json()
    except (requests.exceptions.RequestException, ValueError, KeyError):
        return None

    if not artworks or not artworks[0].get("image_id"):
        url = None
    else:
        image_id = artworks[0]["image_id"]
        url = f"https://images.igdb.com/igdb/image/upload/t_1080p/{image_id}.jpg"

    _igdb_artwork_cache[app_id] = (url, now + _IGDB_ARTWORK_CACHE_TTL)
    return url


def resolve_hero_image(app_id, guaranteed_fallback):
    """Priority for hero-slide art: curated override > IGDB (only if
    credentials are configured) > the guaranteed Steam image the
    caller already has on hand. Always returns something as long as
    guaranteed_fallback isn't None -- never a guess, never blank."""
    curated = get_curated_hero_image(app_id)
    if curated:
        return curated

    igdb = fetch_igdb_hero_art(app_id)
    if igdb:
        return igdb

    return guaranteed_fallback
