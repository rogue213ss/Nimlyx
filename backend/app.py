from flask import Flask, jsonify, render_template, request
from flask_cors import CORS
import re
import requests
from bs4 import BeautifulSoup

app = Flask(__name__)
CORS(app)


# ==========================================================
# SHARED SCRAPER — used by /api/browse, /api/verdicts, and home()
# ==========================================================

def fetch_browse_category(category, count=25):
    url = (
        f"https://store.steampowered.com/search/results/"
        f"?query=&start=0&count={count}&filter={category}&cc=US&l=english"
    )

    response = requests.get(url, timeout=10)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")
    games = soup.find_all("a", class_="search_result_row")

    hardware_keywords = ["steam deck", "steam controller", "steam machine", "steam link"]
    cleaned = []

    for game in games:
        app_id = game.get("data-ds-appid")

        title = game.find("span", class_="title")
        name = title.text.strip() if title else "Unknown"

        if any(keyword in name.lower() for keyword in hardware_keywords):
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


def to_game_dict(item, stat_fields=None):
    """Shapes a raw scraped game dict into what index.html expects."""
    base = {
        "id": item.get("id"),
        "name": item.get("name"),
        "header_image": item.get("image"),
        "analyze_url": f"/search?q={item.get('name', '')}",
    }
    if stat_fields:
        base.update(stat_fields)
    return base


# ==========================================================
# DISCOVER WIZARD — filter mappings + scraper
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

PLATFORM_OS_PARAM = {
    "windows": "win",
    "linux": "linux",
    "macos": "mac",
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
    "steam-deck": "win",
}


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


def fetch_discover_games(genre=None, play_with=None, budget=None, platform=None, count=30):
    """Scrapes Steam's search results using tag/price/os filters built
    from the discover wizard's answers. Review score isn't filterable
    server-side, so it's applied afterwards in the /api/discover route."""

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
        "cc": "US",
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

    hardware_keywords = ["steam deck", "steam controller", "steam machine", "steam link"]
    games = []

    for row in rows:
        app_id = row.get("data-ds-appid")

        title = row.find("span", class_="title")
        name = title.text.strip() if title else "Unknown"

        if any(keyword in name.lower() for keyword in hardware_keywords):
            continue

        img = row.find("img")
        image = img["src"] if img else None

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
            "image": image,
            "final_price": final_price,
            "original_price": original_price,
            "discount_percent": discount_percent,
            "review_percent": parse_review_percent(row),
        })

    return games


def fetch_authoritative_price(app_id):
    """The /search/results/ listing (used by fetch_discover_games) caches
    its prices and can lag behind a game's real store-page price by hours
    or days after a change. This fetches the live price straight from
    appdetails — the same source /api/game/<app_id> already trusts —
    right before a card is shown, so discover results never show a stale
    number. Returns None (leaving the scraped price as a fallback) if the
    live lookup fails for any reason."""
    if not app_id:
        return None

    try:
      # ==========================================================
# NIMLYX TRADITION #003
#
# "We trusted Steam."
#
# The same endpoint.
# The same App ID.
#
# Different query parameters.
#
# Different CDN cache.
#
# Search page:
#     Correct price ✅
#
# Discover page:
#     Stale price ❌
#
# Hours were spent debugging the pricing logic,
# only to discover the culprit wasn't the code—
# it was Steam serving different cached responses
# because of `filters` and `cc`.
#
# The fix wasn't changing the algorithm.
# It was making this request IDENTICAL to the one
# already proven to return live prices.
#
# Lesson:
# Two URLs can hit the same endpoint...
# and still behave like completely different APIs.
#
# Battle Status:
# Victory.
# ==========================================================

# Match the exact request used by /api/find and /api/game.
# Even small query parameter differences create a different
# Steam CDN cache key and may return stale pricing.
        url = f"https://store.steampowered.com/api/appdetails?appids={app_id}&l=english"
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
        if price_overview and "final" in price_overview:
            return price_overview["final"]

        # No price_overview at all means the game is free (or has no
        # listed price), matching how format_price() treats None/"0".
        return 0

    except (requests.exceptions.RequestException, ValueError):
        return None

