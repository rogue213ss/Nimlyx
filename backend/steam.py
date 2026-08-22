"""
All functions that talk to Steam directly: scraping search-result HTML
and calling Steam's public JSON endpoints (appdetails, storesearch).
Used by the /api/browse, /api/verdicts, /api/discover, /api/game,
/api/find, /api/search routes and the homepage.
"""
import re
import time
import threading
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor

import requests
from bs4 import BeautifulSoup

from services.analysis.wilson_score import compute_nimlyx_score

HARDWARE_KEYWORDS = ["steam deck", "steam controller", "steam machine", "steam link"]

# Steam's store endpoints frequently 403 requests with no browser-like
# User-Agent (especially from cloud/datacenter IPs, e.g. Render).  A
# bare `_session.get(url)` with no headers was silently turning into a
# RequestException on every homepage load, which routes/pages.py's
# top-level except catches and renders as an all-sections-empty
# homepage. Route every Steam call through this shared session so
# they all send a normal browser UA instead of Python's default.
_session = requests.Session()
_session.headers.update({
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
})


def _is_single_app_id(app_id):
    """Steam's search results HTML mixes genuine single-game rows in
    with franchise/bundle rows -- a "Witcher 3 + both expansions"
    pack, for example -- and those bundle rows carry a comma-joined
    data-ds-appid like "292030,378649,378648" instead of one real ID.
    Every card contract in this app represents exactly one game, so a
    multi-ID row can't be honestly rendered as one; every scrape site
    below should skip it rather than pass the raw joined string
    downstream, where it silently becomes a broken
    /search?app_id=292030,378649,378648 URL with nothing behind it."""
    return bool(app_id) and "," not in app_id


def _is_genuine_app_row(row, app_id):
    """A second, independent check on top of _is_single_app_id --
    catches the case that check can't: a *single*, non-comma
    data-ds-appid that still isn't a real standalone app. Some
    edition/complete-collection listings on Steam's search page are
    packages ("subs") or bundles rather than a genuine app entry, and
    the observed behavior (see the "Complete Edition" 404 this
    guards against) is that data-ds-appid can carry a package-space
    ID that happens to collide with an unrelated real app_id -- so a
    lookup either 404s or, worse, silently loads the wrong game.

    The row's own href is a second, independent signal: Steam links
    genuine app rows to /app/<id>/..., but bundles/packages link to
    /bundle/<id>/... or /sub/<id>/... instead. Requiring the href to
    actually say /app/ catches rows data-ds-appid alone can't."""
    if not _is_single_app_id(app_id):
        return False
    href = row.get("href") or ""
    return "/app/" in href


# ==========================================================
# SHORT-LIVED RESPONSE CACHE — real data only, never a substitute
# for it.
#
# This does NOT fabricate, guess, or serve placeholder data. It
# stores the exact real response Steam returned, keyed by the exact
# request that was made, for a few minutes. Two callers asking for
# the same thing seconds apart (e.g. the homepage's Trending section
# and the hero engine's candidate pool both scraping "topsellers" on
# the SAME request) get the SAME real answer instead of two identical
# live Steam round-trips -- the truthfulness of the data is unchanged,
# only the redundant network cost is removed.
# ==========================================================

_response_cache = {}
_response_cache_lock = threading.Lock()


def _cache_get(key, ttl_seconds):
    with _response_cache_lock:
        entry = _response_cache.get(key)
        if entry:
            actual_ttl = entry.get("ttl_override") or ttl_seconds
            if (time.time() - entry["at"]) < actual_ttl:
                return entry["value"]
        return None


def _cache_set(key, value, ttl_override=None):
    with _response_cache_lock:
        _response_cache[key] = {"value": value, "at": time.time(), "ttl_override": ttl_override}


_inflight_requests = {}
_inflight_requests_lock = threading.Lock()

def _execute_deduplicated(cache_key, ttl_seconds, fetch_func, failure_ttl=60):
    """
    Prevents multiple threads from simultaneously requesting the exact
    same data from Steam. If Steam fails (e.g. 429), it caches the
    failure briefly to prevent a retry storm.

    NOTE on the synchronization primitive: this uses threading.Event,
    not threading.Condition + wait()/notify_all(). A Condition-based
    version of this exact pattern was tried first and had a real,
    reproducible deadlock: Condition.wait() only wakes a thread that
    is ALREADY blocked at the moment notify_all() runs. If the
    "fetcher" thread finishes and calls notify_all() before a
    "waiter" thread has reached its own wait() call (entirely
    possible under normal OS thread-scheduling jitter -- confirmed
    with a deliberately delayed waiter thread, no artificial fault
    injection needed), that waiter never gets woken and hangs
    forever, since the real code calls wait() with no timeout. Under
    Flask's ThreadPoolExecutor(max_workers=8), one lost wakeup
    permanently strands a pool worker -- the exact class of failure
    this cache was built to prevent, just moved from "rate limit
    spiral" to "silent thread starvation."

    threading.Event doesn't have this failure mode: Event.set() marks
    a persistent flag, and Event.wait() checks that flag before
    blocking -- so a waiter that arrives AFTER set() was already
    called still returns immediately instead of waiting on a signal
    that already happened and will never repeat.
    """
    cached = _cache_get(cache_key, ttl_seconds)
    if cached is not None:
        if cached == "RATE_LIMITED_OR_FAILED":
            return None
        return cached

    we_fetch = False
    with _inflight_requests_lock:
        entry = _inflight_requests.get(cache_key)
        if entry is None:
            entry = {"event": threading.Event(), "result": None}
            _inflight_requests[cache_key] = entry
            we_fetch = True

    if we_fetch:
        try:
            result = fetch_func()
            if result is None:
                _cache_set(cache_key, "RATE_LIMITED_OR_FAILED", ttl_override=failure_ttl)
            else:
                _cache_set(cache_key, result)
            entry["result"] = result
            return result
        finally:
            entry["event"].set()
            with _inflight_requests_lock:
                _inflight_requests.pop(cache_key, None)
    else:
        entry["event"].wait()
        # entry["result"] holds the RAW fetch_func() return value (not
        # the "RATE_LIMITED_OR_FAILED" cache sentinel, which only ever
        # lives in _response_cache) -- None here already means exactly
        # what it means for the fetcher's own return value: the fetch
        # failed and this caller gets no result, same as the fetcher
        # got.
        return entry["result"]


# ==========================================================
# ASYNC FEED CACHE — serve-stale-while-revalidating
#
# Shared generic pattern for the homepage endless feed.
# Guarantees that any cached row (even if stale) returns instantly
# without blocking the request. A background thread updates the
# cache for the next visitor.
# A BoundedSemaphore ensures we never fire more than 5 parallel
# background Steam scrapes across the entire application.
# ==========================================================
_async_feed_cache = {}
_async_feed_lock = threading.Lock()
_async_feed_in_progress = set()
_steam_scrape_semaphore = threading.BoundedSemaphore(5)

def _rebuild_async_feed(cache_key, fetch_func):
    try:
        # Acquire semaphore to protect Steam from simultaneous overwhelming requests
        with _steam_scrape_semaphore:
            data = fetch_func()
        with _async_feed_lock:
            _async_feed_cache[cache_key] = {"data": data, "fetched_at": time.time()}
    except Exception:
        # If scrape fails, silently leave the stale cache so we don't break the UI
        pass
    finally:
        with _async_feed_lock:
            _async_feed_in_progress.discard(cache_key)

