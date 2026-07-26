"""
All functions that talk to Steam directly: scraping search-result HTML
and calling Steam's public JSON endpoints (appdetails, storesearch).
Used by the /api/browse, /api/verdicts, /api/discover, /api/game,
/api/find, /api/search routes and the homepage.
"""
import re
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor

import requests
from bs4 import BeautifulSoup

HARDWARE_KEYWORDS = ["steam deck", "steam controller", "steam machine", "steam link"]


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


# ==========================================================
# SHARED SCRAPER — used by /api/browse, /api/verdicts, and home()
# ==========================================================

def fetch_browse_category(category, count=25, cc="US"):
    # category1=998 restricts results to base games only — excludes
    # DLC, soundtracks, and software. Without this, DLC entries (e.g.
    # remaster/"resync" bundles) slip into Trending, Top Sellers, and
    # the hero/Picks candidate pool. DLC also often lacks its own
    # library_hero.jpg asset, which is why one showed up with a
    # broken/missing image rather than just being a wrong result.
    # fetch_discover_games() already applies this same filter — this
    # brings fetch_browse_category in line with it. DLC will get its
    # own homepage section later; until then it shouldn't appear
    # anywhere general "games" data is shown.
    url = (
        f"https://store.steampowered.com/search/results/"
        f"?query=&start=0&count={count}&filter={category}&category1=998&cc={cc}&l=english"
    )

    response = requests.get(url, timeout=10)
    response.raise_for_status()

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
        image = img["src"] if img else None

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
            "platforms": platforms
        })

    return cleaned


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

    tag_ids = []
    if genre in GENRE_TAG_IDS:
        tag_ids.append(GENRE_TAG_IDS[genre])
    if play_with in PLAYWITH_TAG_IDS:
        tag_ids.append(PLAYWITH_TAG_IDS[play_with])

    params = {
        "query": "",
        "start": 0,
        "count": count,
        "category1": 998,  # Games only — excludes DLC, soundtracks, software
        "cc": cc,
        "l": "english",
    }
    if tag_ids:
        params["tags"] = ",".join(str(t) for t in tag_ids)
    if platform in PLATFORM_OS_PARAM:
        params["os"] = PLATFORM_OS_PARAM[platform]
    if budget in BUDGET_MAX_PRICE_CENTS and BUDGET_MAX_PRICE_CENTS[budget] is not None:
        params["maxprice"] = BUDGET_MAX_PRICE_CENTS[budget] / 100

    url = "https://store.steampowered.com/search/results/"

    response = requests.get(url, params=params, timeout=10)

    print("\n========== DISCOVER DEBUG ==========")
    print("Genre:", genre)
    print("Play With:", play_with)
    print("Budget:", budget)
    print("Platform:", platform)
    print("Steam URL:", response.url)

    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")

    rows = soup.find_all("a", class_="search_result_row")

    print("Rows Found:", len(rows))
    print("===================================\n")

    games = []

    for row in rows:
        app_id = row.get("data-ds-appid")

        title = row.find("span", class_="title")
        name = title.text.strip() if title else "Unknown"

        if any(keyword in name.lower() for keyword in HARDWARE_KEYWORDS):
            continue

        img = row.find("img")
        image = img["src"] if img else None
        small_image = image
        large_image = (
            image.replace("capsule_231x87", "capsule_616x353")
            if image else None
        )

        price_div = row.find("div", class_="search_price_discount_combined")
        final_price_el = row.find("div", class_="discount_final_price")
        is_free = final_price_el and "free" in final_price_el.get("class", [])
        final_price = "0" if is_free else (price_div.get("data-price-final") if price_div else None)

        original_price_span = row.find("div", class_="discount_original_price")
        original_price = original_price_span.text.strip() if original_price_span else None

        discount_span = row.find("div", class_="discount_pct")
        discount_percent = discount_span.text.strip() if discount_span else None
        games.append({
            "id": app_id,
            "name": name,
            "image": small_image,
            "large_image": large_image,
            "final_price": final_price,
            "original_price": original_price,
            "discount_percent": discount_percent,
            "review_percent": parse_review_percent(row),
        })

    return games


