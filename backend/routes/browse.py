import requests

_session = requests.Session()
_session.headers.update({
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
})

from flask import Blueprint, jsonify, render_template
from region import get_region_code
from steam import fetch_browse_category
from services.analysis.score_cache import get_cached_score

browse_bp = Blueprint("browse", __name__)


@browse_bp.route("/api/browse/<category>")
def browse_games(category):
    allowed = ["topsellers", "specials", "popularnew"]

    if category not in allowed:
        return jsonify({"error": "Invalid category"}), 400

    try:
        return jsonify(fetch_browse_category(category))
    except requests.exceptions.RequestException as e:
        return jsonify({"error": str(e)}), 500


@browse_bp.route("/api/verdicts")
def verdicts():
    try:
        cc = get_region_code()
        top_sellers = fetch_browse_category("topsellers", cc=cc)
        specials = fetch_browse_category("specials", cc=cc)
        new_releases = fetch_browse_category("popularnew", cc=cc)

        def discount_num(g):
            d = g.get("discount_percent")
            return int(d.replace("%", "").replace("-", "")) if d else 0

        def price_num(g):
            fp = g.get("final_price")
            return int(fp) if fp and str(fp).isdigit() else 0

        worth_buying = [g for g in specials if discount_num(g) >= 40][:8]
        skip_for_now = [g for g in top_sellers if discount_num(g) == 0 and price_num(g) >= 3000][:8]
        hidden_value = [g for g in new_releases if price_num(g) == 0 or price_num(g) < 1000][:8]

        return jsonify({
            "worth_buying": worth_buying,
            "skip_for_now": skip_for_now,
            "hidden_value": hidden_value
        })

    except requests.exceptions.RequestException as e:
        return jsonify({"error": str(e)}), 500


@browse_bp.route("/api/featured")
def featured_games_api():
    cc = get_region_code()
    cache_key = ("featured_categories", cc)
    
    from steam import _cache_get, _cache_set
    cached = _cache_get(cache_key, ttl_seconds=180)
    if cached is not None:
        return jsonify(cached)

    url = f"https://store.steampowered.com/api/featuredcategories?l=english&cc={cc}"
    try:
        response = _session.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()
    except requests.exceptions.RequestException as e:
        return jsonify({"error": str(e)}), 500

    def clean_items(category):
        items = data.get(category, {}).get("items", [])
        cleaned = []
        hardware_keywords = ["steam deck", "steam controller", "steam machine", "steam link"]

        for item in items:
            name = item.get("name", "")
            if any(keyword in name.lower() for keyword in hardware_keywords):
                continue

            cleaned.append({
                "id": item.get("id"),
                "name": name,
                "image": item.get("header_image"),
                "final_price": item.get("final_price", 0),
                "original_price": item.get("original_price"),
                "discount_percent": item.get("discount_percent", 0)
            })
        return cleaned

    top_sellers = clean_items("top_sellers")

    hero = [
        {
            "appid": g["id"],
            "name": g["name"],
            "header_image": g["image"],
            "short_description": "",
            "price": g.get("final_price", 0)
        }
        for g in top_sellers[:5]
    ]

    result = {
        "hero": hero,
        "top_sellers": top_sellers,
        "new_releases": clean_items("new_releases"),
        "specials": clean_items("specials")
    }
    
    _cache_set(cache_key, result)
    return jsonify(result)


@browse_bp.route("/api/feed/row/<category>")
def feed_row(category):
    """
    Returns an HTML snippet for a specific homepage feed row.
    Uses serve-stale-while-revalidating cache logic to guarantee fast responses.
    """
    from flask import request
    from steam import fetch_homepage_row
    from formatters import format_price
    cc = get_region_code()
    
    seen_param = request.args.get("seen", "")
    seen_ids = set([s.strip() for s in seen_param.split(",") if s.strip()])
    
    # fetch_homepage_row uses background thread caching.
    games = fetch_homepage_row(category, cc=cc, seen_ids=seen_ids)
    
    if games is None:
        # True cold start. We could return a loading skeleton, but it's easier 
        # for AJAX to just retry or leave the skeleton that's already in the DOM.
        return "", 202 

    # to_discover_card() deliberately leaves `price` as the raw
    # unformatted cents value (it's a shared contract with Search,
    # whose own JS formats it client-side) -- but this route renders
    # server-side Jinja with no such formatting pass, so without this
    # every card here would show "1999" instead of "$19.99".
    #
    # IMPORTANT: `games` here is the same list/dicts held by
    # fetch_homepage_row's shared, cross-request cache (see
    # serve_stale_or_rebuild -- it returns cached["data"] by
    # reference, not a copy). Mutating g["price"] in place would
    # format it correctly once, then corrupt the cached raw value for
    # every subsequent request in this cache's TTL window (re-running
    # format_price on an already-formatted "$19.99" string isn't
    # all-digits, so it would silently fall back to "Free" for every
    # user). Building fresh dict copies for the template keeps the
    # cached originals untouched.
    games = [dict(g, price=format_price(g.get("price"))) for g in games]

    # Neither the specials nor action feed source makes a per-game
    # Steam review-stats call (see fetch_homepage_row's own "avoids
    # N+1 appdetails hits" comment) -- score comes from the same
    # non-blocking async cache Trending uses. get_cached_score()
    # never blocks this request; a cold cache means the fallback
    # state renders once, then fills in on a later request.
    games = [dict(g, nimlyx_score=get_cached_score(g.get("app_id"), cc)) for g in games]

    # For Phase 1 prototype, we map the visual treatments.
    title = ""
    variant = "feed-variant-standard"
    
    if category == "specials":
        title = "Biggest Deals"
        variant = "feed-variant-deal"
    elif category == "action":
        title = "Action"
        variant = "feed-variant-standard"
    else:
        title = category.title()

    html = render_template(
        "components/feed_row.html",
        title=title,
        games=games,
        variant=variant,
        category=category
    )
    return html