def serve_stale_or_rebuild(cache_key, fetch_func, ttl_seconds=1800):
    """
    Returns (data, is_building).
    If cache hit (fresh): returns data instantly.
    If cache hit (stale): kicks off background thread, returns stale data instantly.
    If cache miss (cold): kicks off background thread, returns None.
    """
    with _async_feed_lock:
        cached = _async_feed_cache.get(cache_key)
        building = cache_key in _async_feed_in_progress

    if cached is not None:
        is_stale = (time.time() - cached["fetched_at"]) >= ttl_seconds
        if is_stale and not building:
            with _async_feed_lock:
                _async_feed_in_progress.add(cache_key)
            threading.Thread(target=_rebuild_async_feed, args=(cache_key, fetch_func), daemon=True).start()
        return cached["data"]

    # Cold miss
    if not building:
        with _async_feed_lock:
            _async_feed_in_progress.add(cache_key)
        threading.Thread(target=_rebuild_async_feed, args=(cache_key, fetch_func), daemon=True).start()
    
    return None


# ==========================================================
# DISCOVER WIZARD — filter mappings
# Steam's own tag IDs, used to translate the wizard's plain-English
# answers (from discover.html / discover.js) into the store's search
# query params. Tag IDs are Steam's public, stable category IDs.
# ==========================================================

GENRE_TAG_IDS = {
    "action": 19,
    "fantasy": 1684,
    "horror": 1667,
    "rpg": 122,
    "racing": 699,
    "puzzle": 1664,
    "simulation": 599,
    "strategy": 9,
}

PLAYWITH_TAG_IDS = {
    # "solo" intentionally has no tag — it's the default when no
    # multiplayer tag is applied.
    "co-op": 1685,
    "online-multiplayer": 3859,
    "local-co-op": 3843,
}

BUDGET_MAX_PRICE_CENTS = {
    "free": 0,
    "under-10": 1000,
    "under-20": 2000,
    "under-40": 4000,
    "any-price": None,
}

# ==========================================================
# NIMLYX TRADITION #001
#
# We assumed Steam could filter games by review score.
#
# It can't.
#
# Steam Search doesn't expose any review-score parameter.
# The only reliable solution is to extract the review
# percentage ourselves from each search result's tooltip
# and filter the games manually.
#
# Lesson:
# If the API doesn't provide a feature,
# build it yourself.
# ==========================================================

# Steam doesn't expose a review-score query parameter.
# We post-filter results using the review percentage
# extracted from each result's tooltip. Thresholds match
# Steam's own review categories.
REVIEW_SCORE_MIN_PERCENT = {
    "any": 0,
    "positive": 70,
    "very-positive": 80,
    "overwhelmingly-positive": 95,
}

# ==========================================================
# NIMLYX TRADITION #002
#
# We wanted a Steam Deck filter.
#
# Steam didn't.
#
# There is no official Steam Search parameter for
# "Steam Deck Verified" or "Steam Deck Playable."
#
# After researching Steam's search behavior, we found
# that Windows titles are the closest practical proxy,
# since most Deck-compatible games run through Proton.
#
# Is it perfect?
# No.
#
# Is it the best available without Steam's own Deck API?
# Yes.
#
# Lesson:
# Sometimes the best solution isn't perfect—
# it's the best one the platform allows.
# ==========================================================

# Steam Search has no dedicated Steam Deck filter.
# Windows titles are used as the closest practical proxy,
# since most Deck-compatible games run through Proton.
PLATFORM_OS_PARAM = {
    "windows": "win",
    "linux": "linux",
    "macos": "mac",
    "steam-deck": "win",
}

# How many rows fetch_games_by_credit() (More From Developer/
# Publisher) requests from Steam in a single /search/results/ request.
# Same number fetch_discover_games() already uses successfully -- one
# request, no true start= pagination needed, Steam's search page
# handles a buffer this size fine in one round trip. Kept as a shared
# constant (not folded inline) so both places asking "how big can one
# request safely be" stay in sync if that ever needs revisiting.
_CREDIT_GAMES_FETCH_BUFFER = 100



# ==========================================================
# SHARED SCRAPER — used by /api/browse, /api/verdicts, and home()
# ==========================================================

def fetch_browse_category(category, count=25, cc="US"):
    # Short-lived cache keyed by the exact request. Trending (in
    # routes/pages.py) and the hero engine's candidate pool (in
    # services/hero/pool.py) both independently call this for
    # "topsellers" on the SAME homepage request -- this makes the
    # second caller reuse the first's real, already-fetched result
    # instead of scraping Steam twice for identical data.
    cache_key = ("browse_category", category, count, cc)

    def _fetch():
        url = (
            f"https://store.steampowered.com/search/results/"
            f"?query=&start=0&count={count}&filter={category}&category1=998&cc={cc}&l=english"
        )
        try:
            response = _session.get(url, timeout=10)
            response.raise_for_status()
        except (requests.exceptions.RequestException, ValueError):
            return None

        soup = BeautifulSoup(response.text, "html.parser")
        games = soup.find_all("a", class_="search_result_row")
        cleaned = []
        for game in games:
            app_id = game.get("data-ds-appid")
            title = game.find("span", class_="title")
            name = title.text.strip() if title else "Unknown"
            if any(keyword in name.lower() for keyword in HARDWARE_KEYWORDS):
                continue
            img = game.find("img")
            image = img["src"] if img and img.get("src") else None
            if not _is_genuine_app_row(game, app_id) or not image:
                continue
            price_div = game.find("div", class_="search_price_discount_combined")
            final_price_el = game.find("div", class_="discount_final_price")
            is_free = final_price_el and "free" in final_price_el.get("class", [])
            final_price = "0" if is_free else (price_div.get("data-price-final") if price_div else None)
            original_price_span = game.find("div", class_="discount_original_price")
            original_price = original_price_span.text.strip() if original_price_span else None
            discount_span = game.find("div", class_="discount_pct")
            discount_percent = discount_span.text.strip() if discount_span else None
            platforms_div = game.find("div", class_="search_platforms")
            platforms = []
            if platforms_div:
                for span in platforms_div.find_all("span", class_="platform_img"):
                    classes = span.get("class", [])
                    for cls in classes:
                        if cls in ("win", "mac", "linux"):
                            platforms.append(cls)
            cleaned.append({
                "id": app_id,
                "name": name,
                "image": image,
                "final_price": final_price,
                "original_price": original_price,
                "discount_percent": discount_percent,
                "review_percent": parse_review_percent(game),
                "review_summary": parse_review_summary(game),
                "platforms": platforms
            })
        return cleaned

    result = _execute_deduplicated(cache_key, 180, _fetch, failure_ttl=60)
    return result if result is not None else []


def fetch_budget_catalog_sweep(max_price_cents, count=100, cc="US"):
    """Scrapes Steam's catalog filtered to `category1=998` (base games
    only) + a price ceiling, with NO other filter (no tags/os) --
    a broad, unbiased sweep of everything Steam sells under that
    price, not a specific genre or platform slice.

    Built for services/hero/potato_pool.py: the hero engine's
    candidate pool (build_candidate_pool() in services/hero/pool.py)
    is deliberately today's top sellers/new releases/specials, which
    structurally excludes almost every game that would actually land
    in Nimlyx's Potato ecosystem (🥔/🔧/💀) -- those games are, by the
    nature of what that ecosystem classifies, old or budget titles,
    not this week's trending list. A full-price new AAA game
    essentially never sits permanently under $10-20 (only temporarily
    via a special, which the hero pool already covers), so filtering
    by a low, PERMANENT price ceiling reliably surfaces older/smaller
    titles instead.

    Reuses `_scrape_search_results()` -- the exact same parsing
    `fetch_discover_games()` already relies on -- so this doesn't
    duplicate that ~80-line scrape/parse block or risk it drifting out
    of sync.
    """
    cache_key = ("budget_catalog_sweep", max_price_cents, count, cc)
    
    def _fetch():
        params = {
            "query": "",
            "start": 0,
            "count": count,
            "category1": 998,
            "cc": cc,
            "l": "english",
        }
        if max_price_cents is not None:
            params["maxprice"] = max_price_cents / 100
        
        try:
            return _scrape_search_results(params, cc)
        except (requests.exceptions.RequestException, ValueError):
            return None

    result = _execute_deduplicated(cache_key, 1800, _fetch, failure_ttl=60)
    return result if result is not None else []


