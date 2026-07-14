from flask import Flask, jsonify, render_template
from flask_cors import CORS
import requests

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

    # Clean data using pandas-friendly extraction
    clean_data = {
        "name": raw.get("name"),
        "header_image": raw.get("header_image"),
        "genres": [g["description"] for g in raw.get("genres", [])],
        "price": raw.get("price_overview", {}).get("final_formatted", "Free"),
        "is_free": raw.get("is_free"),
        "developers": raw.get("developers", []),
        "publishers": raw.get("publishers", []),
        "release_date": raw.get("release_date", {}).get("date"),
        "total_reviews": raw.get("recommendations", {}).get("total", 0),
        "metacritic": raw.get("metacritic", {}).get("score", None),
        "short_description": raw.get("short_description"),
        "platforms": raw.get("platforms", {})  
    }

    return jsonify(clean_data)


if __name__ == "__main__":
    app.run(debug=True)