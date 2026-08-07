"""Similar Games — Sprint 5 foundation. "More Like This."

Deliberately simple and deterministic, per spec: no recommendation
engine, no AI, no database, no new analysis logic. Two signals only:

  1. Genre overlap, via Steam's own tags= search facet.
  2. Developer/publisher overlap, by REUSING build_game_detail()'s
     already-fetched developer_games/publisher_games -- zero extra
     Steam calls for this half.

IMPORTANT ID-SPACE NOTE (read before touching genre matching):
appdetails' `genres` field carries Steam's GENRE ids (e.g. "1" for
Action). Steam's own search/results scrape filters by community TAG
ids instead (e.g. 19 for Action) -- a different, unrelated numbering.
This module never guesses a mapping between the two. It only uses
steam.GENRE_TAG_IDS, the same tag-id table already proven correct in
production by the Discover wizard (steam.fetch_discover_games). That
table only covers 8 genres (action, fantasy, horror, rpg, racing,
puzzle, simulation, strategy) -- when a game's genres don't match any
of those (Steam has dozens more: Adventure, Indie, Casual, Sports,
Free to Play, etc.), genre-based matching is honestly skipped rather
than guessed at. This is Nimlyx Tradition #003's lesson applied here:
a wrong tag id doesn't error, it just silently returns unrelated
games, which is worse than returning fewer, ALWAYS RIGHT ones.

FAILURE MODE: every step in get_similar_games() is wrapped so a
Steam failure, empty response, or unmapped genre degrades to fewer
results or an empty list -- never an exception that could take down
the rest of the game detail page. Per the historical rate-limiting
issue, a failed/empty Steam response here is never treated as "these
aren't real games" -- it's treated as "no similar-games data
available right now," and the section simply doesn't render.
"""

from steam import fetch_games_by_tags, GENRE_TAG_IDS
from steam_images import default_header_image, build_image_candidates
from formatters import to_discover_card

# Reverse-lookup from a Steam genre DESCRIPTION string (as returned by
# appdetails' genres[].description, e.g. "RPG") to the wizard's own
# genre keys (steam.GENRE_TAG_IDS' keys, e.g. "rpg") -- so this module
# can go from "this game's real genre labels" to "a tag id we've
# already proven correct" without inventing any new ids of its own.
# Steam's own description casing/wording for these 8 is stable enough
# in practice that a simple exact-match (case-insensitive) covers them;
# anything not listed here is a genre this module doesn't attempt to
# match on, by design (see module docstring).
_GENRE_DESCRIPTION_TO_KEY = {
    "action": "action",
    "rpg": "rpg",
    "role-playing": "rpg",
    "racing": "racing",
    "puzzle": "puzzle",
    "simulation": "simulation",
    "strategy": "strategy",
    # "fantasy" and "horror" aren't genre labels Steam's appdetails
    # actually returns (they're tag-only concepts on Steam) -- kept
    # out of this map on purpose rather than guessing at a genre
    # string Steam never sends here.
}


def _resolve_tag_ids(genres):
    """genres: raw list of genre description strings off appdetails
    (e.g. ["Action", "RPG"]). Returns the subset of steam.GENRE_TAG_IDS
    values this game's real genres map to -- possibly empty."""
    if not genres:
        return []

    tag_ids = []
    for description in genres:
        if not description:
            continue
        key = _GENRE_DESCRIPTION_TO_KEY.get(description.strip().lower())
        if key and key in GENRE_TAG_IDS:
            tag_id = GENRE_TAG_IDS[key]
            if tag_id not in tag_ids:
                tag_ids.append(tag_id)
    return tag_ids


def _shape_scraped_candidates(games):
    """Tag-scrape results come back in the same raw scraped shape
    fetch_games_by_credit's callers already reshape (see
    related_games.py) -- same image pipeline, same to_discover_card
    contract, so Similar Games cards render identically to
    Developer/Publisher cards with zero new frontend work."""
    shaped = []
    for g in games:
        app_id = g.get("id")
        if not app_id or not g.get("name"):
            # Never render a blank/incomplete card -- matches the
            # historical "don't show blank cards" requirement.
            continue
        g["header_default"] = default_header_image(app_id) or g.get("image")
        g["image_candidates"] = build_image_candidates(app_id)
        shaped.append(to_discover_card(g))
    return shaped


def fetch_genre_candidates(app_id, genres, cc="US", count=10):
    """The ONLY Steam-calling half of Similar Games. Split out from the
    merge step below specifically so routes/game.build_game_detail()
    can run this concurrently with the developer/publisher lookups
    (in the same ThreadPoolExecutor) instead of waiting for them to
    finish first -- this is the one new network call Similar Games
    introduces, so it gets the same "run it in parallel, don't add to
    the critical path" treatment every other Steam call in
    build_game_detail() already gets.

    Returns a list of to_discover_card-shaped candidates, or [] if
    this game's genres don't map to any known tag id (see module
    docstring) or the Steam request itself fails. Never raises.
    """
    try:
        tag_ids = _resolve_tag_ids(genres)
        if not tag_ids:
            return []
        scraped = fetch_games_by_tags(tag_ids, exclude_app_id=app_id, count=count, cc=cc)
        return _shape_scraped_candidates(scraped)
    except Exception:
        return []


def merge_similar_games(genre_cards, app_id, developer_games=None, publisher_games=None, count=6):
    """Pure, in-memory merge -- no I/O, negligible cost. Called AFTER
    genre_cards (fetch_genre_candidates, above) and developer_games/
    publisher_games (already fetched elsewhere in build_game_detail)
    have all resolved.

    Genre matches are ordered first (the actual "similar" signal),
    then developer/publisher overlap fills any remaining slots.
    Deduped by app_id so a game that's both genre-similar AND from the
    same studio doesn't take two slots, and so this section isn't just
    a rerun of the Developer/Publisher carousels already on the page.
    """
    try:
        credit_cards = list(developer_games or []) + list(publisher_games or [])

        merged = []
        seen_ids = {str(app_id)}  # never include the game itself
        for card in list(genre_cards or []) + credit_cards:
            candidate_id = card.get("app_id")
            if not candidate_id or str(candidate_id) in seen_ids:
                continue
            seen_ids.add(str(candidate_id))
            merged.append(card)
            if len(merged) >= count:
                break
        return merged
    except Exception:
        return []


def get_similar_games(app_id, genres, developer_games=None, publisher_games=None, cc="US", count=6):
    """Convenience wrapper for any caller that doesn't need the two
    halves run concurrently (routes/game.py doesn't use this directly
    -- see fetch_genre_candidates + merge_similar_games above, called
    separately so the Steam call can run in parallel with dev/pub).
    Kept for completeness/tests: does the same work, sequentially.
    """
    genre_cards = fetch_genre_candidates(app_id, genres, cc=cc, count=count + 4)
    return merge_similar_games(genre_cards, app_id, developer_games, publisher_games, count=count)