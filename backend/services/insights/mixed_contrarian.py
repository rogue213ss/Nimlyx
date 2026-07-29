"""
MIXED / CONTRARIAN — Insight Provider.

Flags games where Steam's own player base is split on it — not
"underrated" (Hidden Gem) or "critics vs. players" (Critic Gap), but
players disagreeing with THEMSELVES at scale. This is Nimlyx's second
editorial provider: no external data dependency (Metacritic-free),
so it can fire far more reliably than Critic Gap while still telling
a story Steam's storefront never surfaces on its own — Steam shows a
"Mixed" badge with no context; this explains why that split is worth
knowing about before buying.

Per docs/homepage-engine.md: every provider returns a dict with
{insight, why_it_matters, confidence, category} or None if it has
nothing honest to say. Confidence is NOT comparable across providers
(see selector.py) — it only ranks candidates within this category.

Deliberately narrow: a mild 60/40 split on a niche game with 150
reviews isn't a story. A near-50/50 split at real volume, especially
on a game popular enough that lots of people already have an opinion,
is the one worth surfacing. Chasing frequency by loosening this
defeats the point — same principle as Critic Gap.
"""

# Steam's own "Mixed" review-score band, by positive ratio. Staying
# inside Steam's own bucket definition (rather than inventing our
# own cutoffs) keeps this provider honest — we're surfacing games
# Steam ITSELF already considers divisive, not manufacturing a story
# out of ordinary variance.
MIXED_RATIO_LOW = 0.40
MIXED_RATIO_HIGH = 0.69

# Below this, a "Mixed" label is too noisy to trust — a handful of
# early reviews can land anywhere.
MIN_TOTAL_REVIEWS = 150

CATEGORY = "mixed_contrarian"


def generate(game_raw):
    """game_raw is the raw `data` dict from appdetails, with an added
    `review_summary` key from get_review_summary() (may be None).

    Returns None if review data doesn't exist, volume is too low, or
    the split isn't actually inside Steam's own "Mixed" band — never
    fabricates a controversy from a game that's just mildly liked.
    """
    review_summary = game_raw.get("review_summary")
    if not review_summary:
        return None

    total_reviews = review_summary.get("total_reviews", 0)
    if total_reviews < MIN_TOTAL_REVIEWS:
        return None

    total_positive = review_summary.get("total_positive", 0)
    ratio = total_positive / total_reviews

    if not (MIXED_RATIO_LOW <= ratio <= MIXED_RATIO_HIGH):
        return None

    name = game_raw.get("name", "This game")
    desc = review_summary.get("review_score_desc", "Mixed")
    positive_percent = round(ratio * 100)

    confidence = _confidence_from_split(ratio, total_reviews)

    return {
        "insight": (
            f"{name} is sitting at {positive_percent}% positive {desc}. "
            f"Players can't agree on this one."
        ),
        "why_it_matters": (
            f"{total_reviews:,} reviews and still split down the middle. Not a fluke, "
            f"people genuinely disagree, so it's worth seeing why before you pick a side."
        ),
        "confidence": confidence,
        "category": CATEGORY,
    }


def _confidence_from_split(ratio, total_reviews):
    """Scales confidence with how close to a true 50/50 split the
    game sits (maximum disagreement = most interesting) and how much
    volume backs it up. A 51/49 split on 40,000 reviews should heavily
    outrank a 68/32 split on 200 — the former is a real fault line,
    the latter is barely inside the Mixed band at all."""
    closeness_to_even = 1 - (abs(ratio - 0.5) / 0.19)  # 0.19 = distance from 0.5 to either band edge
    closeness_to_even = max(0, closeness_to_even)

    volume_component = min(total_reviews, 20000) / 20000  # caps out at 20k reviews

    score = (closeness_to_even * 0.65) + (volume_component * 0.35)
    return round(score * 100)