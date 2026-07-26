"""
FRESH RELEASE — Insight Provider.

Flags games that launched recently. Ranked highest priority in
docs/homepage-engine.md's tiebreak order, because a brand-new release
usually has no review consensus yet — freshness is often the ONLY
honest thing another provider (Critic Gap, Review Momentum, Hidden
Gem) could even attempt to say about it, and most of them will
correctly return None for a two-day-old game. This provider fills
that gap: "verdict still forming" is itself a valid, honest insight.

Per docs/homepage-engine.md: every provider returns a dict with
{insight, why_it_matters, confidence, category} or None if it has
nothing honest to say.
"""

from datetime import datetime

CATEGORY = "fresh_release"

# Beyond this many days old, "fresh" stops being true — other
# providers (which need review data that's had time to accumulate)
# should be doing the talking by then instead.
MAX_DAYS_OLD = 14

# Steam's release_date.date format, e.g. "Jul 22, 2026"
DATE_FORMAT = "%b %d, %Y"


def generate(game_raw):
    """game_raw is the raw `data` dict from appdetails.

    Returns None if there's no parseable release date, the game is
    coming_soon (not actually out yet), or it's older than
    MAX_DAYS_OLD — never fabricates freshness from partial data.
    """
    release = game_raw.get("release_date") or {}

    if release.get("coming_soon"):
        return None

    release_date_str = release.get("date")
    if not release_date_str:
        return None

    try:
        parsed = datetime.strptime(release_date_str, DATE_FORMAT)
    except ValueError:
        # Steam sometimes returns non-standard strings ("Q1 2027",
        # "Coming soon", regional date formats) — if we can't parse
        # it with confidence, we don't guess.
        return None

    days_old = (datetime.now() - parsed).days

    if days_old < 0 or days_old > MAX_DAYS_OLD:
        return None

    name = game_raw.get("name", "This game")
    review_summary = game_raw.get("review_summary")
    confidence = _confidence_from_age(days_old)

    if days_old <= 2:
        insight = f"{name} just launched {_day_phrase(days_old)} — verdict still forming."
        why_it_matters = "Too new for a review consensus yet. Early adopters are the only ones who've weighed in so far."
    elif review_summary and review_summary.get("total_reviews", 0) > 0:
        desc = review_summary.get("review_score_desc", "")
        total = review_summary.get("total_reviews", 0)
        insight = f"{name} released {_day_phrase(days_old)} ago and already has {total:,} reviews — {desc}."
        why_it_matters = "An early signal is forming fast, which usually means real interest, not just launch-week noise."
    else:
        insight = f"{name} is a new release, out for {_day_phrase(days_old)} now."
        why_it_matters = "Still in its first two weeks — early enough that most players haven't formed an opinion yet."

    return {
        "insight": insight,
        "why_it_matters": why_it_matters,
        "confidence": confidence,
        "category": CATEGORY,
    }


def _day_phrase(days_old):
    if days_old == 0:
        return "today"
    if days_old == 1:
        return "yesterday"
    return f"{days_old} days"


def _confidence_from_age(days_old):
    """Confidence peaks at launch day and decays linearly to the
    MAX_DAYS_OLD cutoff — freshness is most newsworthy the moment it
    happens, and steadily less so as "new" becomes a stretch."""
    decay = days_old / MAX_DAYS_OLD
    score = 1 - (decay * 0.5)  # never drops below 50% just for being 14 days old
    return round(score * 100)
