"""
HOMEPAGE — server-side rendered, plus the two client-rendered
pages (/discover, /search) that just hand off to their JS.
"""
import requests
from flask import Blueprint, render_template

from region import get_region_code
from steam import fetch_browse_category
from formatters import format_price, platform_label, to_game_dict

pages_bp = Blueprint("pages", __name__)


def hero_image_url(appid, fallback):
    """
    NIMLYX TRADITION #004 — "We almost accepted blurry." Steam's search
    only gives a tiny 231x87 capsule image; it looked fine in lists
    until stretched across the homepage hero. Steam's hidden
    `library_hero.jpg` asset (1920x622) was built exactly for this.

    Steam's high-resolution library hero banner (1920x622) replaces the
    small 231x87 search capsule to keep the homepage hero crisp on
    large displays.
    """
    if appid:
        return f"https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/{appid}/library_hero.jpg"
    return fallback


@pages_bp.route("/")
def home():
    try:
        cc = get_region_code()
        top_sellers_raw = fetch_browse_category("topsellers", cc=cc)
        specials_raw = fetch_browse_category("specials", cc=cc)
        new_releases_raw = fetch_browse_category("popularnew", cc=cc)

        featured_games = [
            {
                "id": g.get("id"),
                "name": g.get("name"),
                "header_image": hero_image_url(g.get("id"), g.get("image")),
                "analyze_url": f"/search?q={g.get('name', '')}",
                "short_description": "",
            }
            for g in top_sellers_raw[:5]
        ]

        # ---------------- TOP SELLERS ----------------
        # Left: real rank (#1, #2...) based on Steam's own ordering.
        # Right: real price.
        top_seller_games = [
            to_game_dict(g, {
                "footer_left": f"#{i + 1} Global",
                "footer_right": format_price(g.get("final_price")),
            })
            for i, g in enumerate(top_sellers_raw[:8])
        ]

        # ---------------- BIGGEST DEALS ----------------
        # Left: real discount percent. Right: was → now price.
        deal_games = []
        for g in specials_raw:
            discount = (g.get("discount_percent") or "").replace("%", "").replace("-", "")
            if not discount:
                continue
            was = g.get("original_price") or ""
            now = format_price(g.get("final_price"))
            deal_games.append(to_game_dict(g, {
                "footer_left": f"-{discount}%",
                "footer_right": f"{was} → {now}" if was else now,
            }))
        deal_games = deal_games[:8]

        # ---------------- FREE TO PLAY ----------------
        # Left: "Free". Right: real platform support (Windows/Mac/Linux),
        # since Steam's search results don't expose genre tags.
        free_games = []
        for g in top_sellers_raw + new_releases_raw:
            final_cents = g.get("final_price")
            if final_cents == "0" or final_cents == 0:
                free_games.append(to_game_dict(g, {
                    "footer_left": "Free",
                    "footer_right": platform_label(g.get("platforms", [])),
                }))
        seen_ids = set()
        deduped_free = []
        for g in free_games:
            if g["id"] not in seen_ids:
                seen_ids.add(g["id"])
                deduped_free.append(g)
        free_games = deduped_free[:8]

        # ---------------- NEW RELEASES ----------------
        # Replaces the old fake "Highest Rated" placeholder section.
        # Left: "New". Right: real price.
        new_release_games = [
            to_game_dict(g, {
                "footer_left": "New",
                "footer_right": format_price(g.get("final_price")),
            })
            for g in new_releases_raw[:8]
        ]

        return render_template(
            "index.html",
            featured_games=featured_games,
            top_seller_games=top_seller_games,
            deal_games=deal_games,
            free_games=free_games,
            new_release_games=new_release_games,
        )

    except requests.exceptions.RequestException:
        return render_template(
            "index.html",
            featured_games=[],
            top_seller_games=[],
            deal_games=[],
            free_games=[],
            new_release_games=[],
        )


@pages_bp.route("/discover")
def discover():
    return render_template("discover.html")


@pages_bp.route("/search")
def search_page():
    return render_template("search.html")
