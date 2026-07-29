"""
WILSON SCORE — real statistics, replacing the fabricated Nimlyx Score.

This is the foundation the earlier "Nimlyx Score" should have been from
the start. What it was instead (see search.js, computeNimlyxScore,
now retired): when Metacritic existed, it was just the Metacritic
number relabeled — not a Nimlyx metric at all. When Metacritic was
absent, it was `50 + log10(review_count) * 8`, a formula based purely
on review VOLUME that never once checked whether those reviews were
positive or negative. A game with 100k negative reviews scored
identically to one with 100k positive reviews. Real bug, flagged and
tracked, now fixed by building the thing properly instead of patching
the old formula.

THE ACTUAL PROBLEM THIS SOLVES: raw positive-percentage is misleading
at the extremes. "98% positive" sounds better than "93% positive" —
until you learn the 98% is from 40 reviews and the 93% is from
250,000. The 250k-review game is the one you can actually trust that
number for. Naively ranking by raw percentage gets this backwards.

THE FIX: the Wilson score interval's LOWER BOUND (not the raw
percentage) is the standard, well-established statistical answer to
exactly this — it's the same ranking method popularized by Reddit for
comment ranking and Evan Miller's "How Not To Sort By Average Rating."
A small sample with a high raw percentage gets pulled DOWN toward
uncertainty automatically, without needing a separate, arbitrary
"minimum review count" cutoff bolted on afterward — the math itself
is conservative when the sample is thin. (Reputation Trajectory, the
next piece built on top of this, does NOT get this for free — a small
"recent reviews" bucket needs its own explicit minimum-sample guard,
because that comparison is between two Wilson scores, not one, and a
thin "recent" sample can still produce a misleading swing between two
individually-defensible numbers. That guard lives in
reputation_trajectory.py, not here.)

Formula: https://www.evanmiller.org/how-not-to-sort-by-average-rating.html
Same interval Steam's own "MOST HELPFUL" review sorting doesn't use
but arguably should — Nimlyx does.
"""

import math

# 1.96 = z-score for a 95% confidence interval — the standard,
# widely-used choice for this formula (not a tuned/arbitrary value).
DEFAULT_Z = 1.96

MIN_REVIEWS_TO_SCORE = 1  # below this, there's nothing to compute a confidence interval FROM at all


def wilson_lower_bound(positive, total, z=DEFAULT_Z):
    """Returns the lower bound of the Wilson score confidence interval
    as a float in [0, 1], or None if there's no data to compute one
    from. This is the number to rank/score by — never the raw
    positive/total percentage on its own.
    """
    if total is None or positive is None or total < MIN_REVIEWS_TO_SCORE:
        return None
    if positive < 0 or positive > total:
        return None  # malformed input — never silently clamp and pretend it was clean

    phat = positive / total
    z2 = z * z

    denominator = 1 + z2 / total
    centre_adjusted_probability = phat + z2 / (2 * total)
    adjusted_standard_deviation = math.sqrt((phat * (1 - phat) + z2 / (4 * total)) / total)

    lower_bound = (centre_adjusted_probability - z * adjusted_standard_deviation) / denominator
    return max(0.0, min(1.0, lower_bound))  # float rounding can nudge just past [0,1] at the extremes


# Verdict bands intentionally reuse Steam's own review-summary
# language ("Overwhelmingly Positive", "Very Positive", "Mixed", etc.)
# where they line up — familiar vocabulary players already trust,
# rather than inventing a parallel label system that means the same
# thing but requires learning a new scale.
_VERDICT_BANDS = (
    (95, "Overwhelmingly Positive"),
    (85, "Very Positive"),
    (70, "Positive"),
    (50, "Mixed"),
    (20, "Negative"),
    (0, "Overwhelmingly Negative"),
)


def _verdict_for(score_0_100):
    for floor, label in _VERDICT_BANDS:
        if score_0_100 >= floor:
            return label
    return _VERDICT_BANDS[-1][1]


def compute_nimlyx_score(total_positive, total_reviews):
    """The real Nimlyx Score. Returns None if there's no review data
    to compute one from — callers must treat None as "nothing to show
    here," never fall back to guessing or inventing a placeholder
    number.

    Returns a dict with the score AND its inputs, deliberately —
    every number Nimlyx shows should be inspectable, not a mystery
    figure. `note` is built to always be honest about what's actually
    known: the real percentage AND the real sample size, together.
    """
    lower_bound = wilson_lower_bound(total_positive, total_reviews)
    if lower_bound is None:
        return None

    score = round(lower_bound * 100)
    raw_percent = round((total_positive / total_reviews) * 100) if total_reviews else 0

    return {
        "value": score,
        "verdict": _verdict_for(score),
        "raw_percent": raw_percent,
        "total_reviews": total_reviews,
        "note": (
            f"{raw_percent}% of {total_reviews:,} reviews positive — "
            f"Wilson-adjusted for sample size."
        ),
    }