def to_discover_card(game):
    """Shapes a scraped game into the {name, header_image, analyze_url,
    footer_left, footer_right} card fields discover.js renders."""

    def format_price(cents):
        if cents is None:
            return "Free"
        s = str(cents)
        if not s.isdigit():
            return "Free"
        n = int(s)
        return "Free" if n == 0 else f"${n / 100:.2f}"

    review_percent = game.get("review_percent")
    review_label = f"{review_percent}% Positive" if review_percent is not None else "No reviews yet"

    return {
        "id": game.get("id"),
        "name": game.get("name"),
        "header_image": game.get("image"),
        "analyze_url": f"/search?q={game.get('name', '')}",
        "footer_left": format_price(game.get("final_price")),
        "footer_right": review_label,
    }


# ==========================================================
# HOMEPAGE — server-side rendered
# ==========================================================

@app.route("/")
def home():
    def format_price(cents):
        if cents is None:
            return "Free"
        s = str(cents)
        if not s.isdigit():
            return "Free"
        n = int(s)
        return "Free" if n == 0 else f"${n / 100:.2f}"

    def platform_label(platforms):
        names = {"win": "Windows", "mac": "macOS", "linux": "Linux"}
        labels = [names[p] for p in platforms if p in names]
        return ", ".join(labels) if labels else "—"

    try:
        top_sellers_raw = fetch_browse_category("topsellers")
        specials_raw = fetch_browse_category("specials")
        new_releases_raw = fetch_browse_category("popularnew")

        def hero_image_url(appid, fallback):
          # ==========================================================
# NIMLYX TRADITION #004
#
# We almost accepted blurry.
#
# Steam's search only gives a tiny 231x87 capsule image.
# It looked fine in lists...
# until we stretched it across the homepage hero.
#
# Instead of settling, we dug deeper and discovered
# Steam's hidden `library_hero.jpg` asset (1920x622),
# built exactly for this purpose.
#
# Sometimes the right solution isn't improving
# what you have—
# it's discovering what already exists.
#
# Lesson:
# Explore the platform before working around it.
#
# Battle Status:
# Victory.
# ==========================================================

# Steam's high-resolution library hero banner (1920x622).
# Replaces the small 231x87 search capsule to keep the
# homepage hero crisp on large displays.
            if appid:
                return f"https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/{appid}/library_hero.jpg"
            return fallback

        featured_games = [
            {
                "id": g.get("id"),
                "name": g.get("name"),
                "header_image": hero_image_url(g.get("id"), g.get("image")),
                "analyze_url": f"/search?q={g.get('name', '')}",
                "short_description": "",
            }
            for g in top_sellers_raw[:5]
        ]

        # ---------------- TOP SELLERS ----------------
        # Left: real rank (#1, #2...) based on Steam's own ordering.
        # Right: real price.
        top_seller_games = [
            to_game_dict(g, {
                "footer_left": f"#{i + 1} Global",
                "footer_right": format_price(g.get("final_price")),
            })
            for i, g in enumerate(top_sellers_raw[:8])
        ]

        # ---------------- BIGGEST DEALS ----------------
        # Left: real discount percent. Right: was → now price.
        deal_games = []
        for g in specials_raw:
            discount = (g.get("discount_percent") or "").replace("%", "").replace("-", "")
            if not discount:
                continue
            was = g.get("original_price") or ""
            now = format_price(g.get("final_price"))
            deal_games.append(to_game_dict(g, {
                "footer_left": f"-{discount}%",
                "footer_right": f"{was} → {now}" if was else now,
            }))
        deal_games = deal_games[:8]

        # ---------------- FREE TO PLAY ----------------
        # Left: "Free". Right: real platform support (Windows/Mac/Linux),
        # since Steam's search results don't expose genre tags.
        free_games = []
        for g in top_sellers_raw + new_releases_raw:
            final_cents = g.get("final_price")
            if final_cents == "0" or final_cents == 0:
                free_games.append(to_game_dict(g, {
                    "footer_left": "Free",
                    "footer_right": platform_label(g.get("platforms", [])),
                }))
        seen_ids = set()
        deduped_free = []
        for g in free_games:
            if g["id"] not in seen_ids:
                seen_ids.add(g["id"])
                deduped_free.append(g)
        free_games = deduped_free[:8]

        # ---------------- NEW RELEASES ----------------
        # Replaces the old fake "Highest Rated" placeholder section.
        # Left: "New". Right: real price.
        new_release_games = [
            to_game_dict(g, {
                "footer_left": "New",
                "footer_right": format_price(g.get("final_price")),
            })
            for g in new_releases_raw[:8]
        ]

        return render_template(
            "index.html",
            featured_games=featured_games,
            top_seller_games=top_seller_games,
            deal_games=deal_games,
            free_games=free_games,
            new_release_games=new_release_games,
        )

    except requests.exceptions.RequestException:
        return render_template(
            "index.html",
            featured_games=[],
            top_seller_games=[],
            deal_games=[],
            free_games=[],
            new_release_games=[],
        )


