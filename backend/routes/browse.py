import requests
from flask import Blueprint, jsonify

from region import get_region_code
from steam import fetch_browse_category

browse_bp = Blueprint("browse", __name__)


@browse_bp.route("/api/browse/<category>")
def browse_games(category):
    allowed = ["topsellers", "specials", "popularnew"]

    if category not in allowed:
        return jsonify({"error": "Invalid category"}), 400

    try:
        return jsonify(fetch_browse_category(category))
    except requests.exceptions.RequestException as e:
        return jsonify({"error": str(e)}), 500


@browse_bp.route("/api/verdicts")
def verdicts():
    try:
        cc = get_region_code()
        top_sellers = fetch_browse_category("topsellers", cc=cc)
        specials = fetch_browse_category("specials", cc=cc)
        new_releases = fetch_browse_category("popularnew", cc=cc)

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


@browse_bp.route("/api/featured")
def featured_games_api():
    cc = get_region_code()
    url = f"https://store.steampowered.com/api/featuredcategories?l=english&cc={cc}"
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
