import re
import requests
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from flask import Blueprint, jsonify, request

from region import get_region_code
from steam import get_appdetails, get_review_summary, clean_search_term, build_purchase_options, fetch_search_by_term
from formatters import format_price
from services.analysis.wilson_score import compute_nimlyx_score
from services.analysis.reputation_trajectory import compute_trajectory
from services.analysis.community_pulse import compute_pulse
from services.analysis.tag_honesty import compute_tag_honesty
from services.analysis.spotlight_reviews import compute_spotlight_reviews
from services.game.related_games import get_developer_games, get_publisher_games
from services.game.requirements import parse_requirements
from services.hardware.compatibility import evaluate_compatibility, HardwareProfile, serialize_compatibility_result
from services.hardware.rankings_loader import get_cpus_with_rankings, get_gpus_with_rankings

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
    """Sprint 3 (refined) -- powers the SearchList results experience.
    GameGrid stays reserved for Discover; query-based Search results
    use this row layout instead (thumbnail left, details right) with
    a client-side filter sidebar (free/price/genre/platform).

    ARCHITECTURE NOTE (search backend switch): this used to call
    Steam's storesearch JSON endpoint. That was replaced after
    debugging confirmed, empirically (repeated identical &start= probes
    against storesearch directly, at three different offsets, always
    coming back with the exact same 10 app_ids in the exact same
    order), that storesearch is a small, non-paginating autocomplete-
    style endpoint -- fine for a search-bar dropdown, unusable for
    "give me a whole franchise's real result set". This now uses
    fetch_search_by_term() in steam.py, the same /search/results/ HTML
    scrape fetch_discover_games() and fetch_games_by_credit() (Sprint 4
    Phase 3's developer/publisher lookups) already share -- the
    endpoint Steam's own search results PAGE itself pages through, so
    &start= there genuinely does page.

    A second, related simplification came for free with the switch:
    Steam's own category1=998 (Games) filter + _is_genuine_app_row's
    href check exclude DLC/software/soundtracks/bundles/packages at
    the SOURCE, server-side, on Steam's end -- there's no longer a
    client-side appdetails type-verification pass needed to catch a
    same-named DLC/edition the way storesearch's ambiguous "app" type
    required (that verification pass was also the origin of this
    endpoint's earlier rate-limit problems on broad queries; it's gone
    now, not just made more lenient).

    Returns:
      { "exact_match_app_id": <id or None>, "has_more": bool,
        "next_offset": <int or None>, "results": [SearchList rows] }

    exact_match_app_id is set only on the first page (offset==0) and
    only when a result's name matches the query case-insensitively
    (punctuation/whitespace-normalized on both sides) -- search.js
    uses this to skip the list entirely and redirect straight to that
    game's page, same as Steam/Amazon/IMDb search do for an obvious
    single answer. Gated to offset==0 so a later "Load more" batch
    matching by coincidence can't yank someone out of a list they're
    deliberately browsing.
    """
    try:
        cc = get_region_code()
        term = clean_search_term(query)

        # offset is real Steam &start= now (see fetch_search_by_term) --
        # the frontend's "Load more" control passes back whatever
        # next_offset this endpoint returned last time, so a request
        # continues exactly where the previous one left off.
        offset = request.args.get("offset", default=0, type=int)

        # One request pulls BATCH_SIZE candidates directly at the given
        # offset -- genuine pagination, not a fixed-page cap papering
        # over a non-paginating endpoint the way the old storesearch
        # loop had to. A short batch (fewer than BATCH_SIZE rows) is
        # Steam's own signal there's nothing further to fetch.
        BATCH_SIZE = 30
        games = fetch_search_by_term(term, start=offset, count=BATCH_SIZE, cc=cc)
        has_more = len(games) == BATCH_SIZE
        next_offset = offset + BATCH_SIZE if has_more else None

        # Genre data is now lazy-loaded via /api/search-genres to decouple
        # its high-latency (30 concurrent appdetails lookups on cold cache)
        # from the critical rendering path. The search rows render
        # immediately with genres=[], and search_list.js populates them
        # async.
        genres_by_id = {}

        normalized_query = clean_search_term(query).lower()
        results = []
        exact_match_app_id = None

        for g in games:
            app_id = g.get("id")
            name = g.get("name", "")

            # final_price is a cents string ("0" for free) straight off
            # the scrape -- see _scrape_search_results -- same unit
            # format_price() already expects everywhere else in this file.
            final_price = g.get("final_price")
            is_free = final_price == "0"
            price_cents = int(final_price) if final_price and final_price.isdigit() else 0

            discount_raw = g.get("discount_percent") or ""
            discount_digits = re.sub(r"[^\d]", "", discount_raw)
            discount = int(discount_digits) if discount_digits else 0

            row = {
                # steam_type/steam_id kept for shape-parity with the
                # SearchList row contract (and the package_id-aware
                # href branch in search_list.js) -- always "app" here
                # now, since packages/bundles never reach this point at
                # all (_is_genuine_app_row excludes them server-side-
                # adjacent, before this loop ever sees them).
                "app_id": app_id,
                "steam_type": "app",
                "steam_id": app_id,
                "name": name,
                "header_image": g.get("image"),
                "short_description": None,  # not in this scrape either -- detail page has the full one
                "is_free": is_free,
                "price": "Free" if is_free else format_price(price_cents),
                "price_cents": price_cents,
                "discount": discount,
                "genres": genres_by_id.get(app_id, []),
                "platforms": g.get("platforms") or {"windows": False, "mac": False, "linux": False},
                # This scrape only has an aggregate review percentage,
                # not a raw review count -- same limitation
                # to_discover_card() already documents for Discover.
                "review_percentage": g.get("review_percent"),
                "review_count": None,
            }
            results.append(row)

            if offset == 0 and exact_match_app_id is None and clean_search_term(name).lower() == normalized_query:
                exact_match_app_id = app_id

        return jsonify({
            "exact_match_app_id": exact_match_app_id,
            "has_more": has_more,
            "next_offset": next_offset,
            "results": results,
        })

    except requests.exceptions.RequestException as e:
        return jsonify({"error": str(e), "results": [], "exact_match_app_id": None, "has_more": False, "next_offset": None}), 500