def parse_review_percent(game_anchor):
    """Pulls the review percentage out of a search result row's tooltip,
    e.g. data-tooltip-html="87% of the 2,301 user reviews...". Returns
    None if Steam hasn't shown a review summary for that title yet."""
    summary = game_anchor.find("span", class_="search_review_summary")
    if not summary:
        return None

    tooltip = summary.get("data-tooltip-html", "")
    match = re.search(r"(\d{1,3})%", tooltip)
    return int(match.group(1)) if match else None


def parse_review_summary(game_anchor):
    """Pulls the textual review summary from the tooltip, e.g. "Very Positive".
    Returns None if missing."""
    summary = game_anchor.find("span", class_="search_review_summary")
    if not summary:
        return None

    tooltip = summary.get("data-tooltip-html", "")
    # Example: "Very Positive<br>87% of the..."
    if "<br>" in tooltip:
        return tooltip.split("<br>")[0].strip()
    return None


def _scrape_search_results(params, cc):
    """Shared core of Steam's search/results HTML scrape -- the request
    + BeautifulSoup parsing that used to live directly inside
    fetch_discover_games(). Pulled out so fetch_games_by_credit()
    (Sprint 4 Phase 3's developer/publisher lookups) can reuse the
    exact same parsing instead of a second copy of this ~80-line block
    that would silently drift from this one over time.

    Takes an already-built `params` dict so each caller stays in charge
    of its own filter params (tags/os/maxprice for Discover,
    developer/publisher for the game page) -- this function only owns
    the HTTP call and the row-by-row parsing, not what's being
    searched for."""
    url = "https://store.steampowered.com/search/results/"

    response = _session.get(url, params=params, timeout=10)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")

    rows = soup.find_all("a", class_="search_result_row")

    games = []

    for row in rows:
        app_id = row.get("data-ds-appid")

        title = row.find("span", class_="title")
        name = title.text.strip() if title else "Unknown"

        if any(keyword in name.lower() for keyword in HARDWARE_KEYWORDS):
            continue

        img = row.find("img")
        image = img["src"] if img and img.get("src") else None

        # ==========================================================
        # NIMLYX TRADITION #009
        #
        # "Some games are getting pics, some aren't" wasn't random.
        #
        # Steam mixes bundle/package rows and other non-standard
        # listing types into its own search results HTML alongside
        # regular single-app rows. Those rows either have no
        # data-ds-appid at all, or no real <img src>, or both — and
        # every one of them was getting pushed into the results list
        # anyway. Downstream, a missing app_id means
        # default_header_image() can't build even the guaranteed CDN
        # fallback (it needs a real app_id), and a missing image
        # means there's nothing to show at all. Both landed on the
        # frontend's own broken-image fallback, which — separately —
        # pointed at a PNG file that was never actually created.
        # Two silent failures stacked on each other looked like
        # "random" cards missing pictures.
        #
        # The fix: a row that has neither a usable app_id nor a
        # usable image isn't a card Nimlyx can honestly render —
        # skip it here instead of passing broken data downstream and
        # hoping a fallback catches it.
        #
        # Lesson:
        # A missing image bug is sometimes actually a missing app_id
        # bug wearing a different symptom.
        #
        # Battle Status:
        # Victory.
        # ==========================================================
        if not _is_genuine_app_row(row, app_id) or not image:
            continue

        small_image = image
        large_image = image.replace("capsule_231x87", "capsule_616x353")

        price_div = row.find("div", class_="search_price_discount_combined")
        final_price_el = row.find("div", class_="discount_final_price")
        is_free = final_price_el and "free" in final_price_el.get("class", [])
        final_price = "0" if is_free else (price_div.get("data-price-final") if price_div else None)

        original_price_span = row.find("div", class_="discount_original_price")
        original_price = original_price_span.text.strip() if original_price_span else None

        discount_span = row.find("div", class_="discount_pct")
        discount_percent = discount_span.text.strip() if discount_span else None

        # Steam marks each row's release date with a
        # "search_released" div (e.g. "21 Jun, 2023") -- used by
        # Discover's "Newest" sort (see formatters.sort_discover_games).
        # Reuses the existing parse_steam_release_date() parser (same
        # one fetch_new_release_candidates already relies on) rather
        # than a second date parser, and stores it as an ISO string
        # (JSON-safe) or None -- never a guess when Steam's own text
        # isn't one of the concrete formats that parser trusts.
        released_div = row.find("div", class_="search_released")
        release_date_obj = parse_steam_release_date(released_div.text.strip()) if released_div else None
        release_date = release_date_obj.isoformat() if release_date_obj else None

        # Platform icons -- Steam marks each supported OS with its own
        # <span class="platform_img win/mac/linux"> inside the row.
        # Not previously extracted here (Discover/credit-games callers
        # never needed it -- their cards don't show platform icons),
        # generalized in now that a caller (search) does. Best-effort:
        # if Steam's markup for this ever differs from what's assumed
        # here, this just quietly yields no icons for a row rather than
        # breaking anything -- nothing downstream depends on it being
        # present.
        platform_icons = row.find_all("span", class_="platform_img")
        platforms = {
            "windows": any("win" in (icon.get("class") or []) for icon in platform_icons),
            "mac": any("mac" in (icon.get("class") or []) for icon in platform_icons),
            "linux": any("linux" in (icon.get("class") or []) for icon in platform_icons),
        }

        games.append({
            "id": app_id,
            "name": name,
            "image": small_image,
            "large_image": large_image,
            "final_price": final_price,
            "original_price": original_price,
            "discount_percent": discount_percent,
            "review_percent": parse_review_percent(row),
            "review_summary": parse_review_summary(row),
            "platforms": platforms,
            "release_date": release_date,
        })

    return games


def fetch_discover_games(genre=None, play_with=None, budget=None, platform=None, count=100, cc="US"):
    """Scrapes Steam's search results using tag/price/os filters built
    from the discover wizard's answers. Review score isn't filterable
    server-side, so it's applied afterwards in the /api/discover route.

    count defaults to 100 (Steam's search page tops out comfortably
    there in one request) instead of the old 30, so a single scrape can
    back several pages of infinite scroll (12 → 24 → 36...) without
    re-hitting Steam's search endpoint on every "load more". This is a
    fixed-size buffer, not true unlimited pagination — if a filter
    combination has fewer than `count` raw matches, scrolling will
    eventually hit the real end of what's available rather than an
    artificial page boundary. Good enough for the wizard's five filters;
    would need Steam's own `start` paging to go further.

    NOTE: this function only scrapes and returns raw candidates — no
    per-game appdetails calls happen here anymore. Live price and
    artwork lookups happen later in discover_api, and only for the 12
    games on the page actually being shown, not the whole buffer."""

    # Same reasoning as fetch_browse_category's cache above: this is
    # Discover's most expensive uncached call, and it's now hit on
    # every debounced live-filter change (not just an explicit "Find
    # Games" click) — the exact same filter combination re-selected a
    # few minutes later, or picked by a different visitor, re-scraped
    # Steam from scratch every single time before this. 3 minutes
    # matches fetch_browse_category's TTL: short enough that a real
    # listing change still shows up quickly, long enough that the
    # rapid back-and-forth clicking a live filter UI invites is
    # answered from cache instead of Steam.
    cache_key = ("discover_games", genre, play_with, budget, platform, count, cc)

    def _fetch():
        tag_ids = []
        if genre in GENRE_TAG_IDS:
            tag_ids.append(GENRE_TAG_IDS[genre])
        if play_with in PLAYWITH_TAG_IDS:
            tag_ids.append(PLAYWITH_TAG_IDS[play_with])

        params = {
            "query": "",
            "start": 0,
            "count": count,
            "category1": 998,
            "cc": cc,
            "l": "english",
        }
        if tag_ids:
            params["tags"] = ",".join(str(t) for t in tag_ids)
        if platform in PLATFORM_OS_PARAM:
            params["os"] = PLATFORM_OS_PARAM[platform]
        if budget in BUDGET_MAX_PRICE_CENTS and BUDGET_MAX_PRICE_CENTS[budget] is not None:
            params["maxprice"] = BUDGET_MAX_PRICE_CENTS[budget] / 100

        try:
            return _scrape_search_results(params, cc)
        except (requests.exceptions.RequestException, ValueError):
            return None

    games = _execute_deduplicated(cache_key, 180, _fetch, failure_ttl=60)
    if games is None:
        games = []
    return games


