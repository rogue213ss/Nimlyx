

from flask import Flask, jsonify, render_template
from flask_cors import CORS
import requests
from bs4 import BeautifulSoup


app = Flask(__name__)
CORS(app)



@app.route("/")
def home():
    return render_template("index.html")

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


@app.route("/api/search/<game_name>")
def search_game(game_name):
    try:
        url = f"https://store.steampowered.com/api/storesearch/?term={game_name}&l=english&cc=US"
        response = requests.get(url, timeout=10)
        response.raise_for_status()

        return jsonify(response.json())

    except requests.exceptions.RequestException as e:
        return jsonify({"error": str(e)}), 500


import pandas as pd

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
def featured_games():
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

    return jsonify({
        "top_sellers": clean_items("top_sellers"),
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

    url = (
        f"https://store.steampowered.com/search/results/"
        f"?query=&start=0&count=25&filter={category}&cc=US&l=english"
    )

    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")
        games = soup.find_all("a", class_="search_result_row")

        hardware_keywords = [
            "steam deck",
            "steam controller",
            "steam machine",
            "steam link"
        ]

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

            if is_free:
                final_price = "0"
            else:
                final_price = price_div.get("data-price-final") if price_div else None

            original_price_span = game.find("div", class_="discount_original_price")
            original_price = original_price_span.text.strip() if original_price_span else None

            discount_span = game.find("div", class_="discount_pct")
            discount_percent = discount_span.text.strip() if discount_span else None

            cleaned.append({
                "id": app_id,
                "name": name,
                "image": image,
                "final_price": final_price,
                "original_price": original_price,
                "discount_percent": discount_percent
            })

        return jsonify(cleaned)

    except requests.exceptions.RequestException as e:
        return jsonify({"error": str(e)}), 500
if __name__ == "__main__":
    app.run(debug=True)

