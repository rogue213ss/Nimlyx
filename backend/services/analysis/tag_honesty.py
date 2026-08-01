"""
TAG HONESTY, the filtered view of topic_engine.py.

Steam's own store tags are a claim ("Multiplayer") with no built-in
accountability for whether that claim holds up in practice. This
checks whether players actually discussing the topic a claimed tag
implies agree with it or not, using the same scan and the same
curated phrase dictionary as Player Pulse. No topic runs unless
the game actually carries a Steam tag or category that maps to it
(see topic_engine.TAG_TOPIC_MAP), so this never manufactures a check
for something the store page never claimed in the first place.
"""

from steam import get_review_texts
from services.analysis.topic_engine import analyze_topics, topics_for_tags

NUM_REVIEWS_TO_SCAN = 100
MIN_MENTIONS_TO_JUDGE = 3


def compute_tag_honesty(app_id, game_tags, cc="US"):
    """game_tags: the game's own Steam categories/genres. Returns a
    list of per-topic verdicts, or an empty list if none of the
    game's tags map to a tracked topic, or if there isn't enough
    review signal to judge the ones that do.
    """
    topic_ids = topics_for_tags(game_tags)
    if not topic_ids:
        return []

    review_texts = get_review_texts(app_id, cc, num_reviews=NUM_REVIEWS_TO_SCAN)
    if not review_texts:
        return []

    results = analyze_topics(review_texts, topic_ids=topic_ids)
    if not results:
        return []

    verdicts = []
    for topic in results:
        positive = topic["positive_count"]
        negative = topic["negative_count"]
        total_mentions = positive + negative

        if total_mentions < MIN_MENTIONS_TO_JUDGE:
            continue

        if negative > positive:
            agrees = False
            note = f"{negative} of the last {topic['total_scanned']} reviews flag issues here."
        elif positive > negative:
            agrees = True
            note = f"{positive} of the last {topic['total_scanned']} reviews back this up."
        else:
            # Exactly split, not enough of a lean either way to call it.
            continue

        verdicts.append({
            "label": topic["label"],
            "agrees": agrees,
            "note": note,
        })

    return verdicts