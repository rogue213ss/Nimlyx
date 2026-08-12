"""Sprint 4 Phase 3 -- "More From Developer" / "More From Publisher".

Deliberately thin: all the real work (the Steam scrape, the image
pipeline, the card shape) already exists and is reused as-is here,
not reimplemented:

- steam.fetch_games_by_credit() -- same search/results scrape
  fetch_discover_games() uses, filtered by developer=/publisher=
  instead of tags/os/maxprice (see steam.py for the shared
  _scrape_search_results() core both now call).
- steam_images.default_header_image() / build_image_candidates() --
  the same zero/low-cost image pipeline Discover's cards use.
- formatters.to_discover_card() -- the same canonical result-card
  contract Search and Discover both already return
  ({app_id, name, header_image, price, discount, review_percentage,
  review_count, genres}), so the game page's carousels need no card
  shape of their own.

No live per-card appdetails/price calls happen here (unlike Discover's
paginated slice, which calls fetch_authoritative_price per visible
card) -- these are secondary, below-the-fold sections, so the scraped
price/discount/review data is good enough and keeps the game page's
single load fast, per Sprint 4's performance requirements.
"""

from steam import fetch_games_by_credit
from steam_images import default_header_image, build_image_candidates
from formatters import to_discover_card


def _credit_games(field, names, exclude_app_id, cc, count):
    """Shared by get_developer_games/get_publisher_games -- only the
    field name differs between them. Uses just the first credited
    name (Steam's own developer/publisher search only takes one term
    anyway, and the first credit is normally the primary one)."""
    if not names:
        return []

    value = names[0]
    games = fetch_games_by_credit(field, value, exclude_app_id=exclude_app_id, count=count, cc=cc)

    for g in games:
        app_id = g.get("id")
        g["header_default"] = g.get("image") or default_header_image(app_id)
        g["image_candidates"] = build_image_candidates(app_id)

    return [to_discover_card(g) for g in games]


def get_developer_games(developers, exclude_app_id=None, cc="US", count=10):
    """developers: the game's own `developers` list, straight off
    appdetails (raw.get("developers", []))."""
    return _credit_games("developer", developers, exclude_app_id, cc, count)


def get_publisher_games(publishers, exclude_app_id=None, cc="US", count=10):
    """publishers: the game's own `publishers` list, straight off
    appdetails (raw.get("publishers", []))."""
    return _credit_games("publisher", publishers, exclude_app_id, cc, count)