def fetch_games_by_credit(field, value, exclude_app_id=None, count=10, cc="US"):
    """Sprint 4 Phase 3 -- "More From Developer" / "More From
    Publisher". Same Steam search/results scrape fetch_discover_games
    uses, just filtered by Steam's own developer=/publisher= facet
    params instead of tags/os/maxprice. field must be "developer" or
    "publisher"; value is the exact credit name off this game's own
    appdetails (e.g. game["developers"][0]).

    exclude_app_id drops the game currently being viewed out of its
    own "more like this" list -- Steam's own developer/publisher
    search naturally includes the game itself.

    count is the DISPLAY count returned to the caller (Sprint 4 spec's
    "6-10 games" for these carousels) -- it is NOT how many rows get
    requested from Steam. See _CREDIT_GAMES_FETCH_BUFFER below for why
    those are now two separate numbers.

    BUFFER FIX (was: single page, count+1 rows only): this used to ask
    Steam for exactly `count + 1` rows and never request more --for a
    prolific studio (e.g. Ubisoft, dozens of Steam titles) that meant
    "More From Developer" only ever had Steam's top ~10 results in
    that category to choose from, most of which aren't even that
    studio's own catalog once exclude_app_id and downstream filtering
    trim it further. This wasn't Steam under-returning or rate
    limiting -- it was this function never asking for more than one
    small page. Same _scrape_search_results() core, same
    /search/results/ endpoint that genuinely supports a larger
    single-request page size -- fetch_discover_games already proves
    this works (it requests up to 100 rows in ONE request, no true
    multi-page start= looping needed). This function now does the
    same: request a bigger buffer once, cache it, then slice to the
    caller's display count -- zero additional Steam calls per request,
    just a bigger single response.
    """
    if field not in ("developer", "publisher") or not value:
        return []

    # Buffer size is intentionally independent of `count` (and of the
    # cache key below) -- this means a developer carousel wanting 10
    # and, say, a future "See More" page wanting 30 both reuse the
    # exact same cached Steam response instead of triggering two
    # separate scrapes for the same developer/publisher.
    cache_key = ("credit_games", field, value, cc)

    def _fetch():
        params = {
            "query": "",
            "start": 0,
            "count": _CREDIT_GAMES_FETCH_BUFFER,
            "category1": 998,
            "cc": cc,
            "l": "english",
            field: value,
        }

        try:
            return _scrape_search_results(params, cc)
        except (requests.exceptions.RequestException, ValueError):
            return None

    games = _execute_deduplicated(cache_key, 86400, _fetch, failure_ttl=60)
    if games is None:
        games = []


    if exclude_app_id:
        games = [g for g in games if g.get("id") != str(exclude_app_id)]
    return games[:count]


def fetch_search_by_term(term, start=0, count=30, cc="US"):
    """Search's backend, replacing storesearch (see the /api/search-
    results docstring in routes/game.py for the full history -- in
    short: storesearch was confirmed, empirically, to ignore &start=
    entirely and just re-serve the same top-10 relevance set no
    matter the offset, so a broad franchise search could never see
    past it). Same /search/results/ HTML scrape fetch_discover_games
    and fetch_games_by_credit already use, just driven by Steam's own
    free-text `term=` facet instead of tags/developer/publisher.

    category1=998 (Games only) is Steam's own server-side filter --
    DLC/soundtracks/software never come back in the response at all,
    and _is_genuine_app_row (see its docstring) already excludes
    bundle/package rows via their /bundle//sub/ href. Neither needs a
    client-side appdetails type-verification call the way
    storesearch's ambiguous "app" type (real game OR same-shaped DLC)
    did -- that whole verification pass, and the rate-limit pressure
    it put on broad queries, goes away with it.

    start/count are real Steam pagination on this endpoint -- unlike
    storesearch, /search/results/ is the endpoint Steam's own search
    results PAGE uses to page through results, so different start
    values genuinely return different games."""
    cache_key = ("term_search", term, start, count, cc)
    
    def _fetch():
        params = {
            "term": term,
            "start": start,
            "count": count,
            "category1": 998,
            "cc": cc,
            "l": "english",
        }
        try:
            return _scrape_search_results(params, cc)
        except (requests.exceptions.RequestException, ValueError):
            return None

    result = _execute_deduplicated(cache_key, 86400, _fetch, failure_ttl=60)
    return result if result is not None else []


def fetch_authoritative_price(app_id, cc="US"):
    """The /search/results/ listing (used by fetch_discover_games) caches
    its prices and can lag behind a game's real store-page price by hours
    or days after a change. This fetches the live price straight from
    appdetails — the same source /api/game/<app_id> already trusts —
    right before a card is shown, so discover results never show a stale
    number.

    Also retries under the US region if the caller's own region has no
    data for this app — the same region-unavailable fallback already
    used in services/hero/builder.py and routes/game.py. Without it, a
    game that isn't sold in the visitor's region silently kept its
    stale scraped price instead of getting corrected, and (see below)
    never got a chance at a real image either.

    While already talking to appdetails for the price, this also grabs
    header_image from the same response. It's a genuine Steam-confirmed
    URL, not a guessed CDN path — a real upgrade over
    steam_images.default_header_image()'s guess specifically for a
    title that needed the US retry to resolve at all: if it isn't
    actually sold in the caller's own region, its normal store CDN
    assets may not exist there either.

    Returns None (leaving the scraped price/image as-is) only if both
    the original region AND the US retry fail.

    NIMLYX TRADITION #003 — "We trusted Steam." Same endpoint, same App
    ID, different query parameters produced a different CDN cache and a
    stale price on the discover page even though the search page was
    correct. The fix was making this request IDENTICAL to the one
    already proven to return live prices (used by /api/find and
    /api/game) — not changing the algorithm. Two URLs can hit the same
    endpoint and still behave like completely different APIs.
    """
    if not app_id:
        return None

    # Discover's pagination calls this once per visible game, per
    # page. Without this cache, scrolling through results re-fetches
    # a price you already fetched moments ago for a game still on
    # screen or just off it. 5 minutes is short enough that a real
    # price change still shows up quickly, long enough to absorb
    # normal browsing/pagination within one visit.
    cache_key = ("authoritative_price", app_id, cc)

    def _fetch():
        def _try(region):
            try:
                url = f"https://store.steampowered.com/api/appdetails?appids={app_id}&l=english&cc={region}"
                response = _session.get(url, timeout=8)
                response.raise_for_status()
                data = response.json()
                entry = data.get(str(app_id))

                if not entry or not entry.get("success"):
                    return None

                game_data = entry.get("data")
                if not isinstance(game_data, dict):
                    return None

                price_overview = game_data.get("price_overview")
                if price_overview:
                    result = {
                        "final": price_overview.get("final", 0),
                        "discount_percent": price_overview.get("discount_percent", 0),
                    }
                else:
                    result = {"final": 0, "discount_percent": 0}

                result["header_image"] = game_data.get("header_image")
                return result

            except (requests.exceptions.RequestException, ValueError):
                return None

        result = _try(cc)
        if result is None:
            result = _try("US")
        return result

    return _execute_deduplicated(cache_key, 300, _fetch, failure_ttl=60)


