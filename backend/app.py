from flask import Flask, jsonify, render_template
from flask_cors import CORS
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
            # Steam's high-res library hero banner (1920x622) — much
            # sharper than the small search-result capsule thumbnail
            # (231x87) that fetch_browse_category() returns, which
            # blurs badly when stretched across the full hero width.
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