from bs4 import BeautifulSoup
import requests
from flask import jsonify

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