# ==========================================================
# NEW RELEASES — verified against Steam's own release_date field.
#
# NIMLYX TRADITION #008 — "Today" wasn't today.
#
# The old homepage New Releases section took whatever order
# 'popularnew' happened to return (a blend of popularity and
# recency, not a real release-date sort) and slapped "Released
# Today" / "Yesterday" / "N Days Ago" on the first few rows based
# purely on their POSITION in that list. Counter-Strike 2, Palworld,
# and Warframe -- games that have been out for months or years --
# showed up labeled "Released Today" simply because they landed near
# the top of a popularity ranking.
#
# The fix: never derive a date from position. Pull a candidate pool
# ordered by Steam's own release-date sort, ask appdetails for each
# candidate's REAL release_date, parse only the concrete formats
# below, and drop anything that isn't cleanly parseable rather than
# guess at it. Games without a trustworthy date simply don't appear
# -- that's correct behavior for an analytics platform, not a bug.
#
# Lesson:
# A sorted list and a dated list are not the same thing.
#
# Battle Status:
# Victory.
# ==========================================================

# Steam's release_date.date is free text, not a machine-readable
# field, and its format varies ("21 Jun, 2023", "Jun 21, 2023") and
# sometimes isn't a date at all ("Coming soon", "Q4 2024", "TBD").
# Only these concrete formats are trusted; anything else returns
# None so the caller excludes the game instead of guessing at it.
_RELEASE_DATE_FORMATS = (
    "%d %b, %Y",   # 21 Jun, 2023 — Steam's most common English format
    "%b %d, %Y",   # Jun 21, 2023
    "%d %B, %Y",   # 21 June, 2023
    "%B %d, %Y",   # June 21, 2023
    "%d %b %Y",    # 21 Jun 2023 (no comma)
)


def parse_steam_release_date(raw_date_str):
    """Real appdetails release_date.date -> a real date() object, or
    None if it isn't one of the concrete formats above. Never
    guesses: "Q4 2024", "Coming soon", "", None all return None."""
    if not raw_date_str or not isinstance(raw_date_str, str):
        return None

    text = raw_date_str.strip()
    for fmt in _RELEASE_DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def release_recency_label(release_date_obj, today=None):
    """Relative label computed from a REAL parsed release date --
    never from list position, never invented. Returns None (caller
    must exclude the game) if the date is somehow in the future,
    which shouldn't happen once coming_soon titles are filtered out
    but is a real possibility around timezone edges."""
    if release_date_obj is None:
        return None

    today = today or datetime.utcnow().date()
    days_ago = (today - release_date_obj).days

    if days_ago < 0:
        return None
    if days_ago == 0:
        return "Released Today"
    if days_ago == 1:
        return "Yesterday"
    return f"{days_ago} Days Ago"


def fetch_new_release_candidates(count=40, cc="US"):
    cache_key = ("new_release_candidates", count, cc)
    def _fetch():
        url = (
            f"https://store.steampowered.com/search/results/"
            f"?query=&start=0&count={count}&sort_by=Released_DESC"
            f"&category1=998&cc={cc}&l=english"
        )
        try:
            response = _session.get(url, timeout=10)
            response.raise_for_status()
        except (requests.exceptions.RequestException, ValueError):
            return None

        soup = BeautifulSoup(response.text, "html.parser")
        games = soup.find_all("a", class_="search_result_row")
        cleaned = []
        for game in games:
            app_id = game.get("data-ds-appid")
            title = game.find("span", class_="title")
            name = title.text.strip() if title else "Unknown"
            if any(keyword in name.lower() for keyword in HARDWARE_KEYWORDS):
                continue
            img = game.find("img")
            image = img["src"] if img and img.get("src") else None
            if not _is_genuine_app_row(game, app_id) or not image:
                continue
            cleaned.append({
                "id": app_id,
                "name": name,
                "image": image
            })
        return cleaned

    result = _execute_deduplicated(cache_key, 1800, _fetch, failure_ttl=60)
    return result if result is not None else []


def fetch_verified_new_releases(limit=5, cc="US", candidate_pool=40):
    """The only source of truth for the homepage's New Releases
    section. Every field returned here is real, sourced from Steam's
    own appdetails response for that exact app id:

      - name / image fall back to the search-result scrape only if
        appdetails itself didn't return them (it always has name;
        image falls back to header_image).
      - release_date is parsed from appdetails' own release_date.date
        -- never guessed, never derived from list position.
      - recency_label is computed from that real date against today.
      - price comes straight from appdetails' price_overview; if
        Steam has no price data for this region, price is None
        rather than an invented "Free" or placeholder number.

    Games without a trustworthy release date -- unparseable,
    coming-soon, or a failed lookup -- are dropped entirely. Returning
    fewer real entries than `limit` is correct behavior, not a bug:
    callers must render however many this returns and never pad the
    list back up with anything fabricated.
    """
    candidates = fetch_new_release_candidates(count=candidate_pool, cc=cc)

    def enrich(candidate):
        try:
            raw = get_appdetails(candidate["id"], cc)
        except (requests.exceptions.RequestException, ValueError):
            # A single failed/malformed lookup shouldn't take down the
            # whole section -- treat it the same as "no trustworthy
            # data for this game" and exclude it.
            raw = None
        return candidate, raw

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(enrich, candidates))

    today = datetime.utcnow().date()
    verified = []

    for candidate, raw in results:
        if not raw:
            continue

        release_info = raw.get("release_date") or {}
        if release_info.get("coming_soon"):
            continue  # not released yet -- not a "new release" today

        release_date_obj = parse_steam_release_date(release_info.get("date"))
        if release_date_obj is None:
            continue  # unparseable -- exclude rather than guess

        recency_label = release_recency_label(release_date_obj, today=today)
        if recency_label is None:
            continue  # date parsed but landed in the future somehow

        price_overview = raw.get("price_overview") or {}
        if raw.get("is_free"):
            price = "Free"
        else:
            price = price_overview.get("final_formatted")  # None if unavailable -- never invented

        genres_data = raw.get("genres") or []
        genres = [g.get("description") for g in genres_data]

        # Same appdetails-adjacent enrichment as the hero builder --
        # this function already makes one live Steam call per
        # candidate (for the release date) inside a background
        # rebuild thread (see _rebuild_new_releases_cache in
        # routes/pages.py), so one more call here for review stats
        # costs nothing extra on the request path. See
        # services/hero/candidate.py for the matching hero/Picks path.
        review_summary = get_review_summary(candidate["id"], cc)
        nimlyx_score = None
        if review_summary:
            nimlyx_score = compute_nimlyx_score(
                total_positive=review_summary["total_positive"],
                total_reviews=review_summary["total_reviews"],
            )

        verified.append({
            "id": candidate["id"],
            "name": raw.get("name") or candidate["name"],
            "image": raw.get("header_image") or candidate["image"],
            "release_date": release_date_obj,
            "recency_label": recency_label,
            "price": price,
            "primary_genre": genres[0] if genres else None,
            "nimlyx_score": nimlyx_score,
        })

    verified.sort(key=lambda g: g["release_date"], reverse=True)
    return verified[:limit]


