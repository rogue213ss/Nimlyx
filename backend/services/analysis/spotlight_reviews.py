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

from steam import get_top_helpful_review
from formatters import trim_review_quote


def compute_spotlight_reviews(app_id, cc="US"):
    """Returns {"positive": {...} | None, "negative": {...} | None}.

    Each present side is a dict with:
      - quote: the trimmed, real review text
      - votes_up: how many players found it helpful (Steam's own count)
    """
    positive = get_top_helpful_review(app_id, cc, voted_up=True)
    negative = get_top_helpful_review(app_id, cc, voted_up=False)

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
