"""
PLAYER PULSE, the unfiltered view of topic_engine.py.

(Named to stay distinct from the "Community Pulse" feature already on
the long-range roadmap under V3 AI — that one's a Gemini-powered
summary of broader community discussion. This one is a real-count
scan of actual Steam review text, no AI involved. Different features,
kept clearly separate now rather than colliding later.)

Scans a sample of recent reviews for every topic in TOPICS and
surfaces whichever ones players are actually talking about, split
into what they like and what they don't. No topic is guaranteed to
appear. A game with nothing matching any curated phrase produces an
empty list, not a placeholder.
"""

from steam import get_review_texts
from services.analysis.topic_engine import analyze_topics

NUM_REVIEWS_TO_SCAN = 100
MIN_MENTIONS_TO_SURFACE = 3


def compute_player_pulse(app_id, cc="US"):
    """Returns a dict with a `positives` list and a `concerns` list,
    each entry a plain sentence built from real counts, or None if
    there isn't enough signal to say anything honest.
    """
    review_texts = get_review_texts(app_id, cc, num_reviews=NUM_REVIEWS_TO_SCAN)
    if not review_texts:
        return None

    results = analyze_topics(review_texts)
    if not results:
        return None

    positives = []
    concerns = []

    for topic in results:
        total = topic["total_scanned"]

        if topic["positive_count"] >= MIN_MENTIONS_TO_SURFACE:
            positives.append({
                "label": topic["label"],
                "count": topic["positive_count"],
                "total_scanned": total,
                "note": f"Came up in {topic['positive_count']} of the last {total} reviews.",
            })

        if topic["negative_count"] >= MIN_MENTIONS_TO_SURFACE:
            concerns.append({
                "label": topic["label"],
                "count": topic["negative_count"],
                "total_scanned": total,
                "note": f"Came up in {topic['negative_count']} of the last {total} reviews.",
            })

    if not positives and not concerns:
        return None

    positives.sort(key=lambda p: p["count"], reverse=True)
    concerns.sort(key=lambda c: c["count"], reverse=True)

    return {
        "positives": positives,
        "concerns": concerns,
        "total_scanned": len(review_texts),
    }