def get_review_summary(app_id, cc="US", day_range=None):
    """Fetches Steam's aggregate review stats for a game via the public
    appreviews endpoint (filter=summary by default — stats only, no
    review text, so no moderation surface). Used by Phase 2 Insight
    Providers that need review sentiment: Review Momentum, Critic/User
    Gap, Hidden Gem, Mixed/Contrarian, etc. — and now also by the
    Search page's real (Wilson-adjusted) Nimlyx Score, see
    services/analysis/wilson_score.py.

    day_range: when set, scopes the summary to only reviews posted in
    the last `day_range` days (used by
    services/analysis/reputation_trajectory.py to get a "recent"
    bucket to compare against the all-time one). Per Steam's own API
    constraint, day_range only takes effect when the query also uses
    filter=all — filter=summary on its own ignores it and silently
    returns the all-time summary instead, which would make a
    "recent" claim quietly wrong rather than absent. This function
    switches to filter=all automatically whenever day_range is set,
    specifically to avoid that silent failure mode.

    Returns None if the lookup fails or the game has no review data
    yet (e.g. brand-new release) — callers must treat None as "this
    provider has nothing to say," never fabricate a summary.
    """
    if not app_id:
        return None

    # Same caching convention as every other Steam-calling function in
    # this file — this became a hot path the moment Search started
    # calling it on every game lookup, not just the homepage hero
    # engine's bulk enrichment. 10 minutes matches get_appdetails'
    # TTL: review aggregates don't meaningfully shift minute to minute.
    # day_range is part of the cache key since it's a genuinely
    # different query, not just a different filter on the same data.
    cache_key = ("review_summary", app_id, cc, day_range)

    def _fetch():
        try:
            review_filter = "all" if day_range else "summary"
            url = (
                f"https://store.steampowered.com/appreviews/{app_id}"
                f"?json=1&filter={review_filter}&language=english&cc={cc}"
            )
            if day_range:
                url += f"&day_range={day_range}"

            response = _session.get(url, timeout=8)
            response.raise_for_status()
            data = response.json()

            if not data.get("success"):
                return None

            summary = data.get("query_summary")
            if not summary:
                return None

            total_reviews = summary.get("total_reviews", 0)
            if total_reviews == 0:
                return None

            result = {
                "review_score_desc": summary.get("review_score_desc"),
                "total_positive": summary.get("total_positive", 0),
                "total_negative": summary.get("total_negative", 0),
                "total_reviews": total_reviews,
            }
            return result

        except (requests.exceptions.RequestException, ValueError):
            return None

    return _execute_deduplicated(cache_key, 600, _fetch, failure_ttl=60)


def get_review_texts(app_id, cc="US", num_reviews=100):
    """Fetches actual review TEXT, not just stats. This is a different
    data surface than get_review_summary above, on purpose. That
    function was built to deliberately avoid review text (see its
    docstring: stats only, no moderation surface). This function
    exists because services/analysis/topic_engine.py (Community Pulse,
    Tag Honesty) needs to scan for what players are actually saying,
    which stats alone can't answer.

    Caps at num_reviews (default 100, Steam's own per-page maximum,
    so this is a single request, not a paginated crawl). This means
    every claim built on top of this function is a claim about a
    sample of the most relevant recent reviews, not the entire review
    corpus. Callers must say so explicitly in their output ("in the
    last 100 reviews", not just "in reviews") so nobody reads a
    sample-based count as a complete one.

    Returns a list of plain review text strings, or an empty list on
    any failure. No review author names, no profile data, no other
    metadata beyond the review body itself, since nothing downstream
    needs anything more than the text.
    """
    if not app_id:
        return []

    cache_key = ("review_texts", app_id, cc, num_reviews)
    cached = _cache_get(cache_key, ttl_seconds=600)
    if cached is not None:
        return cached

    try:
        url = (
            f"https://store.steampowered.com/appreviews/{app_id}"
            f"?json=1&filter=recent&language=english&cc={cc}"
            f"&num_per_page={min(num_reviews, 100)}&purchase_type=all"
        )
        response = _session.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()

        if not data.get("success"):
            return []

        reviews = data.get("reviews", [])
        texts = [r.get("review", "").strip() for r in reviews if r.get("review")]

        _cache_set(cache_key, texts)
        return texts

    except (requests.exceptions.RequestException, ValueError):
        return []


def get_top_helpful_review(app_id, cc="US", voted_up=True, num_reviews=20):
    """Fetches the single most-helpful review for a game in one
    direction (positive or negative) — the evidence behind Nimlyx
    Analysis's review spotlight (see
    services/analysis/spotlight_reviews.py).

    Uses filter=all, which is Steam's own HELPFULNESS-sorted review
    order (not chronological, not "recent") restricted to
    review_type=positive/negative. The first non-empty review in that
    response IS the most helpful one Steam has for this game in that
    direction — no client-side re-ranking, no guessing at what
    "helpful" means.

    Returns a dict with the raw review text, Steam's own helpful-vote
    count (votes_up), and the review's timestamp, or None if this
    game has no usable review in that direction (brand-new release,
    a direction with zero reviews, or the lookup failed). Callers
    must treat None as "nothing to show here" — never invent a quote
    or fall back to a different game's review.
    """
    if not app_id:
        return None

    review_type = "positive" if voted_up else "negative"

    # Same caching convention as the rest of this file. 10 minutes
    # matches get_review_summary/get_review_texts — the most-helpful
    # review for a game doesn't change minute to minute.
    cache_key = ("top_review", app_id, cc, review_type, num_reviews)
    cached = _cache_get(cache_key, ttl_seconds=600)
    if cached is not None:
        return cached

    try:
        url = (
            f"https://store.steampowered.com/appreviews/{app_id}"
            f"?json=1&filter=all&language=english&cc={cc}"
            f"&num_per_page={min(num_reviews, 100)}&purchase_type=all"
            f"&review_type={review_type}"
        )
        response = _session.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()

        if not data.get("success"):
            return None

        reviews = data.get("reviews", [])
        # reviews is already in Steam's own helpfulness order (see
        # docstring) — walk it only to skip the rare empty-body
        # review, never to re-sort it.
        for review in reviews:
            text = (review.get("review") or "").strip()
            if not text:
                continue

            result = {
                "text": text,
                "votes_up": review.get("votes_up", 0),
                "timestamp_created": review.get("timestamp_created"),
            }
            _cache_set(cache_key, result)
            return result

        return None

    except (requests.exceptions.RequestException, ValueError):
        return None


def get_helpful_reviews(app_id, cc="US", voted_up=True, limit=5, num_reviews=20):
    """Fetches up to `limit` of the most-helpful reviews for a game in
    one sentiment direction (positive or negative) -- the multi-review
    sibling of get_top_helpful_review() above, built for the game
    page's 10-review preview (see services/analysis/spotlight_reviews.
    compute_review_preview) rather than a single spotlight quote.

    Same request shape and same Steam helpfulness ordering as
    get_top_helpful_review() (filter=all, review_type=positive/
    negative -- Steam's own helpfulness sort, not chronological, no
    client-side re-ranking). The difference is purely how many
    non-empty reviews are collected out of that same response before
    returning, so this shares get_top_helpful_review()'s cache
    entries only when `limit`/`num_reviews` also match -- otherwise
    it's cached under its own key at the same 10-minute TTL (a
    game's most-helpful reviews don't meaningfully change minute to
    minute, same reasoning as the rest of this file).

    Returns a list (never None) of dicts, each with the raw review
    text, Steam's own helpful-vote count (votes_up), and the review's
    timestamp -- shortest possible list is [], meaning this game has
    no usable reviews in that direction. Callers must treat an empty
    list as "nothing to show here", never pad it with another game's
    review or a placeholder.
    """
    if not app_id:
        return []

    review_type = "positive" if voted_up else "negative"

    cache_key = ("helpful_reviews", app_id, cc, review_type, limit, num_reviews)
    cached = _cache_get(cache_key, ttl_seconds=600)
    if cached is not None:
        return cached

    try:
        url = (
            f"https://store.steampowered.com/appreviews/{app_id}"
            f"?json=1&filter=all&language=english&cc={cc}"
            f"&num_per_page={min(num_reviews, 100)}&purchase_type=all"
            f"&review_type={review_type}"
        )
        response = _session.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()

        if not data.get("success"):
            return []

        reviews = data.get("reviews", [])
        # Same helpfulness order as get_top_helpful_review() -- walk
        # it only to skip empty-body reviews and stop once we have
        # `limit` of them, never to re-sort it.
        results = []
        for review in reviews:
            text = (review.get("review") or "").strip()
            if not text:
                continue

            results.append({
                "text": text,
                "votes_up": review.get("votes_up", 0),
                "timestamp_created": review.get("timestamp_created"),
            })
            if len(results) >= limit:
                break

        _cache_set(cache_key, results)
        return results

    except (requests.exceptions.RequestException, ValueError):
        return []


