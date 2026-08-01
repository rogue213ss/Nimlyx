import requests
from flask import Blueprint, jsonify

from region import get_region_code
from steam import get_appdetails, get_review_summary, clean_search_term
from formatters import format_price
from services.analysis.wilson_score import compute_nimlyx_score
from services.analysis.reputation_trajectory import compute_trajectory
from services.analysis.community_pulse import compute_pulse
from services.analysis.tag_honesty import compute_tag_honesty
from services.analysis.spotlight_reviews import compute_spotlight_reviews

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


@game_bp.route("/api/search-results/<query>")
def search_results(query):
    """Sprint 3 — powers the new GameGrid results experience (both
    Search and, later, Discover funnel into this card shape).

    Returns:
      { "exact_match_app_id": <id or None>, "results": [GameGrid cards] }

    exact_match_app_id is set only when a result's name matches the
    query case-insensitively (punctuation/whitespace-normalized on
    both sides) -- search.js uses this to skip the grid entirely and
    redirect straight to that game's page, same as Steam/Amazon/IMDb
    search do for an obvious single answer.
    """
    try:
        cc = get_region_code()
        term = clean_search_term(query)
        url = f"https://store.steampowered.com/api/storesearch/?term={term}&l=english&cc={cc}"
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        items = response.json().get("items", [])

        normalized_query = clean_search_term(query).lower()

        results = []
        exact_match_app_id = None
        for item in items:
            app_id = item.get("id")
            name = item.get("name", "")
            price_overview = item.get("price", {}) or {}

            card = {
                "app_id": app_id,
                "name": name,
                "header_image": item.get("tiny_image"),
                "price": (
                    "Free" if price_overview.get("final") == 0
                    else format_price(price_overview.get("final"))
                ),
                "discount": price_overview.get("discount_percent", 0),
                # storesearch doesn't return review data or genres --
                # left null/empty here rather than guessed; GameGrid
                # renders these fields only when present.
                "review_percentage": None,
                "review_count": None,
                "genres": [],
            }
            results.append(card)

            if exact_match_app_id is None and clean_search_term(name).lower() == normalized_query:
                exact_match_app_id = app_id

        return jsonify({
            "exact_match_app_id": exact_match_app_id,
            "results": results,
        })

    except requests.exceptions.RequestException as e:
        return jsonify({"error": str(e), "results": [], "exact_match_app_id": None}), 500


@game_bp.route("/api/game-detail/<app_id>")
def game_detail_by_id(app_id):
    """Canonical Sprint 3 detail endpoint -- loads a game straight off
    its Steam app_id, no name resolution involved. This is what
    search.js should call whenever it already knows the app_id
    (exact-match redirect, GameGrid card click, or a /search?app_id=
    URL loaded directly/refreshed/shared)."""
    cc = get_region_code()
    clean_data = build_game_detail(app_id, cc)
    if clean_data is None:
        return jsonify({"error": "Details not found"}), 404
    return jsonify(clean_data)


@game_bp.route("/api/find/<game_name>")
def find_game(game_name):
    """Legacy name-based resolution -- still used by /search?q=. Finds
    the best-matching app_id via storesearch, then delegates to the
    exact same build_game_detail() used by the app_id route, so both
    paths always return identical shapes."""
    cc = get_region_code()
    term = clean_search_term(game_name)

    search_url = f"https://store.steampowered.com/api/storesearch/?term={term}&l=english&cc={cc}"
    search_data = requests.get(search_url).json()

    if not search_data.get("items"):
        return jsonify({"error": "No game found"}), 404

    app_id = search_data["items"][0]["id"]

    clean_data = build_game_detail(app_id, cc)
    if clean_data is None:
        return jsonify({"error": "Details not found"}), 404
    return jsonify(clean_data)


def build_game_detail(app_id, cc):
    """Shared by /api/game-detail/<app_id> (canonical, Sprint 3) and
    /api/find/<game_name> (legacy name lookup) so both routes stay
    byte-for-byte identical in what they return. Returns None if the
    app_id doesn't resolve to real appdetails in either the visitor's
    region or the US fallback."""
    raw = get_appdetails(app_id, cc)
    if raw is None:
        raw = get_appdetails(app_id, "US")  # fallback for region-unavailable titles
    if raw is None:
        return None

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

    # Sections 5 & 6 of Nimlyx Analysis — one real, most-helpful
    # review per direction, straight from Steam. See
    # services/analysis/spotlight_reviews.py.
    spotlight_reviews = compute_spotlight_reviews(app_id, cc)

    clean_data = {
        "app_id": app_id,
        # Generic Steam reviews surface for this app — used by the
        # review spotlight's "Read on Steam →" links. Steam has no
        # public permalink format for a single review that doesn't
        # require the author's own steamid (which this app deliberately
        # never fetches, see steam.get_review_texts's docstring), so
        # this points at the app's own review list rather than a
        # specific (unreachable) review URL.
        "steam_reviews_url": f"https://steamcommunity.com/app/{app_id}/reviews/",
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
        "spotlight_reviews": spotlight_reviews,
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

    return clean_data