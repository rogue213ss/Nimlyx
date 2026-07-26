"""
DISCOUNT — Insight Provider.

Flags games with a meaningful active discount. This is the most
common signal in the pool (sales are frequent), which is exactly why
its confidence must be calibrated conservatively — see
docs/homepage-engine.md's warning that a structurally "easy to be
confident about" provider can silently dominate the hero rotation if
its confidence isn't kept in check relative to rarer, harder-earned
signals like Critic Gap. This provider deliberately caps out lower
than critic_gap's ceiling for an equivalent-rarity event.

Per docs/homepage-engine.md: every provider returns a dict with
{insight, why_it_matters, confidence, category} or None if it has
nothing honest to say.
"""

CATEGORY = "discount"

# Below this, a discount isn't a story — it's just Tuesday on Steam.
MIN_DISCOUNT_PERCENT = 25

# Reviews below this make "worth it at this price" a harder claim to
# stand behind — doesn't block the insight, just caps confidence.
LOW_REVIEW_VOLUME_THRESHOLD = 200


def generate(game_raw):
    """game_raw is the raw `data` dict from appdetails, with an added
    `review_summary` key from get_review_summary() (may be None).

    Returns None if there's no active discount, or the discount is
    below MIN_DISCOUNT_PERCENT.
    """
    price_overview = game_raw.get("price_overview")
    if not price_overview:
        return None

    discount_percent = price_overview.get("discount_percent", 0)
    if discount_percent < MIN_DISCOUNT_PERCENT:
        return None

    name = game_raw.get("name", "This game")
    final_formatted = price_overview.get("final_formatted", "")
    review_summary = game_raw.get("review_summary")

    confidence = _confidence_from_discount(discount_percent, review_summary)

    has_volume = review_summary and review_summary.get("total_reviews", 0) >= LOW_REVIEW_VOLUME_THRESHOLD
    desc = review_summary.get("review_score_desc", "") if review_summary else ""
    positive_descs = ("Overwhelmingly Positive", "Very Positive", "Positive")

    if has_volume and desc in positive_descs:
        insight = f"{name} is {discount_percent}% off, now {final_formatted} — and it's {desc}."
        why_it_matters = (
            f"A steep cut on a game with a proven track record ({desc.lower()} reviews) "
            f"is a stronger case than a discount alone."
        )
    elif has_volume:
        # Volume exists but sentiment isn't positive — state the
        # discount plainly and let the reader draw their own
        # conclusion. Never frame mixed/negative reviews as a selling
        # point just because there's a big discount attached.
        insight = f"{name} just dropped {discount_percent}% — down to {final_formatted}."
        why_it_matters = (
            f"One of the steeper discounts among today's candidates, though reviews are {desc.lower()} — worth a closer look."
        )
    else:
        insight = f"{name} just dropped {discount_percent}% — down to {final_formatted}."
        why_it_matters = "One of the steeper discounts among today's candidates."

    return {
        "insight": insight,
        "why_it_matters": why_it_matters,
        "confidence": confidence,
        "category": CATEGORY,
    }


def _confidence_from_discount(discount_percent, review_summary):
    """Scales with discount depth, with a bonus for a backing review
    consensus and a penalty for thin/no review data. Deliberately
    capped below critic_gap's ceiling (see module docstring) — a
    discount alone, however steep, shouldn't be able to out-rank a
    genuine critic/player disagreement just by being a bigger number.
    """
    depth_component = min(discount_percent, 90) / 90  # caps out at 90% off

    if review_summary and review_summary.get("total_reviews", 0) >= LOW_REVIEW_VOLUME_THRESHOLD:
        desc = review_summary.get("review_score_desc", "")
        positive_descs = ("Overwhelmingly Positive", "Very Positive", "Positive")
        consensus_bonus = 0.15 if desc in positive_descs else 0.0
    else:
        consensus_bonus = -0.15  # thin/no review data — hold back confidence

    score = (depth_component * 0.8) + consensus_bonus
    score = max(0.0, min(score, 0.85))  # hard cap below critic_gap's max
    return round(score * 100)