def _fetch_packagedetails_payload(package_id, cc="US"):
    package_id = str(package_id)
    cache_key = ("packagedetails_payload", package_id, cc)
    
    def _fetch():
        try:
            url = f"https://store.steampowered.com/api/packagedetails?packageids={package_id}&l=english&cc={cc}"
            response = _session.get(url, timeout=10)
            response.raise_for_status()
            data = response.json()
        except (requests.exceptions.RequestException, ValueError):
            return None
        if not isinstance(data, dict):
            return None
        entry = data.get(package_id)
        if isinstance(entry, dict) and entry.get("success"):
            return entry.get("data")
        return None

    return _execute_deduplicated(cache_key, 3600, _fetch, failure_ttl=60)


def _format_price_cents(cents, currency="USD"):
    """Formats a raw integer cent amount into a display string.

    Needed specifically because Steam's packagedetails endpoint --
    unlike appdetails' price_overview -- does NOT return a pre-
    formatted string (no final_formatted/initial_formatted field,
    just raw cents). get_package_display_info used to read those
    field names anyway, which silently produced None for every
    package's price rather than erroring, since dict.get() on a
    missing key just returns nothing to blame. This is the fix: format
    the raw cents ourselves for the currencies we recognize, falling
    back to a plain "CODE 12.34" for anything else rather than
    inventing a symbol we're not sure of.
    """
    if cents is None:
        return None
    amount = f"{cents / 100:.2f}"
    symbol = _CURRENCY_SYMBOLS.get(currency)
    return f"{symbol}{amount}" if symbol else f"{currency} {amount}"


def get_package_display_info(package_id, cc="US"):
    """Builds display-facing info for one Steam package ("sub") id --
    name/price/discount/included-apps/steam_url. The shared building
    block behind the Purchase Options section (build_purchase_options,
    below), which fans this out concurrently across every package
    Steam lists for a game.

    Returns None when the package can't be honestly described (same
    failure modes as resolve_package_primary_app -- packagedetails
    request failed, or Steam reported no success for this id). Callers
    must skip this package rather than render invented data when this
    is None.
    """
    package_id = str(package_id)
    data = _fetch_packagedetails_payload(package_id, cc)
    if data is None:
        return None

    price_info = data.get("price", {}) or {}
    included_apps = data.get("apps", []) or []
    currency = price_info.get("currency", "USD")
    discount = price_info.get("discount_percent", 0) or 0
    final_cents = price_info.get("final")
    # packagedetails only gives the discounted "final" cents plus a
    # discount %, never the pre-discount amount directly (unlike
    # appdetails' price_overview, which has both final and initial).
    # Back it out from final + discount% instead of leaving it blank.
    initial_cents = (
        round(final_cents / (1 - discount / 100)) if discount and final_cents else None
    )

    return {
        "package_id": package_id,
        "name": data.get("name"),
        "price": _format_price_cents(final_cents, currency),
        "original_price": _format_price_cents(initial_cents, currency) if discount else None,
        "discount": discount,
        "steam_url": f"https://store.steampowered.com/sub/{package_id}/",
        "included_apps": [
            {"app_id": a.get("id"), "name": a.get("name")}
            for a in included_apps if a.get("id")
        ],
    }


def build_purchase_options(app_id, raw_appdetails, cc="US"):
    """Purchase Options: "which version should I buy?", answered from
    Steam's OWN purchase-options data instead of Nimlyx guessing at it.

    appdetails (already fetched for every game page, see
    routes/game.build_game_detail) includes a `package_groups` field --
    this is literally the same data Steam's own store page purchase box
    is built from: every package a visitor can buy this game through
    (the base game itself, Complete/Deluxe/GOTY editions, franchise
    bundles), in Steam's own display order, base game first.

    Each entry is filled in via get_package_display_info() -- the exact
    same per-package lookup the old standalone "Steam Package" card
    used, just fanned out across every package instead of one. Nothing
    about how a single package's info is fetched changes; this only
    changes how many are shown and where.

    Returns [] when this game has no package_groups (some titles,
    especially F2P ones, genuinely don't) -- the frontend must not
    render a Purchase Options section when this is empty. The first
    item is always the base game itself (`is_base_game: True`), exactly
    matching Steam's own ordering, so the frontend never has to guess
    which option that is either.
    """
    app_id = str(app_id)
    groups = raw_appdetails.get("package_groups") or []
    sub_ids = []
    for group in groups:
        for sub in group.get("subs", []) or []:
            package_id = sub.get("packageid")
            if package_id is not None and package_id not in sub_ids:
                sub_ids.append(package_id)  # de-dupe, preserve Steam's order
    if not sub_ids:
        return []

    cache_key = ("purchase_options", app_id, cc, tuple(sub_ids))
    cached = _cache_get(cache_key, ttl_seconds=1800)
    if cached is not None:
        return cached

    # Same reasoning as build_game_detail's developer/publisher lookup:
    # independent per-package calls, so run them concurrently rather
    # than one after another. Each individual call is itself cached for
    # an hour (_fetch_packagedetails_payload), so this fan-out is cheap
    # on anything but a fully cold cache.
    with ThreadPoolExecutor(max_workers=min(len(sub_ids), 6)) as executor:
        results = list(executor.map(lambda pid: get_package_display_info(pid, cc), sub_ids))

    options = []
    for index, info in enumerate(results):
        if info is None:
            continue  # honest omission, not a placeholder -- see get_package_display_info
        options.append({**info, "is_base_game": index == 0})

    _cache_set(cache_key, options)
    return options


def resolve_package_primary_app(package_id, cc="US"):
    """Resolves a Steam package ("sub") ID -- a Complete/GOTY/Deluxe
    Edition, or any other bundle -- to the app_id of the one base game
    it contains. Not specific to any title: works purely from Steam's
    own data, in two steps:

    1. packagedetails tells us which app_ids a package actually
       contains (Steam has no other public endpoint for this -- a sub
       id and an app id are different ID namespaces with no
       conversion formula between them, so this lookup is mandatory,
       not optional).
    2. Each included app's own appdetails `type` field ("game" vs
       "dlc"/"music"/"video"/etc) tells us which of those included
       apps is the actual playable base game, rather than a bonus
       soundtrack or an expansion also bundled in. This is the same
       get_appdetails() every other part of the app already calls, so
       it's cached the same way (10 min).

    If a package genuinely bundles more than one standalone game
    (uncommon, but franchise packs exist), the lowest app_id is
    chosen deterministically -- normally also the earliest-released /
    primary title -- rather than guessing from the name.

    Returns None when the package can't be honestly resolved (no
    included apps, or none of them are type="game"). Callers should
    drop the row in that case; there's no in-app destination to send
    someone to for a package Nimlyx can't identify a real game in.

    NOTE: I have not been able to verify Steam's packagedetails
    endpoint against live traffic from this environment (no network
    access to store.steampowered.com here) -- this is built from
    known Steam API conventions, not a confirmed live response. Watch
    the first few [package-resolve] log lines in production to
    confirm the shape actually matches before trusting this broadly.
    """
    package_id = str(package_id)
    cache_key = ("package_primary_app", package_id, cc)
    cached = _cache_get(cache_key, ttl_seconds=3600)
    if cached is not None:
        return cached if cached != "" else None  # "" is the cached-negative sentinel; see below

    resolved = None
    data = _fetch_packagedetails_payload(package_id, cc)
    if data is None:
        # _fetch_packagedetails_payload already logged the specific
        # failure reason (request failed vs. no success) -- nothing
        # further to add here, and its own cache_key already holds
        # the negative result, so this function's cache doesn't need
        # a duplicate negative entry.
        return None

    included_apps = data.get("apps", []) or []
    included_ids = [a.get("id") for a in included_apps if a.get("id")]

    if not included_ids:
        print(f"[package-resolve] sub {package_id} -> no included apps found")
        _cache_set(cache_key, "")
        return None

    game_apps = []
    for app_id in included_ids:
        details = get_appdetails(app_id, cc)
        if details and details.get("type") == "game":
            game_apps.append(app_id)

    if game_apps:
        resolved = min(game_apps)
        print(f"[package-resolve] sub {package_id} -> app {resolved} (game candidates: {game_apps}, all included: {included_ids})")
    else:
        print(f"[package-resolve] sub {package_id} -> included apps {included_ids}, none are type=game")

    _cache_set(cache_key, resolved if resolved is not None else "")
    return resolved


