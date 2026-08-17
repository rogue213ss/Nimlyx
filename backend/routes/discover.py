from concurrent.futures import ThreadPoolExecutor

import requests
from flask import Blueprint, jsonify, request

from region import get_region_code
from steam import (
    REVIEW_SCORE_MIN_PERCENT,
    fetch_discover_games,
    fetch_authoritative_price,
)
from formatters import to_discover_card, sort_discover_games
from steam_images import default_header_image, build_image_candidates

discover_bp = Blueprint("discover_api", __name__)


@discover_bp.route("/api/discover")
def discover_api():
    genre = request.args.get("genre")
    play_with = request.args.get("playWith")
    budget = request.args.get("budget")
    review_score = request.args.get("reviewScore", "any")
    platform = request.args.get("platform")
    sort_mode = request.args.get("sort", "recommended")

    try:
        offset = int(request.args.get("offset", 0))
    except (TypeError, ValueError):
        offset = 0
    if offset < 0:
        offset = 0

    PAGE_SIZE = 12

    try:
        cc = get_region_code()
        games = fetch_discover_games(
            genre=genre,
            play_with=play_with,
            budget=budget,
            platform=platform,
            cc=cc,
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

        # Sort By -- applied to the full filtered candidate buffer,
        # BEFORE the offset slice below, so it's consistent across
        # "load more" pages too, not just whatever 12 are on the
        # current page. See formatters.sort_discover_games's own
        # docstring for the missing-data/stable-sort rules.
        games = sort_discover_games(games, sort_mode)

        # ==========================================================
        # NIMLYX TRADITION #007
        #
        # "Load more" needed more than a frontend trick.
        #
        # The button used to just render games[:12] — always the
        # same 12, no matter how many times you clicked it.
        #
        # Turning that into real infinite scroll meant the backend
        # had to know WHERE the user already was (offset), not just
        # WHAT they asked for (genre/budget/etc). And since 100 raw
        # candidates now come back per search instead of 30, doing
        # a live price + artwork lookup on all of them up front
        # would have undone the concurrency fix from Tradition #006.
        #
        # The fix: keep the full filtered list in memory, slice out
        # only the 12 being shown *this request*, and only pay for
        # live enrichment on that slice — not the other 88 games
        # sitting in the buffer for later pages.
        #
        # Lesson:
        # Pagination isn't "fetch less" — it's "fetch the same,
        # but only enrich what's on screen."
        #
        # Battle Status:
        # Victory.
        # ==========================================================

        total_matches = len(games)
        page_games = games[offset:offset + PAGE_SIZE]
        has_more = offset + PAGE_SIZE < total_matches

        # Enrichment used to also fire a live Steam appdetails call per
        # card here (get_cached_artwork) just to *guess* which fancier
        # asset might exist -- doubling the request count for every
        # page of results and still serving unverified URLs straight
        # to the <img> tag. Artwork upgrading now happens client-side
        # (see image-upgrade.js), so the only live call left per card
        # is the one that actually needs to be live: price.
        def enrich(g):
            return fetch_authoritative_price(g.get("id"), cc=cc)

        with ThreadPoolExecutor(max_workers=8) as executor:
            live_prices = list(executor.map(enrich, page_games))

        for g, live_price in zip(page_games, live_prices):
            if live_price is not None:
                g["final_price"] = live_price["final"]
                g["discount_percent"] = live_price["discount_percent"]
                # A real, Steam-confirmed image beats a guessed CDN
                # path outright -- particularly for a title that only
                # resolved via fetch_authoritative_price's US-region
                # retry, whose normal store assets may not exist under
                # the visitor's own region at all.
                if live_price.get("header_image"):
                    g["image"] = live_price["header_image"]
            app_id = g.get("id")
            # Guaranteed, zero-API-call base image every card can
            # render immediately. Higher-res candidates are cheap
            # unverified CDN-convention URLs -- the frontend probes
            # them and only swaps one in on a real, successful load.
            g["header_default"] = g.get("image") or default_header_image(app_id)
            g["image_candidates"] = build_image_candidates(app_id)

        cards = [to_discover_card(g) for g in page_games]

        return jsonify({
            "games": cards,
            "has_more": has_more,
            "next_offset": offset + len(page_games),
            "total_matches": total_matches,
        })

    except requests.exceptions.RequestException as e:
        return jsonify({"error": str(e), "games": [], "has_more": False}), 500