def fetch_authoritative_price(app_id, cc="US"):
    """The /search/results/ listing (used by fetch_discover_games) caches
    its prices and can lag behind a game's real store-page price by hours
    or days after a change. This fetches the live price straight from
    appdetails — the same source /api/game/<app_id> already trusts —
    right before a card is shown, so discover results never show a stale
    number. Returns None (leaving the scraped price as a fallback) if the
    live lookup fails for any reason.

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

    try:
        # Match the exact request used by /api/find and /api/game.
        # Even small query parameter differences create a different
        # Steam CDN cache key and may return stale pricing.
        url = f"https://store.steampowered.com/api/appdetails?appids={app_id}&l=english&cc={cc}"
        response = requests.get(url, timeout=8)
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
            return {
                "final": price_overview.get("final", 0),
                "discount_percent": price_overview.get("discount_percent", 0),
            }

        # No price_overview at all means the game is free (or has no
        # listed price) — no discount to speak of either.
        return {"final": 0, "discount_percent": 0}

    except (requests.exceptions.RequestException, ValueError):
        return None


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
    """Scrapes Steam's own search results sorted by real release date
    (sort_by=Released_DESC) -- the same ordering Steam's own New
    Releases page is built from -- restricted to base games
    (category1=998, matching fetch_browse_category's DLC exclusion).

    This is a CANDIDATE pool only. The scraped search HTML has no
    actual date field, just an ordering, so every candidate still
    needs a live appdetails call (see fetch_verified_new_releases)
    before its release date can be trusted or shown.
    """
    url = (
        f"https://store.steampowered.com/search/results/"
        f"?query=&start=0&count={count}&sort_by=Released_DESC"
        f"&category1=998&cc={cc}&l=english"
    )

    response = requests.get(url, timeout=10)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")
    rows = soup.find_all("a", class_="search_result_row")

    candidates = []
    for row in rows:
        app_id = row.get("data-ds-appid")
        if not app_id:
            continue

        title = row.find("span", class_="title")
        name = title.text.strip() if title else "Unknown"
        if any(keyword in name.lower() for keyword in HARDWARE_KEYWORDS):
            continue

        img = row.find("img")
        image = img["src"] if img else None

        candidates.append({"id": app_id, "name": name, "image": image})

    return candidates


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

        verified.append({
            "id": candidate["id"],
            "name": raw.get("name") or candidate["name"],
            "image": raw.get("header_image") or candidate["image"],
            "release_date": release_date_obj,
            "recency_label": recency_label,
            "price": price,
        })

    verified.sort(key=lambda g: g["release_date"], reverse=True)
    return verified[:limit]


def get_review_summary(app_id, cc="US"):
    """Fetches Steam's aggregate review stats for a game via the public
    appreviews endpoint (filter=summary — stats only, no review text,
    so no moderation surface). Used by Phase 2 Insight Providers that
    need review sentiment: Review Momentum, Critic/User Gap, Hidden
    Gem, Mixed/Contrarian, etc.

    Returns None if the lookup fails or the game has no review data
    yet (e.g. brand-new release) — callers must treat None as "this
    provider has nothing to say," never fabricate a summary.
    """
    if not app_id:
        return None

    try:
        url = (
            f"https://store.steampowered.com/appreviews/{app_id}"
            f"?json=1&filter=summary&language=english&cc={cc}"
        )
        response = requests.get(url, timeout=8)
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

        return {
            "review_score_desc": summary.get("review_score_desc"),
            "total_positive": summary.get("total_positive", 0),
            "total_negative": summary.get("total_negative", 0),
            "total_reviews": total_reviews,
        }

    except (requests.exceptions.RequestException, ValueError):
        return None


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
    """
    url = f"https://store.steampowered.com/api/appdetails?appids={app_id}&l=english&cc={cc}"
    try:
        response = requests.get(url, timeout=10)
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


def clean_search_term(name):
    # Strip punctuation that breaks Steam's storesearch matching,
    # collapse whitespace
    cleaned = re.sub(r"[^\w\s]", " ", name)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned