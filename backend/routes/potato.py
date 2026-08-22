"""
POTATO ECOSYSTEM — "view more" page (/potato) + its pagination API
(/api/potato/<tier>).

Sourced from the researched, verified database
(data/potato/verified_potato_games.json via
services/hardware/verified_potato_pool.py) -- NOT from Steam's
published requirements. See verified_potato_db.py's module docstring
for why: Steam's official minimum/recommended spec is a legal/
marketing floor, not a measurement of what a game's engine actually
does on real low-end hardware, and no amount of dynamic-classifier
threshold tuning can substitute for real-world tested evidence.

The dynamic candidate pools this route used to page through (hero
pool, budget-price potato pool, curated seed pool -- see
routes/pages.py and services/hero/potato_pool.py /
services/hero/potato_curated_seed.py) are UNCHANGED and still exist,
but are no longer consulted here; they're kept for research/future
candidate validation (see homepage_classifier.classify_potato_tier_all()'s
updated docstring).
"""
import logging

from flask import Blueprint, jsonify, render_template, request

from region import get_region_code
from services.hardware.homepage_classifier import to_homepage_card
from services.hardware.verified_potato_pool import TIERS as VALID_TIERS, get_verified_potato_tiers

potato_bp = Blueprint("potato", __name__)
logger = logging.getLogger(__name__)

PAGE_SIZE = 20

_TIER_BADGES = {
    "friendly": ("Meets Low-End Minimum", "portrait"),
    "tweaks": ("Playable With Tweaks", "landscape"),
    "extreme": ("Extreme Settings Only", "landscape"),
}


def _tier_cards(tier, cc):
    """Every verified candidate for `tier`, rendered to the same
    homepage card shape the index page uses (to_homepage_card()),
    for the FULL verified list -- no 14-card cap, since this is the
    dedicated "view more" page the cap exists to send people to."""
    verified_tiers = get_verified_potato_tiers(cc)
    badge, orientation = _TIER_BADGES[tier]

    cards = []
    for candidate in verified_tiers.get(tier, []):
        try:
            cards.append(to_homepage_card(candidate, badge, orientation=orientation))
        except Exception:
            logger.exception("Failed to build verified Potato card for /potato, app_id=%s", candidate.app_id)
    return cards


@potato_bp.route("/potato")
def potato_page():
    """Server-renders the first page of all three tiers so the page
    isn't blank before JS runs; potato.js takes over from there for
    "Load More" pagination via /api/potato/<tier>."""
    cc = get_region_code()

    initial = {}
    for tier in VALID_TIERS:
        try:
            matches = _tier_cards(tier, cc)
        except Exception:
            logger.exception("Potato tier rendering failed for %s, region %s", tier, cc)
            matches = []
        initial[tier] = {
            "games": matches[:PAGE_SIZE],
            "has_more": len(matches) > PAGE_SIZE,
            "total_matches": len(matches),
        }

    return render_template(
        "potato.html",
        page_size=PAGE_SIZE,
        friendly=initial["friendly"],
        tweaks=initial["tweaks"],
        extreme=initial["extreme"],
    )


@potato_bp.route("/api/potato/<tier>")
def potato_tier_api(tier):
    if tier not in VALID_TIERS:
        return jsonify({"error": f"Unknown tier: {tier}", "games": [], "has_more": False}), 400

    try:
        offset = int(request.args.get("offset", 0))
    except (TypeError, ValueError):
        offset = 0
    if offset < 0:
        offset = 0

    try:
        cc = get_region_code()
        matches = _tier_cards(tier, cc)

        page = matches[offset:offset + PAGE_SIZE]
        total_matches = len(matches)
        has_more = offset + PAGE_SIZE < total_matches

        return jsonify({
            "games": page,
            "has_more": has_more,
            "total_matches": total_matches,
            "next_offset": offset + PAGE_SIZE,
        })
    except Exception as e:
        logger.exception("Potato tier API failed for tier=%s", tier)
        return jsonify({"error": str(e), "games": [], "has_more": False}), 500