@app.route("/api/hello")
def hello():
    return jsonify({"message": "Hello from Flask"})


@app.route("/api/game/<app_id>")
def get_game(app_id):
    try:
        url = f"https://store.steampowered.com/api/appdetails?appids={app_id}&l=english"
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()

        if data.get(app_id) and data[app_id]["success"]:
            return jsonify(data[app_id]["data"])

        return jsonify({"error": "Game not found"}), 404

    except requests.exceptions.RequestException as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/verdicts")
def verdicts():
    try:
        top_sellers = fetch_browse_category("topsellers")
        specials = fetch_browse_category("specials")
        new_releases = fetch_browse_category("popularnew")

        def discount_num(g):
            d = g.get("discount_percent")
            return int(d.replace("%", "").replace("-", "")) if d else 0

        def price_num(g):
            fp = g.get("final_price")
            return int(fp) if fp and str(fp).isdigit() else 0

        worth_buying = [g for g in specials if discount_num(g) >= 40][:8]
        skip_for_now = [g for g in top_sellers if discount_num(g) == 0 and price_num(g) >= 3000][:8]
        hidden_value = [g for g in new_releases if price_num(g) == 0 or price_num(g) < 1000][:8]

        return jsonify({
            "worth_buying": worth_buying,
            "skip_for_now": skip_for_now,
            "hidden_value": hidden_value
        })

    except requests.exceptions.RequestException as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/search/<game_name>")
def search_game(game_name):
    try:
        url = f"https://store.steampowered.com/api/storesearch/?term={game_name}&l=english&cc=US"
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        return jsonify(response.json())

    except requests.exceptions.RequestException as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/find/<game_name>")
def find_game(game_name):
    search_url = f"https://store.steampowered.com/api/storesearch/?term={game_name}&l=english&cc=US"
    search_response = requests.get(search_url)
    search_data = search_response.json()

    if not search_data["items"]:
        return jsonify({"error": "No game found"}), 404

    app_id = search_data["items"][0]["id"]

    details_url = f"https://store.steampowered.com/api/appdetails?appids={app_id}&l=english"
    details_response = requests.get(details_url)
    details_data = details_response.json()

    if not details_data[str(app_id)]["success"]:
        return jsonify({"error": "Details not found"}), 404

    raw = details_data[str(app_id)]["data"]

    clean_data = {
        "name": raw.get("name"),
        "header_image": raw.get("header_image"),
        "genres": [g["description"] for g in raw.get("genres", [])],
        "price": raw.get("price_overview", {}).get("final_formatted", "Free"),
        "is_free": raw.get("is_free"),
        "developers": raw.get("developers", []),
        "publishers": raw.get("publishers", []),
        "release_date": raw.get("release_date", {}).get("date"),
        "coming_soon": raw.get("release_date", {}).get("coming_soon", False),
        "total_reviews": raw.get("recommendations", {}).get("total", 0),
        "metacritic": raw.get("metacritic", {}).get("score"),
        "short_description": raw.get("short_description"),
        "platforms": raw.get("platforms", {}),
        "movies": [
            {
                "name": movie.get("name"),
                "thumbnail": movie.get("thumbnail"),
                "video_url": (
                    movie.get("mp4", {}).get("max")
                    or movie.get("mp4", {}).get("480")
                    or movie.get("webm", {}).get("max")
                    or movie.get("webm", {}).get("480")
                )
            }
            for movie in raw.get("movies", [])
        ],
        "screenshots": [
            shot.get("path_full")
            for shot in raw.get("screenshots", [])
        ]
    }

    return jsonify(clean_data)


