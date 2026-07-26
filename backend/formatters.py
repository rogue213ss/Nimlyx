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


def to_discover_card(game):
    """Shapes a scraped game into the {name, header_image, analyze_url,
    footer_left, footer_right} card fields discover.js renders."""

    def parse_discount(value):
        if value is None:
            return 0
        if isinstance(value, int):
            return value
        digits = re.sub(r"[^\d]", "", str(value))
        return int(digits) if digits else 0

    review_percent = game.get("review_percent")
    review_label = f"{review_percent}% Positive" if review_percent is not None else "No reviews yet"

    discount_percent = parse_discount(game.get("discount_percent"))
    price_label = format_price(game.get("final_price"))
    footer_left = f"-{discount_percent}% · {price_label}" if discount_percent > 0 else price_label

    return {
        "id": game.get("id"),
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
        "analyze_url": f"/search?q={game.get('name', '')}",
        "footer_left": footer_left,
        "footer_right": review_label,
    }
