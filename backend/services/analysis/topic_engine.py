"""
TOPIC ENGINE, shared foundation for Player Pulse and Tag Honesty.

The pitch behind this feature was "no AI, no hallucination, just real
frequency analysis." Taken literally, plain keyword counting on real
review text has a real failure mode: matching a neutral word like
"combat" tells you a review mentions combat, not whether it liked or
hated it. Getting from there to a clean checkmark or warning bullet
either needs actual sentiment inference (a bigger, riskier build than
"frequency analysis" implies) or a different foundation.

The foundation used here: every phrase in the dictionary below already
carries its own polarity in its wording. "dead servers" is negative on
its face. "great combat" is positive on its face. Counting how often
players use phrasing that already means something, instead of trying
to compute what a neutral word like "combat" means in context, is what
keeps this an honest frequency count instead of a disguised sentiment
model wearing a frequency count's clothing.

The real, disclosed limitation: a review that says "the fighting felt
clunky and unsatisfying" without ever using one of the curated phrases
below is invisible to this engine. It undercounts. It does not
overclaim. That tradeoff is the right one here, consistent with this
project's standing rule: exclude rather than guess.

Every result carries how many reviews were actually scanned, since
get_review_texts caps at 100 reviews per call. "Mentioned in 12 of the
last 100 reviews" is the honest phrasing. "Mentioned in reviews" is
not, since it implies the whole review corpus was checked, and it
wasn't.
"""

import re

# Each topic: a label for display, plus phrase lists that already
# carry their own polarity. Deliberately not exhaustive. Real players
# use far more phrasings than any curated list can cover, and that's
# the accepted tradeoff described above.
TOPICS = {
    "combat": {
        "label": "Combat",
        "positive": [
            "great combat", "combat is great", "amazing combat", "fun combat",
            "combat feels great", "satisfying combat", "combat is fun",
            "combat is amazing", "love the combat",
        ],
        "negative": [
            "boring combat", "combat is boring", "clunky combat",
            "combat feels clunky", "bad combat", "combat is bad",
            "combat is repetitive", "combat feels bad",
        ],
    },
    "soundtrack": {
        "label": "Soundtrack",
        "positive": [
            "amazing soundtrack", "great soundtrack", "soundtrack is amazing",
            "soundtrack is great", "beautiful soundtrack", "love the soundtrack",
            "incredible ost", "amazing ost",
        ],
        "negative": [
            "forgettable soundtrack", "soundtrack is forgettable",
            "bad soundtrack", "soundtrack is bad", "annoying music",
        ],
    },
    "story": {
        "label": "Story",
        "positive": [
            "great story", "story is great", "amazing story", "love the story",
            "story is amazing", "compelling story", "story is compelling",
        ],
        "negative": [
            "weak story", "story is weak", "boring story", "story is boring",
            "story is bad", "bad story", "confusing story",
        ],
    },
    "ending": {
        "label": "Ending",
        "positive": [
            "great ending", "ending is great", "satisfying ending",
            "loved the ending",
        ],
        "negative": [
            "weak ending", "ending is weak", "bad ending", "ending is bad",
            "disappointing ending", "rushed ending",
        ],
    },
    "servers": {
        "label": "Server Stability",
        "positive": [
            "servers are great", "great servers", "servers are stable",
            "matchmaking is fast", "matchmaking is great",
        ],
        "negative": [
            "dead servers", "servers are dead", "empty servers",
            "server issues", "server problems", "empty lobbies",
            "no matchmaking", "matchmaking is broken", "matchmaking is dead",
            "can't find a match", "cant find a match", "no players online",
        ],
    },
    "performance": {
        "label": "Performance",
        "positive": [
            "runs great", "well optimized", "great optimization",
            "runs smoothly", "performance is great",
        ],
        "negative": [
            "poorly optimized", "badly optimized", "frame drops",
            "fps drops", "constant crashes", "keeps crashing",
            "full of bugs", "buggy mess", "performance is bad",
            "runs terribly", "stuttering",
        ],
    },
    "replayability": {
        "label": "Replayability",
        "positive": [
            "great replayability", "highly replayable", "lots of replay value",
            "high replay value",
        ],
        "negative": [
            "no replay value", "not replayable", "low replay value",
            "once and done",
        ],
    },
    "grinding": {
        "label": "Grinding",
        "positive": [
            "grinding is fun", "grind is rewarding", "grinding is rewarding",
        ],
        "negative": [
            "too grindy", "extremely grindy", "grinding is boring",
            "grind is boring", "feels like a grind", "pure grind",
        ],
    },
}

# Which topics are worth checking for a given Steam store category or
# genre label. Used by tag_honesty.py to only surface a topic when the
# game actually claims something related to it, since checking every
# topic against every tag would produce noise, not accountability.
TAG_TOPIC_MAP = {
    "Multiplayer": ["servers"],
    "Online PvP": ["servers"],
    "Online Co-op": ["servers"],
    "MMO": ["servers", "grinding"],
    "Massively Multiplayer": ["servers", "grinding"],
}


def _compile_patterns(topics):
    compiled = {}
    for topic_id, info in topics.items():
        compiled[topic_id] = {
            "positive": [re.compile(r"\b" + re.escape(p) + r"\b", re.IGNORECASE) for p in info["positive"]],
            "negative": [re.compile(r"\b" + re.escape(p) + r"\b", re.IGNORECASE) for p in info["negative"]],
        }
    return compiled


_COMPILED = _compile_patterns(TOPICS)


def analyze_topics(review_texts, topic_ids=None):
    """review_texts: list of plain review strings from
    steam.get_review_texts(). topic_ids: restrict the scan to these
    topic keys, or None to check every topic in TOPICS.

    Returns a list of dicts, one per topic that had at least one
    match, sorted by total mention count descending. Each entry
    reports positive_count and negative_count as counts of DISTINCT
    reviews (a review repeating "great combat" three times still
    counts once), plus total_scanned so the caller can build an
    honest "of the last N reviews" note.

    Returns an empty list if there's nothing to scan or nothing
    matched, never a fabricated placeholder result.
    """
    if not review_texts:
        return []

    ids_to_check = topic_ids if topic_ids is not None else list(TOPICS.keys())
    total_scanned = len(review_texts)

    results = []
    for topic_id in ids_to_check:
        if topic_id not in TOPICS:
            continue

        patterns = _COMPILED[topic_id]
        positive_count = sum(
            1 for text in review_texts
            if any(p.search(text) for p in patterns["positive"])
        )
        negative_count = sum(
            1 for text in review_texts
            if any(p.search(text) for p in patterns["negative"])
        )

        if positive_count == 0 and negative_count == 0:
            continue

        results.append({
            "topic_id": topic_id,
            "label": TOPICS[topic_id]["label"],
            "positive_count": positive_count,
            "negative_count": negative_count,
            "total_scanned": total_scanned,
        })

    results.sort(key=lambda r: r["positive_count"] + r["negative_count"], reverse=True)
    return results


def topics_for_tags(game_tags):
    """game_tags: the game's own Steam categories/genres (plain
    strings). Returns the deduplicated list of topic ids worth
    checking, based on TAG_TOPIC_MAP. Empty list if none of the
    game's tags map to a topic this engine tracks.
    """
    topic_ids = []
    for tag in game_tags or []:
        for topic_id in TAG_TOPIC_MAP.get(tag, []):
            if topic_id not in topic_ids:
                topic_ids.append(topic_id)
    return topic_ids