@app.route("/api/featured")
def featured_games_api():
    url = "https://store.steampowered.com/api/featuredcategories?l=english&cc=US"
    response = requests.get(url)
    data = response.json()

    def clean_items(category):
        items = data.get(category, {}).get("items", [])
        cleaned = []
        hardware_keywords = ["steam deck", "steam controller", "steam machine", "steam link"]

        for item in items:
            name = item.get("name", "")
            if any(keyword in name.lower() for keyword in hardware_keywords):
                continue

            cleaned.append({
                "id": item.get("id"),
                "name": name,
                "image": item.get("header_image"),
                "final_price": item.get("final_price", 0),
                "original_price": item.get("original_price"),
                "discount_percent": item.get("discount_percent", 0)
            })
        return cleaned

    top_sellers = clean_items("top_sellers")

    hero = [
        {
            "appid": g["id"],
            "name": g["name"],
            "header_image": g["image"],
            "short_description": "",
            "price": g.get("final_price", 0)
        }
        for g in top_sellers[:5]
    ]

    return jsonify({
        "hero": hero,
        "top_sellers": top_sellers,
        "new_releases": clean_items("new_releases"),
        "specials": clean_items("specials")
    })

@app.route("/discover")
def discover():
    return render_template("discover.html")


from concurrent.futures import ThreadPoolExecutor

@app.route("/api/discover")
def discover_api():
    genre = request.args.get("genre")
    play_with = request.args.get("playWith")
    budget = request.args.get("budget")
    review_score = request.args.get("reviewScore", "any")
    platform = request.args.get("platform")

    try:
        games = fetch_discover_games(
            genre=genre,
            play_with=play_with,
            budget=budget,
            platform=platform,
        )

        min_percent = REVIEW_SCORE_MIN_PERCENT.get(review_score, 0)
        if min_percent > 0:
            games = [
                g for g in games
                if g.get("review_percent") is not None and g["review_percent"] >= min_percent
            ]

        # ==========================================================
# NIMLYX TRADITION #005
#
# "Free" wasn't free.
#
# Steam's own `maxprice=0` search filter somehow returned:
#
#     Free
#     Free
#     $59.99
#     $29.99
#     Free
#
# We questioned our code.
# We questioned our logic.
# We even questioned the definition of "free."
#
# Turns out...
# Steam's filter wasn't reliable enough.
#
# The solution wasn't to trust the API.
# It was to verify every result ourselves.
#
# Lesson:
# Never assume the platform validates its own data.
#
# Battle Status:
# Victory.
# ==========================================================

# Steam's `maxprice=0` filter is unreliable for isolating
# truly free games. Post-filter on the scraped price to
# guarantee only genuinely free titles are returned.
        if budget == "free":
            games = [g for g in games if g.get("final_price") in ("0", 0)]

        games = games[:12]

       # ==========================================================
# NIMLYX TRADITION #006
#
# The Discover page felt... slow.
#
# We blamed Flask.
# We blamed the internet.
# We even blamed Steam.
#
# Turns out...
#
# We were politely waiting for 12 HTTP requests
# to finish one after another.
#
# Request 1...
# "After you."
#
# Request 2...
# "No, after you."
#
# ...
#
# Request 12...
#
# Meanwhile, the user was wondering if Nimlyx had crashed.
#
# The solution:
# Stop waiting.
#
# Ask everyone at once.
#
# Lesson:
# Sequential code is simple.
# Concurrent code is fast.
#
# Battle Status:
# Victory.
# ==========================================================

# Fetch live prices concurrently instead of sequentially.
# This reduces the total wait time to roughly the duration
# of the slowest request instead of the sum of all requests.
        with ThreadPoolExecutor(max_workers=8) as executor:
            live_prices = list(executor.map(
                lambda g: fetch_authoritative_price(g.get("id")),
                games
            ))

        for g, live_price in zip(games, live_prices):
            if live_price is not None:
                g["final_price"] = live_price

        cards = [to_discover_card(g) for g in games]

        return jsonify({"games": cards})

    except requests.exceptions.RequestException as e:
        return jsonify({"error": str(e), "games": []}), 500
@app.route("/search")
def search_page():
    return render_template("search.html")


@app.route("/api/browse/<category>")
def browse_games(category):
    allowed = ["topsellers", "specials", "popularnew"]

    if category not in allowed:
        return jsonify({"error": "Invalid category"}), 400

    try:
        return jsonify(fetch_browse_category(category))
    except requests.exceptions.RequestException as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    app.run(debug=True)