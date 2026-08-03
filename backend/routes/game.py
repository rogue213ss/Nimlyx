import requests
from concurrent.futures import ThreadPoolExecutor
from flask import Blueprint, jsonify, request

from region import get_region_code
from steam import get_appdetails, get_review_summary, clean_search_term, resolve_package_primary_app, build_purchase_options
from formatters import format_price
from services.analysis.wilson_score import compute_nimlyx_score
from services.analysis.reputation_trajectory import compute_trajectory
from services.analysis.community_pulse import compute_pulse
from services.analysis.tag_honesty import compute_tag_honesty
from services.analysis.spotlight_reviews import compute_spotlight_reviews
from services.game.related_games import get_developer_games, get_publisher_games

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
    """Sprint 3 (refined) — powers the SearchList results experience.
    GameGrid stays reserved for Discover; query-based Search results
    use this row layout instead (thumbnail left, details right) with
    a client-side filter sidebar (free/price/genre/platform).

    Returns:
      { "exact_match_app_id": <id or None>, "results": [SearchList rows] }

    exact_match_app_id is set only when a result's name matches the
    query case-insensitively (punctuation/whitespace-normalized on
    both sides) -- search.js uses this to skip the list entirely and
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

        # Confirmed root cause of the app_id=124923 bug: storesearch
        # returns a mix of item types -- "app" for a real single game,
        # "sub" for a Steam package (Complete/GOTY/Deluxe Edition,
        # bundle, etc), and possibly others. A sub id lives in a
        # completely different Steam ID namespace than an app id, so
        # /api/appdetails (which only understands app ids) 404s on it.
        #
        # Rather than dropping every sub result, each one is resolved
        # to the app_id of the actual game it contains -- see
        # resolve_package_primary_app() in steam.py. Not hardcoded to
        # any title: it asks Steam's own packagedetails endpoint what
        # a package contains, then asks each included app's own
        # appdetails what *type* it is to find the real game among
        # any bundled DLC/soundtracks/etc.
        def resolve_item(item):
            steam_id = item.get("id")
            steam_type = item.get("type")
            if steam_type == "app":
                return item, steam_id, steam_type, steam_id
            if steam_type == "sub":
                return item, resolve_package_primary_app(steam_id, cc), steam_type, steam_id
            # Unknown/unhandled type (Steam does return a few other
            # values in practice) -- nothing safe to link to.
            return item, None, steam_type, steam_id

        with ThreadPoolExecutor(max_workers=8) as executor:
            resolved_items = list(executor.map(resolve_item, items))

        # Rows whose app_id couldn't be resolved (unresolvable
        # package, or a type this app doesn't understand) have no
        # honest destination inside Nimlyx and are dropped here,
        # rather than passed through to fail on click.
        resolved_items = [r for r in resolved_items if r[1] is not None]

        normalized_query = clean_search_term(query).lower()

        # Genres aren't in storesearch's payload at all -- only
        # appdetails has them. Platforms ARE in storesearch already
        # (item["platforms"]), so no live call needed for those.
        # get_appdetails() is cached 10 min, so a repeat search for
        # the same term/region costs nothing extra here. Keyed by the
        # RESOLVED app_id now, not the raw storesearch id -- a sub's
        # own id was never a valid appdetails lookup to begin with.
        def fetch_genres(app_id):
            raw = get_appdetails(app_id, cc)
            if raw is None:
                return []
            return [g["description"] for g in raw.get("genres", [])]

        resolved_app_ids = [r[1] for r in resolved_items]
        with ThreadPoolExecutor(max_workers=8) as executor:
            genres_by_id = dict(zip(resolved_app_ids, executor.map(fetch_genres, resolved_app_ids)))

        results = []
        exact_match_app_id = None
        for item, app_id, steam_type, steam_id in resolved_items:
            name = item.get("name", "")
            price_overview = item.get("price", {}) or {}
            platforms = item.get("platforms", {}) or {}
            final_price_cents = price_overview.get("final")

            # storesearch omits the "price" object ENTIRELY for free
            # games -- it's not present with a final of 0, it's just
            # absent. So final_price_cents is None here for a free
            # game, not 0, and "final_price_cents == 0" never matched
            # them: the Free filter silently excluded every genuinely
            # free result. A missing price object is exactly what
            # "free" looks like from this endpoint, so treat it the
            # same as an explicit 0.
            is_free = (not price_overview) or final_price_cents == 0
            price_cents = 0 if is_free else final_price_cents

            row = {
                # app_id is always a real, navigable app id -- either
                # storesearch's own "app"-type id, or a sub resolved
                # to its primary game above. steam_type/steam_id
                # preserve what Steam actually returned, for
                # provenance/debugging -- a "sub" row's displayed
                # name/price/image below are still the PACKAGE's own
                # (that's genuinely what was searched for), only the
                # navigation target is the resolved base game.
                "app_id": app_id,
                "steam_type": steam_type,
                "steam_id": steam_id,
                "name": name,
                "header_image": item.get("tiny_image"),
                "short_description": None,  # not in storesearch; detail page has the full one
                "is_free": is_free,
                "price": (
                    "Free" if is_free
                    else format_price(final_price_cents)
                ),
                "price_cents": price_cents,
                "discount": price_overview.get("discount_percent", 0),
                "genres": genres_by_id.get(app_id, []),
                "platforms": {
                    "windows": bool(platforms.get("windows")),
                    "mac": bool(platforms.get("mac")),
                    "linux": bool(platforms.get("linux")),
                },
                # storesearch has no review data -- left null rather
                # than guessed; SearchList renders this row only when
                # present.
                "review_percentage": None,
                "review_count": None,
            }
            results.append(row)

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
    URL loaded directly/refreshed/shared).

    Optional ?package_id=<sub_id> is passed through as
    highlighted_package_id (Steam `sub` support): when the visitor
    originally clicked a package (Complete/GOTY/Deluxe Edition, etc)
    that got resolved to this app_id, this tells the frontend which
    card in the Purchase Options section (built from Steam's own
    package_groups -- see build_game_detail) to highlight as "what you
    clicked", without a second fetch: that package is already one of
    the options build_game_detail returned.
    """
    cc = get_region_code()
    clean_data = build_game_detail(app_id, cc)
    if clean_data is None:
        return jsonify({"error": "Details not found"}), 404

    clean_data["highlighted_package_id"] = request.args.get("package_id")

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

    # Sprint 4 Phase 3 -- "More From Developer" / "More From Publisher".
    # Two independent Steam search-scrape calls, so they run in
    # parallel rather than one after the other -- same reasoning as
    # every other concurrent lookup in this codebase (Discover's
    # per-card price enrichment, etc). Both are skipped entirely (no
    # Steam call at all) when this game has no developer/publisher
    # credit to search by.
    developers = raw.get("developers", [])
    publishers = raw.get("publishers", [])
    # Self-published titles credit the same name as both developer and
    # publisher -- showing the identical carousel twice under two
    # headings would be exactly the "random boxes" clutter Sprint 4
    # is trying to avoid, so publisher is skipped whenever it matches
    # developer.
    same_credit = bool(developers) and bool(publishers) and developers[0].strip().lower() == publishers[0].strip().lower()

    with ThreadPoolExecutor(max_workers=2) as credit_executor:
        dev_future = credit_executor.submit(get_developer_games, developers, app_id, cc)
        pub_future = (
            credit_executor.submit(get_publisher_games, publishers, app_id, cc)
            if not same_credit else None
        )
        developer_games = dev_future.result()
        publisher_games = pub_future.result() if pub_future else []

    # Purchase Options -- "which version should I buy?" -- built
    # straight from this same appdetails response's package_groups
    # field (Steam's own purchase-options data), not a second lookup.
    # Empty list when Steam has nothing to offer beyond the base game
    # itself (e.g. many F2P titles); frontend must not render the
    # section in that case.
    purchase_options = build_purchase_options(app_id, raw, cc)

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
        # Original (pre-discount) price, only meaningful alongside
        # `discount` below -- frontend only renders it when discount > 0.
        "original_price": raw.get("price_overview", {}).get("initial_formatted"),
        "discount": raw.get("price_overview", {}).get("discount_percent", 0),
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
        # Steam's own review label ("Very Positive", "Mostly Positive",
        # etc) -- deliberately kept separate from nimlyx_score above.
        # nimlyx_score is Nimlyx's Wilson-adjusted number; this is
        # Steam's raw aggregate descriptor. Quick Facts shows both so
        # neither is misrepresented as the other.
        "review_score_desc": review_summary["review_score_desc"] if review_summary else None,
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
        ],
        "developer_games": developer_games,
        "publisher_games": publisher_games,
        "purchase_options": purchase_options,
    }

    return clean_data