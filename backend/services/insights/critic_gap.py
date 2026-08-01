"""
CRITIC / USER GAP — Insight Provider.

Flags games where Metacritic's critic score and Steam's own user
review consensus meaningfully disagree. This is the highest-value
insight type Nimlyx can produce: it's editorial content Steam's own
storefront never surfaces, since Steam doesn't juxtapose Metacritic
against its own review score anywhere in its UI.

Per docs/homepage-engine.md: every provider returns a dict with
{insight, why_it_matters, confidence, category} or None if it has
nothing honest to say. Confidence is NOT comparable across providers
(see selector.py) — it only ranks candidates within this category.
"""

CATEGORY = "critic_gap"

# A gap below this many points isn't interesting enough to be a
# "gap" — normal critic/user variance, not a story.
MIN_GAP = 20

# Reviews below this count make the Steam side of the gap too noisy
# to trust (a handful of early reviews can swing wildly).
MIN_TOTAL_REVIEWS = 100


def generate(game_raw):
    """game_raw is the raw `data` dict from appdetails, with an added
    `review_summary` key from get_review_summary() (may be None).

    Returns None if metacritic score, review summary, or a meaningful
    gap don't exist — never fabricates a gap from partial data.
    """
    metacritic = (game_raw.get("metacritic") or {}).get("score")
    review_summary = game_raw.get("review_summary")

    if metacritic is None or not review_summary:
        return None

    total_reviews = review_summary.get("total_reviews", 0)
    if total_reviews < MIN_TOTAL_REVIEWS:
        return None

    desc = review_summary.get("review_score_desc", "")
    total_positive = review_summary.get("total_positive", 0)

    # Steam doesn't give us a 0-100 user score directly, only a
    # positive/total ratio — use that as our comparable "user score."
    user_score = round((total_positive / total_reviews) * 100)

    gap = user_score - metacritic
    name = game_raw.get("name", "This game")

    if gap <= -MIN_GAP:
        # Critics scored it well above what players actually feel.
        magnitude = abs(gap)
        confidence = _confidence_from_gap(magnitude, total_reviews)
        return {
            "insight": f"Critics scored {name} a {metacritic}  the people actually playing it disagree ({desc}).",
            "why_it_matters": (
                f"A {magnitude}-point gap is huge. Might be worth trusting the players on this one."
            ),
            "confidence": confidence,
            "category": CATEGORY,
        }

    if gap >= MIN_GAP:
        # Players love it more than critics did.
        magnitude = gap
        confidence = _confidence_from_gap(magnitude, total_reviews)
        return {
            "insight": f"{name}: {desc} on Steam, but only a {metacritic} from critics.",
            "why_it_matters": (
                f"{total_reviews:,} players say critics got this one wrong by {magnitude} points  "
                f"often means a game that plays better than it reviews."
            ),
            "confidence": confidence,
            "category": CATEGORY,
        }

    return None


def _confidence_from_gap(magnitude, total_reviews):
    """Scales confidence with both how big the gap is and how many
    reviews back up the user side of it. A 40-point gap backed by
    50,000 reviews should outrank a 21-point gap backed by 150."""
    gap_component = min(magnitude, 60) / 60  # caps out around a 60pt gap
    volume_component = min(total_reviews, 20000) / 20000  # caps out at 20k reviews

    score = (gap_component * 0.7) + (volume_component * 0.3)
    return round(score * 100)