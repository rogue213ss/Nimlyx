import requests
from flask import Blueprint, jsonify

from region import get_region_code
from steam import get_appdetails, get_review_summary, clean_search_term
from services.analysis.wilson_score import compute_nimlyx_score
from services.analysis.reputation_trajectory import compute_trajectory
from services.analysis.community_pulse import compute_pulse
from services.analysis.tag_honesty import compute_tag_honesty

game_bp = Blueprint("game", __name__)


@game_bp.route("/api/hello")
def hello():
    return jsonify({"message": "Hello from Flask"})


@game_bp.route("/api/game/<app_id>")
def get_game(app_id):
    try:
        cc = get_region_code()
        raw = get_appdetails(app_id, cc)

        if raw is None:
            return jsonify({"error": "Game not found"}), 404

        return jsonify(raw)

    except requests.exceptions.RequestException as e:
        return jsonify({"error": str(e)}), 500


@game_bp.route("/api/search/<game_name>")
def search_game(game_name):
    try:
        cc = get_region_code()
        term = clean_search_term(game_name)
        url = f"https://store.steampowered.com/api/storesearch/?term={term}&l=english&cc={cc}"
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        return jsonify(response.json())

    except requests.exceptions.RequestException as e:
        return jsonify({"error": str(e)}), 500


@game_bp.route("/api/find/<game_name>")
def find_game(game_name):
    cc = get_region_code()
    term = clean_search_term(game_name)

    search_url = f"https://store.steampowered.com/api/storesearch/?term={term}&l=english&cc={cc}"
    search_data = requests.get(search_url).json()

    if not search_data.get("items"):
        return jsonify({"error": "No game found"}), 404

    app_id = search_data["items"][0]["id"]

    raw = get_appdetails(app_id, cc)
    if raw is None:
        raw = get_appdetails(app_id, "US")  # fallback for region-unavailable titles
    if raw is None:
        return jsonify({"error": "Details not found"}), 404

    # Real review counts (positive/negative split) for the Wilson
    # score — a different, more precise source than appdetails' own
    # `recommendations.total`, which is just a single aggregate number
    # with no positive/negative breakdown. filter=summary only (no
    # review text), same restraint as everywhere else this project
    # touches review data.
    review_summary = get_review_summary(app_id, cc)
    nimlyx_score = None
    if review_summary:
        nimlyx_score = compute_nimlyx_score(
            total_positive=review_summary["total_positive"],
            total_reviews=review_summary["total_reviews"],
        )

    # Reuses `review_summary` (already fetched above) as the all-time
    # side of the comparison — only the "recent" bucket needs a
    # second live call. Returns None whenever there isn't enough
    # evidence for an honest trend claim; the frontend must not
    # render a Reputation Trajectory section when this is None.
    reputation_trajectory = compute_trajectory(app_id, cc, overall_summary=review_summary)

    # Steam's "categories" field (Multiplayer, Online Co-op, MMO, etc.)
    # is what a store page's tag claims actually look like, not
    # "genres" (Action, RPG). Tag Honesty checks against these.
    game_categories = [c.get("description") for c in raw.get("categories", []) if c.get("description")]

    community_pulse = compute_pulse(app_id, cc)
    tag_honesty = compute_tag_honesty(app_id, game_categories, cc)

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
        # review_summary's total_reviews is the more precise source
        # (it's specifically what it's for); only fall back to
        # appdetails' cruder aggregate if the review lookup itself
        # failed, so this field is never just silently empty.
        "total_reviews": (
            review_summary["total_reviews"] if review_summary
            else raw.get("recommendations", {}).get("total", 0)
        ),
        # The REAL Nimlyx Score — Wilson-adjusted, built from actual
        # positive/negative counts, not a relabeled Metacritic number
        # or a review-volume-only guess (see wilson_score.py's
        # docstring for what this replaces and why). None when there's
        # no review data to compute one from — the frontend must not
        # invent a placeholder when this is None.
        "nimlyx_score": nimlyx_score,
        "reputation_trajectory": reputation_trajectory,
        "community_pulse": community_pulse,
        "tag_honesty": tag_honesty,
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