def get_appdetails(app_id, cc):
    """Fetches one game's appdetails. Returns None on ANY failure —
    network error, timeout, non-JSON body, or Steam returning a bare
    `null` (which it does when it's rate-limiting a client that's
    made too many rapid requests, rather than an HTTP error status).

    This matters beyond just this one call: builder.py's enrich_pool()
    runs this concurrently across the whole candidate pool via
    ThreadPoolExecutor.map(). Before this fix, an unhandled exception
    from ONE game's request (e.g. a single null response during a
    rate-limit window) propagated out of executor.map() and killed
    the entire hero build — every other successfully-fetched game's
    result was lost too, not just the one that failed. Returning None
    here lets _enrich_one() treat it as "no data for this game" (its
    existing, correct behavior) so one flaky response degrades to one
    missing candidate instead of an empty homepage.

    This is the single most-called Steam endpoint in the app — Home's
    hero pool enrichment, New Releases date verification, and Search
    all funnel through it, and the same popular games routinely show
    up in more than one of those at once (a hero candidate someone
    then searches for directly, or a game both trending AND freshly
    verified as a new release). 10 minutes is longer than the other
    caches here since a full appdetails payload (price aside, which
    fetch_authoritative_price already covers separately with its own
    shorter TTL) changes far less often than a listing or a price.

    Only a SUCCESSFUL response is cached — never None. Caching a
    failure would turn one transient rate-limit blip into a "missing"
    game for the entire TTL window instead of just this one request.
    """
    cache_key = ("appdetails", app_id, cc)

    def _fetch():
        url = f"https://store.steampowered.com/api/appdetails?appids={app_id}&l=english&cc={cc}"
        try:
            response = _session.get(url, timeout=10)
            response.raise_for_status()
            data = response.json()
        except (requests.exceptions.RequestException, ValueError):
            return None

        if not isinstance(data, dict):
            # Steam returned `null` or some other non-dict body — most
            # often a rate-limit signal, not a real "this app has no
            # data" response, but it's handled identically either way.
            return None

        entry = data.get(str(app_id))
        if isinstance(entry, dict) and entry.get("success"):
            return entry.get("data")
        return None

    return _execute_deduplicated(cache_key, 600, _fetch, failure_ttl=60)


def clean_search_term(name):
    # An apostrophe (straight ' or curly ') inside a word is a
    # contraction/possessive, not a word boundary -- plenty of real
    # Steam titles have one (Assassin's Creed, Tom Clancy's..., Marvel's
    # Spider-Man). Deleting it outright keeps the word glued together
    # ("Assassins Creed") so storesearch matches the intact word.
    #
    # This used to fall through to the generic punctuation-strip below,
    # which replaces punctuation with a SPACE -- turning "Assassin's"
    # into "Assassin" + a stray one-letter "s" token. That extra noise
    # token was diluting storesearch's own relevance ranking enough
    # that most mainline Assassin's Creed titles fell out of its
    # returned result set entirely (nothing downstream -- exact-match,
    # type filtering, etc -- can recover a title Steam's own search
    # never returned in the first place). Titles without an apostrophe
    # (Witcher, Cyberpunk, Fallout) were never affected by this, which
    # is why the bug looked Assassin's-Creed-specific even though the
    # underlying defect wasn't.
    cleaned = re.sub(r"[’']", "", name)
    # Remaining punctuation (colons, hyphens, etc.) still becomes a
    cleaned = re.sub(r"[^\w\s]", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def fetch_homepage_row(category_id, cc="US", seen_ids=None):
    """
    Phase 1 mapping for homepage rows.
    Uses serve-stale-while-revalidating cache logic and avoids N+1 appdetails hits.
    """
    if seen_ids is None:
        seen_ids = set()

    def _fetch():
        if category_id == "specials":
            # fetch_browse_category scrapes "specials", returning valid list of dicts
            from formatters import to_discover_card
            from steam_images import default_header_image, build_image_candidates
            
            # Fetch a much larger raw pool (60, not the function's
            # default of 25) specifically for this homepage row.
            # Steam's specials listing mixes in a lot of DLC/software
            # that category1=998 (below) then strips back out, so a
            # small raw sample was leaving too few base-game deals to
            # survive filtering -- this was the actual cause of the
            # row only showing ~3 cards, not any filter being too
            # strict. All filtering below is unchanged.
            raw = fetch_browse_category("specials", count=60, cc=cc)
            
            paid_specials = []
            for g in raw:
                app_id = str(g.get("id", ""))
                if not app_id or app_id in seen_ids:
                    continue
                    
                final_price = g.get("final_price")
                if final_price in (0, "0", None, ""):
                    continue
                    
                discount_raw = g.get("discount_percent") or ""
                discount_digits = "".join(filter(str.isdigit, str(discount_raw)))
                discount = int(discount_digits) if discount_digits else 0
                if discount == 0:
                    continue
                    
                g["_discount_num"] = discount
                paid_specials.append(g)
            
            # Prioritize higher discounts, preserving Steam's popularity order for ties
            paid_specials.sort(key=lambda g: g["_discount_num"], reverse=True)

            for g in paid_specials:
                app_id = g.get("id")
                g["final_price"] = g.get("final_price") or "0"
                # A real, Steam-scraped image (guaranteed to exist --
                g["header_default"] = default_header_image(app_id)
                g["image_candidates"] = build_image_candidates(app_id, fallback_image=g.get("image"))
            return [to_discover_card(g) for g in paid_specials]

        elif category_id == "action":
            # fetch_discover_games only scrapes, no N+1 price lookups
            # Fetch a larger buffer so we have enough games after filtering
            raw = fetch_discover_games(genre="action", count=30, cc=cc)
            from formatters import to_discover_card
            from steam_images import default_header_image, build_image_candidates
            
            # Prepare minimal card structure (same as discover.py but skipping live prices)
            filtered_action = []
            for g in raw:
                app_id = str(g.get("id", ""))
                if not app_id or app_id in seen_ids:
                    continue
                    
                # Fallback prices to scraped values
                g["final_price"] = g.get("final_price") or "0"
                g["discount_percent"] = g.get("discount_percent") or 0
                g["header_default"] = default_header_image(g.get("id"))
                g["image_candidates"] = build_image_candidates(g.get("id"), fallback_image=g.get("image"))
                filtered_action.append(g)
            return [to_discover_card(g) for g in filtered_action]
        else:
            return []
            
    cache_key = f"feed_row_{category_id}_{cc}"
    # specials can be cached for 15 mins, action for longer. Default 1800s (30m)
    all_games = serve_stale_or_rebuild(cache_key, _fetch)
    
    if not all_games:
        return all_games

    # Filter out seen_ids
    filtered_games = [g for g in all_games if str(g.get("app_id")) not in seen_ids]
    
    # Safety valve: if filtering removes too many games (less than 4), fall back to original
    if len(filtered_games) < 4:
        filtered_games = all_games
        
    return filtered_games[:14]  # Slice to top 14 for the row -- scrollable rows should carry more than 10