@game_bp.route("/api/search-genres", methods=["POST"])
def search_genres_api():
    try:
        data = request.get_json() or {}
        app_ids = data.get("app_ids", [])
        
        if not app_ids or not isinstance(app_ids, list):
            return jsonify({}), 400

        # Safety cap to prevent abuse
        app_ids = app_ids[:50]
        
        cc = get_region_code()
        
        def fetch_genres(app_id):
            raw = get_appdetails(app_id, cc)
            return [g["description"] for g in (raw or {}).get("genres", [])]

        with ThreadPoolExecutor(max_workers=8) as executor:
            genres_by_id = dict(zip(app_ids, executor.map(fetch_genres, app_ids)))

        return jsonify(genres_by_id)
        
    except Exception as e:
        print(f"Error fetching search genres: {e}")
        return jsonify({}), 500


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


@game_bp.route("/api/game/<app_id>/compatibility", methods=["POST"])
def game_compatibility(app_id):
    """Compatibility-engine integration (read-only). Takes a user's
    selected hardware (by ranking-catalog external_id -- see
    services/hardware/rankings_loader.py) plus RAM in GB, and returns
    whether that hardware meets this game's minimum/recommended specs.

    Deliberately a SEPARATE endpoint from /api/game-detail/<app_id>,
    not a field added onto it: game-detail's response shape is a
    stable contract several existing frontend call sites already
    depend on (see build_game_detail's own docstring note that
    `requirements` is kept stable specifically as this future input),
    and a per-request hardware selection isn't part of "the game"
    the way requirements/reviews/media are -- it varies per visitor,
    per request, so it doesn't belong baked into the cacheable game
    payload. Splitting it out also means this endpoint can be
    called repeatedly (e.g. the user tries a few different GPUs) with
    no need to re-fetch or reprocess the rest of the game detail data
    each time.

    Body (all fields optional -- a missing selection is handled by
    evaluate_compatibility() as "insufficient data" for that
    component, never as a guessed pass/fail):
        {
          "cpu_external_id": "cpu-intel-i5-2500k",
          "gpu_external_id": "nvidia-geforce-rtx-4090",
          "ram_gb": 16
        }

    Only fetches raw appdetails + parses requirements -- it does NOT
    call build_game_detail() (which also runs the review-summary,
    reputation-trajectory, community-pulse, spotlight-review, and
    developer/publisher-games pipeline). Requirement text is the only
    piece of the game payload this endpoint actually needs, so this
    avoids re-doing everything else 1:1 game-detail-by-id already
    computed on the page load that got the user here.
    """
    try:
        cc = get_region_code()
        raw = get_appdetails(app_id, cc)
        if raw is None:
            raw = get_appdetails(app_id, "US")  # same region fallback as build_game_detail
        if raw is None:
            return jsonify({"error": "Game not found"}), 404

        requirements = parse_requirements(raw.get("pc_requirements"))

        data = request.get_json(silent=True) or {}
        profile = HardwareProfile(
            cpu_external_id=data.get("cpu_external_id"),
            gpu_external_id=data.get("gpu_external_id"),
            ram_gb=data.get("ram_gb"),
        )

        result = evaluate_compatibility(requirements, profile)
        return jsonify(serialize_compatibility_result(result))

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@lru_cache(maxsize=1)
def _hardware_catalog_payload():
    """Builds the read-only {cpus: [...], gpus: [...]} catalog payload
    once and caches it in-memory for the life of the process -- the
    same 418+2,627 records the compatibility engine itself already
    reads via rankings_loader.py, just trimmed down to what a
    selection dropdown actually needs (external_id + a display name +
    manufacturer/vendor), not the full ranking/spec record. No score
    fields are exposed here; this endpoint is for populating a picker,
    not for surfacing ranking internals to the client.

    lru_cache is safe here because rankings_loader's own underlying
    data doesn't change at runtime (it's read from the generated
    ranking JSON files once per process); this just avoids rebuilding
    the same ~3,000-item list on every request.
    """
    cpus = [
        {
            "external_id": c["external_id"],
            "name": c["model_name"],
            "manufacturer": c["manufacturer"],
        }
        for c in get_cpus_with_rankings()
    ]
    gpus = [
        {
            "external_id": g["external_id"],
            "name": g["name"],
            "vendor": g["vendor"],
            # VRAM is display-only context for the selector (helping
            # disambiguate e.g. "GTX 1060 3GB" vs "GTX 1060 6GB" in the
            # dropdown) -- not used by the resolver/comparison engine,
            # which already handles VRAM-variant resolution itself.
            # Some normalized records legitimately have no VRAM value;
            # this stays None rather than fabricating one, and the
            # frontend simply omits the tag when absent ("where
            # possible").
            "vram_gb": g.get("vram_gb"),
        }
        for g in get_gpus_with_rankings()
    ]
    cpus.sort(key=lambda r: (r["manufacturer"], r["name"]))
    gpus.sort(key=lambda r: (r["vendor"], r["name"]))
    return {"cpus": cpus, "gpus": gpus}


