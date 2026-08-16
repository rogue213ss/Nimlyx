"""Helpers that reshape raw scraped/JSON game data into the dicts the
Jinja templates and frontend JS expect."""
import re

from steam_images import build_image_candidates


def format_price(cents):
    if cents is None:
        return "Free"
    s = str(cents)
    if not s.isdigit():
        return "Free"
    n = int(s)
    return "Free" if n == 0 else f"${n / 100:.2f}"


def platform_label(platforms):
    names = {"win": "Windows", "mac": "macOS", "linux": "Linux"}
    labels = [names[p] for p in platforms if p in names]
    return ", ".join(labels) if labels else "—"


def to_game_dict(item, stat_fields=None):
    """Shapes a raw scraped game dict into what index.html expects.

    header_image here is the scraped search-result thumbnail Steam
    itself just served us -- guaranteed to exist, nothing guessed.
    image_candidates are unverified higher-res URLs the frontend may
    upgrade to client-side (see image-upgrade.js); they're never
    rendered directly.
    """
    app_id = item.get("id")
    base = {
        "id": app_id,
        "name": item.get("name"),
        "header_image": item.get("image"),
        "image_candidates": build_image_candidates(app_id),
        "analyze_url": f"/search?q={item.get('name', '')}",
    }
    if stat_fields:
        base.update(stat_fields)
    return base


def trim_review_quote(text, target_min=180, target_max=250):
    """Shortens a real Steam review to a display-friendly quote,
    roughly target_min-target_max characters — never a wall of text.

    Only shortens WHERE the reviewer's own words naturally end: prefers
    cutting at a sentence boundary that falls inside the window, and
    only falls back to a whole-word cut (with a trailing ellipsis) when
    no sentence break exists in range. Never rewrites, paraphrases, or
    adds anything the reviewer didn't write.
    """
    if not text:
        return text

    collapsed = " ".join(text.split())  # real review text is full of raw newlines/whitespace
    if len(collapsed) <= target_max:
        return collapsed

    window = collapsed[:target_max]

    sentence_end = max(window.rfind(". "), window.rfind("! "), window.rfind("? "))
    if sentence_end >= target_min:
        return collapsed[:sentence_end + 1]

    last_space = window.rfind(" ")
    cut = last_space if last_space >= target_min else target_max
    return collapsed[:cut].rstrip(",;:- ") + "..."


def to_discover_card(game):
    """Shapes a scraped game into Nimlyx's canonical result-card
    contract (Sprint 3 Phase 4) -- the same shape /api/search-results
    returns for Search:

        { app_id, name, header_image, price, discount,
          review_percentage, review_count, genres }

    Deliberately presentation-free: no formatted price strings, no
    footer_left/footer_right, no analyze_url. discover.js (like
    GameGrid already does for Search) is responsible for turning
    these raw fields into whatever its card component wants to
    display -- that keeps this function reusable by any future
    result surface without baking in one template's layout.

    genres is always [] here -- Discover's scrape (fetch_discover_games)
    doesn't fetch per-game genre data today, unlike Search's concurrent
    get_appdetails lookup. Deferred until a real UI need shows up, since
    wiring it in means an extra live Steam call per card, same cost
    Search already pays. review_count is also always None -- Discover's
    scrape only has an aggregate review percentage, not a raw count.
    """

    def parse_discount(value):
        if value is None:
            return 0
        if isinstance(value, int):
            return value
        digits = re.sub(r"[^\d]", "", str(value))
        return int(digits) if digits else 0

    return {
        "app_id": game.get("id"),
        "name": game.get("name"),
        # header_image is the guaranteed base every card renders
        # immediately: header_default was built with zero live Steam
        # calls (see steam_images.default_header_image), and
        # game["image"] -- the scraped search-result thumbnail -- is
        # only a last-resort fallback for the rare case there's no
        # app id to build a CDN URL from.
        "header_image": game.get("header_default") or game.get("image"),
        # Unverified higher-res candidates. Never rendered directly --
        # discover.js probes each with a real Image() load and only
        # swaps one in on a successful onload.
        "image_candidates": game.get("image_candidates") or [],
        "price": game.get("final_price"),
        "original_price": game.get("original_price"),
        "discount": parse_discount(game.get("discount_percent")),
        "review_percentage": game.get("review_percent"),
        "review_summary": game.get("review_summary"),
        "review_count": None,
        "genres": [],
    }