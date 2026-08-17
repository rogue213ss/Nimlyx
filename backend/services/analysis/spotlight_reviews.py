"""
SPOTLIGHT REVIEWS — the evidence behind Nimlyx Analysis.

The Nimlyx Score, Reputation Trajectory, and Players Loved/Mentioned
sections are all Nimlyx's own conclusions, computed from review data.
This module is the part a shopper can independently verify against:
one real, most-helpful positive review and one real, most-helpful
negative review, straight from Steam's own helpfulness ranking (see
steam.get_top_helpful_review) — not cherry-picked by Nimlyx, not
summarized, not rewritten. The only thing done to the text is
trimming for length (formatters.trim_review_quote), and only at
natural sentence/word boundaries — never for content.

Same discipline as the rest of this project: if a game has no
reviews in a given direction, that side is None. The frontend must
hide that side of the spotlight rather than render an empty quote
block or invent one.
"""

from concurrent.futures import ThreadPoolExecutor

from steam import get_top_helpful_review, get_helpful_reviews
from formatters import trim_review_quote

# Game page review preview cap (Reviews section -> "View more on Steam").
# Kept as one named constant so the frontend's max-10-cards assumption
# and this module's fetch size can never silently drift apart.
MAX_PREVIEW_REVIEWS = 10


def compute_spotlight_reviews(app_id, cc="US"):
    """Returns {"positive": {...} | None, "negative": {...} | None}.

    Each present side is a dict with:
      - quote: the trimmed, real review text
      - votes_up: how many players found it helpful (Steam's own count)

    The positive/negative lookups are two independent Steam calls
    (see get_top_helpful_review) with no shared state -- run
    concurrently rather than one after the other, same reasoning as
    every other independent-calls grouping in this codebase.
    """
    with ThreadPoolExecutor(max_workers=2) as executor:
        positive_future = executor.submit(get_top_helpful_review, app_id, cc, True)
        negative_future = executor.submit(get_top_helpful_review, app_id, cc, False)
        positive = positive_future.result()
        negative = negative_future.result()

    def shape(review):
        if not review or not review.get("text"):
            return None
        return {
            "quote": trim_review_quote(review["text"]),
            "votes_up": review.get("votes_up", 0),
        }

    return {
        "positive": shape(positive),
        "negative": shape(negative),
    }


def compute_review_preview(app_id, cc="US", max_reviews=MAX_PREVIEW_REVIEWS):
    """Returns {"positive": [...], "negative": [...]}, up to
    `max_reviews` real Steam reviews total, for the game page's
    Reviews section (10-review preview + All/Positive/Negative
    filter, then "View more reviews on Steam").

    This is the multi-review sibling of compute_spotlight_reviews()
    above -- same principle (real, unedited, helpfulness-ranked Steam
    reviews, only trimmed for display length), just more of them per
    side instead of one. Built on get_helpful_reviews() rather than
    get_top_helpful_review() so it can collect several per direction
    in the same request shape.

    Balancing (target: don't let one sentiment silently swamp the
    other just because we asked for a fixed number per side): each
    side is first fetched up to a half-share of `max_reviews`. If one
    side comes back short (e.g. a very well-reviewed game has only 1
    negative review in the sample), the shortfall is backfilled from
    the other side so the preview still totals up to `max_reviews`
    whenever the underlying data supports it -- never fabricated,
    just not artificially capped at the half-share when only one
    side is available.
    """
    half = max_reviews // 2  # 10 -> 5/5, backfilled below if lopsided

    with ThreadPoolExecutor(max_workers=2) as executor:
        # Independent Steam calls, same reasoning as
        # compute_spotlight_reviews() above -- run concurrently.
        # Ask for the full max_reviews from Steam per side so there's
        # real headroom to backfill from if the other side is short.
        positive_future = executor.submit(get_helpful_reviews, app_id, cc, True, max_reviews)
        negative_future = executor.submit(get_helpful_reviews, app_id, cc, False, max_reviews)
        positive_pool = positive_future.result()
        negative_pool = negative_future.result()

    take_positive = min(half, len(positive_pool))
    take_negative = min(half, len(negative_pool))

    remaining = max_reviews - take_positive - take_negative
    if remaining > 0:
        # One side ran short of its half-share -- give the leftover
        # slots to whichever side actually has more reviews to offer,
        # up to what's left in that side's pool.
        extra_positive = min(remaining, len(positive_pool) - take_positive)
        take_positive += extra_positive
        remaining -= extra_positive
        if remaining > 0:
            take_negative += min(remaining, len(negative_pool) - take_negative)

    def shape_review(review, recommended):
        return {
            "quote": trim_review_quote(review["text"]),
            "votes_up": review.get("votes_up", 0),
            "timestamp_created": review.get("timestamp_created"),
            "recommended": recommended,
        }

    return {
        "positive": [shape_review(r, True) for r in positive_pool[:take_positive]],
        "negative": [shape_review(r, False) for r in negative_pool[:take_negative]],
    }