@game_bp.route("/api/hardware/catalog")
def hardware_catalog():
    """Read-only hardware catalog for populating the Compatibility
    UI's CPU/GPU selectors (see compatibility endpoint above). Source
    of truth is the same validated ranking catalog
    (services.hardware.rankings_loader) the compatibility engine
    itself uses -- NOT the dormant SQL HardwareDevice table, which
    remains untouched and unused throughout this feature. No database
    involved; this reads the already-generated ranking JSON files,
    same as every other consumer of rankings_loader.
    """
    try:
        return jsonify(_hardware_catalog_payload())
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@game_bp.route("/api/find/<game_name>")
def find_game(game_name):
    """Legacy name-based resolution. Not currently called by any
    frontend JS (search.js uses /api/search-results -> app_id-based
    /search?app_id= instead) but still routed, so it stays aligned
    with search_results()'s current rule: subs (packages) are never
    a search/find target -- see the triage comment in search_results()
    -- and a failed appdetails verification is an unknown state, kept
    rather than treated as disqualifying, so a single Steam rate-limit
    blip can't make an otherwise-real game unfindable here either."""
    cc = get_region_code()
    term = clean_search_term(game_name)

    search_url = f"https://store.steampowered.com/api/storesearch/?term={term}&l=english&cc={cc}"
    search_data = requests.get(search_url).json()

    for item in search_data.get("items", []):
        if item.get("type") != "app":
            continue  # subs (packages) excluded -- see search_results()
        candidate_id = item.get("id")

        raw = get_appdetails(candidate_id, cc)
        # Fail open: raw is None means "couldn't verify", not
        # "confirmed not a game" -- same reasoning as search_results().
        if raw is None or raw.get("type") == "game":
            app_id = candidate_id
            break
    else:
        return jsonify({"error": "No game found"}), 404

    clean_data = build_game_detail(app_id, cc)
    if clean_data is None:
        return jsonify({"error": "Details not found"}), 404
    return jsonify(clean_data)


