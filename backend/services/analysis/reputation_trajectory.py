"""
REPUTATION TRAJECTORY — is this game's reception getting better or
worse lately, compared to its all-time reputation?

This is the "buying insight" Steam never surfaces directly: an 88%
overall rating can be hiding a game that's actively improving (a
rocky launch since patched into shape) or one that's quietly
declining (dead servers, a bad update) — and the overall number alone
can't tell you which. Steam's own store page doesn't show a recent-
vs-all-time split anywhere a shopper would naturally see it.

TWO SEPARATE GUARDS, NOT ONE — this is the part that's easy to get
wrong and worth being explicit about:

1. MIN_RECENT_REVIEWS — the recent bucket needs enough reviews to
   mean anything at all. Unlike the main Nimlyx Score (see
   wilson_score.py), where a thin sample is automatically handled by
   the Wilson lower bound pulling the number down on its own, this
   is a COMPARISON between two Wilson scores. A recent bucket of, say,
   4 reviews can still produce a "confident-looking" gap against the
   all-time score just from the two samples not overlapping much —
   Wilson doesn't save you here because both sides are already
   individually defensible numbers, on the recent window's own thin
   evidence.

2. MIN_MEANINGFUL_GAP — even with enough recent reviews, small
   fluctuations are normal and don't deserve a "Turning Around" or
   "Losing Its Shine" headline. Only a genuinely large gap between
   the two Wilson-adjusted scores gets called a trend; anything
   smaller renders nothing at all rather than overclaiming a swing
   that's really just noise.

If either guard fails, this returns None — exclude the claim
entirely, same discipline as New Releases excluding an unparseable
date instead of guessing at one.
"""

from services.analysis.wilson_score import compute_nimlyx_score
from steam import get_review_summary

# Steam's own review API convention for "recent" — a 30-day window is
# also roughly what Steam's own store page uses for its "Recent
# Reviews" label, so this lines up with vocabulary players already
# recognize rather than inventing a different window.
RECENT_WINDOW_DAYS = 30

# User-set floor (see conversation): balanced — catches most actively-
# played games without rendering a trend claim off a handful of reviews.
MIN_RECENT_REVIEWS = 25

# How far apart the two Wilson-adjusted scores need to be before this
# is treated as a real trend rather than normal week-to-week noise.
# Both scores are already on the same 0-100 Wilson-adjusted scale (not
# raw percentages), so this threshold is smaller than critic_gap.py's
# MIN_GAP=20 (which compares a raw Metacritic score against a raw
# Steam percentage — a noisier, cross-scale comparison). Tunable if
# real-world data shows it's too loose or too strict.
MIN_MEANINGFUL_GAP = 8


def compute_trajectory(app_id, cc="US", overall_summary=None):
    """overall_summary: the already-fetched all-time get_review_summary()
    result for this game (routes/game.py fetches this once and reuses
    it for both the main Nimlyx Score and this — no reason to ask
    Steam for the same all-time numbers twice).

    Returns None whenever there isn't enough evidence for an honest
    trend claim — no overall data, no recent data, too few recent
    reviews, or a gap too small to call a real trend. Never guesses.
    """
    if not overall_summary:
        return None

    overall_score = compute_nimlyx_score(
        overall_summary.get("total_positive"),
        overall_summary.get("total_reviews"),
    )
    if overall_score is None:
        return None

    recent_summary = get_review_summary(app_id, cc, day_range=RECENT_WINDOW_DAYS)
    if not recent_summary or recent_summary["total_reviews"] < MIN_RECENT_REVIEWS:
        return None

    recent_score = compute_nimlyx_score(
        recent_summary["total_positive"],
        recent_summary["total_reviews"],
    )
    if recent_score is None:
        return None

    gap = recent_score["value"] - overall_score["value"]

    if abs(gap) < MIN_MEANINGFUL_GAP:
        return None

    direction = "up" if gap > 0 else "down"
    label = "Turning Around" if direction == "up" else "Losing Its Shine"

    # Plain language, same discipline as wilson_score.py's note fix —
    # the real numbers (both percentages, side by side) are what
    # builds trust here, not a method name or a hedge-heavy sentence.
    note = (
        f"Recent reviews are {recent_score['raw_percent']}% positive, "
        f"versus {overall_score['raw_percent']}% all-time."
    )

    return {
        "direction": direction,
        "label": label,
        "recent_score": recent_score["value"],
        "recent_percent": recent_score["raw_percent"],
        "recent_review_count": recent_summary["total_reviews"],
        "overall_score": overall_score["value"],
        "overall_percent": overall_score["raw_percent"],
        "note": note,
    }
