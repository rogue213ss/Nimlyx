"""
HIDDEN GEM — Insight Provider.

Flags games that are cheap AND well-reviewed AND still overlooked —
the "why has nobody heard of this" signal. Deliberately distinct from
discount.py: a hidden gem isn't about a price CUT, it's about being
quietly good at a low price point regardless of whether anything's on
sale. A $4.99 game that's always been $4.99 can still be a hidden
gem; a $60 game at 90% off cannot, no matter how steep the discount.

The "overlooked" part matters as much as the "good" part — a cheap,
well-reviewed game with 500,000 reviews isn't hidden, it's just
popular and affordable. This provider specifically wants a review
volume SWEET SPOT: enough reviews to trust the sentiment, not so many
that "hidden" stops being true.

Per docs/homepage-engine.md: every provider returns a dict with
{insight, why_it_matters, confidence, category} or None if it has
nothing honest to say.
"""

CATEGORY = "hidden_gem"

# Price ceiling, in cents, for "cheap" (price_overview.final) or the
# game must be free (is_free True / no price_overview at all).
MAX_PRICE_CENTS = 1500  # $15.00

# Review sentiment floor — must be genuinely well-liked, not just
# "not bad."
QUALIFYING_DESCS = ("Overwhelmingly Positive", "Very Positive")

# Volume sweet spot: enough to trust the signal, not so much that the
# game is clearly already well-known. Games below the floor are noise
# (Fresh Release's job, not this provider's); games above the ceiling
# aren't "hidden" by any reasonable definition.
MIN_REVIEWS = 150
MAX_REVIEWS_FOR_HIDDEN = 5000


def generate(game_raw):
    """game_raw is the raw `data` dict from appdetails, with an added
    `review_summary` key from get_review_summary() (may be None).

    Returns None if the game isn't cheap, isn't well-reviewed, or its
    review volume falls outside the "hidden" sweet spot.
    """
    review_summary = game_raw.get("review_summary")
    if not review_summary:
        return None

    total_reviews = review_summary.get("total_reviews", 0)
    if total_reviews < MIN_REVIEWS or total_reviews > MAX_REVIEWS_FOR_HIDDEN:
        return None

    desc = review_summary.get("review_score_desc", "")
    if desc not in QUALIFYING_DESCS:
        return None

    is_free = game_raw.get("is_free", False)
    price_overview = game_raw.get("price_overview")

    if is_free:
        price_label = "free"
        price_cents = 0
    elif price_overview:
        price_cents = price_overview.get("final", None)
        if price_cents is None or price_cents > MAX_PRICE_CENTS:
            return None
        price_label = price_overview.get("final_formatted", "")
    else:
        # No price data and not marked free — can't make a cheap
        # claim we can't back up.
        return None

    name = game_raw.get("name", "This game")
    total_positive = review_summary.get("total_positive", 0)
    confidence = _confidence_from_signals(total_reviews, total_positive, price_cents)

    price_phrase = "free" if is_free else f"just {price_label}"

    return {
        "insight": f"{name} is {price_phrase} and sitting at {desc} barely anyone's talking about it.",
        "why_it_matters": (
            f"Just {total_reviews:,} reviews, but {desc.lower()}. This isn't unproven it's undiscovered."
        ),
        "confidence": confidence,
        "category": CATEGORY,
    }


def _confidence_from_signals(total_reviews, total_positive, price_cents):
    """Confidence favors: strong positive ratio, a review count nearer
    the middle of the sweet-spot band (not right at either edge, where
    the "hidden" or "trustworthy" claim gets shakiest), and a lower
    price. None of these dominate the score on their own."""
    positive_ratio = (total_positive / total_reviews) if total_reviews else 0
    ratio_component = max(0.0, (positive_ratio - 0.85) / 0.15)  # 85%+ starts scoring, 100% maxes it
    ratio_component = min(ratio_component, 1.0)

    # Distance from the sweet-spot midpoint, normalized — closer to
    # the middle of MIN_REVIEWS..MAX_REVIEWS_FOR_HIDDEN scores higher
    # than hugging either edge.
    midpoint = (MIN_REVIEWS + MAX_REVIEWS_FOR_HIDDEN) / 2
    half_range = (MAX_REVIEWS_FOR_HIDDEN - MIN_REVIEWS) / 2
    distance_from_mid = abs(total_reviews - midpoint) / half_range
    volume_component = 1 - min(distance_from_mid, 1.0)

    price_component = 1 - (price_cents / MAX_PRICE_CENTS) if MAX_PRICE_CENTS else 0
    price_component = max(0.0, min(price_component, 1.0))

    score = (ratio_component * 0.5) + (volume_component * 0.3) + (price_component * 0.2)
    return round(score * 100)