def _build_movie_entry(movie):
    """Sprint 4 Media Enhancement Pass. Shapes one of Steam appdetails'
    raw `movies[]` entries into Nimlyx's contract:

        { name, thumbnail, highlight, hls_url }

    - `highlight`: Steam's own signal for which trailer it considers
      primary (e.g. the launch trailer over an older teaser). Passed
      through as-is; the frontend picks the featured trailer from
      this, falling back to movies[0] when no movie is highlighted
      -- never assumed true when the field is simply absent.
    - `hls_url`: Nimlyx Tradition -- as of this Sprint, Steam's
      `movies[]` entries no longer carry flat/progressive mp4 or webm
      file URLs (confirmed via a live diagnostic against The Witcher 3,
      app_id 292030: the real keys are `dash_av1`, `dash_h264`,
      `hls_h264`, nothing else playable). Only `hls_h264` is used --
      `dash_av1`/`dash_h264` are ignored on purpose, since hls.js on
      the frontend covers every modern browser via HLS alone, and
      carrying DASH too would just be two ways to do the same job.
      This key can be None for a movie with no `hls_h264` at all; the
      frontend filters those out (same "don't render what can't play"
      rule this section has always followed)."""
    return {
        "name": movie.get("name"),
        "thumbnail": movie.get("thumbnail"),
        "highlight": bool(movie.get("highlight")),
        "hls_url": movie.get("hls_h264"),
    }


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

    # ---- Performance: everything below this point used to run
    # sequentially on the main thread -- review_summary, trajectory,
    # community pulse, tag honesty, spotlight reviews (itself 2 more
    # sequential calls) -- SIX-plus chained Steam round-trips stacked
    # up before the one already-parallel dev/pub step even started.
    # None of these actually depend on each other except within the
    # two pairs noted below, so they're grouped into independent
    # units and run concurrently instead. This is a pure wall-clock
    # win -- same calls, same data, same caching, just not queued one
    # behind another.
    #
    # Steam's "categories" field (Multiplayer, Online Co-op, MMO, etc.)
    # is what a store page's tag claims actually look like, not
    # "genres" (Action, RPG). Tag Honesty checks against these -- pure
    # in-memory work on `raw` already fetched, no Steam call of its own.
    game_categories = [c.get("description") for c in raw.get("categories", []) if c.get("description")]

    developers = raw.get("developers", [])
    publishers = raw.get("publishers", [])
    # Self-published titles credit the same name as both developer and
    # publisher -- showing the identical carousel twice under two
    # headings would be exactly the "random boxes" clutter Sprint 4
    # is trying to avoid, so publisher is skipped whenever it matches
    # developer.
    same_credit = bool(developers) and bool(publishers) and developers[0].strip().lower() == publishers[0].strip().lower()

    genres_list = [g["description"] for g in raw.get("genres", []) if g.get("description")]

    def _fetch_review_summary_and_trajectory():
        # Kept together, sequential: compute_trajectory needs
        # review_summary's result as its all-time comparison side
        # (reusing it, not re-fetching), so this pair has a real
        # dependency the other groups below don't.
        summary = get_review_summary(app_id, cc)
        trajectory = compute_trajectory(app_id, cc, overall_summary=summary)
        return summary, trajectory

    def _fetch_pulse_and_honesty():
        # Kept together, sequential ON PURPOSE (not just left alone):
        # both call get_review_texts(app_id, cc) with identical
        # params, which land on the SAME 600s cache entry (see
        # steam.get_review_texts). Sequential here means the second
        # call is a guaranteed cache hit -- one real network call
        # instead of two. Running these two against EACH OTHER
        # concurrently would race both onto a cold cache and could
        # cause the exact duplicate live call this grouping avoids;
        # they only run concurrently relative to the OTHER groups
        # below, which don't share any cache key with these.
        pulse = compute_pulse(app_id, cc)
        honesty = compute_tag_honesty(app_id, game_categories, cc)
        return pulse, honesty

    with ThreadPoolExecutor(max_workers=5) as executor:
        summary_trajectory_future = executor.submit(_fetch_review_summary_and_trajectory)
        pulse_honesty_future = executor.submit(_fetch_pulse_and_honesty)
        # Spotlight's own 2 calls (positive/negative helpful review)
        # are genuinely independent of each other too -- see
        # spotlight_reviews.py's own internal parallelization below.
        spotlight_future = executor.submit(compute_spotlight_reviews, app_id, cc)
        dev_future = executor.submit(get_developer_games, developers, app_id, cc)
        pub_future = (
            executor.submit(get_publisher_games, publishers, app_id, cc)
            if not same_credit else None
        )

        review_summary, reputation_trajectory = summary_trajectory_future.result()
        community_pulse, tag_honesty = pulse_honesty_future.result()
        spotlight_reviews = spotlight_future.result()
        developer_games = dev_future.result()
        publisher_games = pub_future.result() if pub_future else []

    nimlyx_score = None
    if review_summary:
        nimlyx_score = compute_nimlyx_score(
            total_positive=review_summary["total_positive"],
            total_reviews=review_summary["total_reviews"],
        )

    # Purchase Options -- "which version should I buy?" -- built
    # straight from this same appdetails response's package_groups
    # field (Steam's own purchase-options data), not a second lookup.
    # Empty list when Steam has nothing to offer beyond the base game
    # itself (e.g. many F2P titles); frontend must not render the
    # section in that case.
    purchase_options = build_purchase_options(app_id, raw, cc)

    # System Requirements -- Sprint 5. Parsed from THIS SAME appdetails
    # response's pc_requirements field, already sitting in `raw` -- no
    # extra Steam call. Pure in-memory string parsing (no I/O), so this
    # runs inline rather than through the ThreadPoolExecutor above; it
    # costs microseconds, not a round-trip, and never blocks anything
    # else in build_game_detail(). parse_requirements() never raises --
    # see its own docstring -- so this can't be the reason a game page
    # fails to load.
    requirements = parse_requirements(raw.get("pc_requirements"))

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
        "genres": genres_list,
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
        "movies": [_build_movie_entry(movie) for movie in raw.get("movies", [])],
        "screenshots": [
            shot.get("path_full")
            for shot in raw.get("screenshots", [])
        ],
        "developer_games": developer_games,
        "publisher_games": publisher_games,
        "purchase_options": purchase_options,
        # Normalized {minimum: {...}, recommended: {...}} -- see
        # services/game/requirements.py. This is the ONLY requirements
        # data sent to the frontend; Steam's raw HTML never leaves the
        # backend, and parsing never happens client-side (per Sprint 5
        # spec). This is also the future input source for Phase 2's
        # compatibility engine -- keep this shape stable.
        "requirements": requirements,
    }

    return clean_data