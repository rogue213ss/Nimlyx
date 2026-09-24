"""
SEO — robots.txt + XML sitemap.

SITE_URL is the one thing this module needs from the outside world
(the canonical public origin, no trailing slash) — read from the
SITE_URL env var, falling back to the production domain. Every
absolute URL emitted here (sitemap <loc>, robots Sitemap: line) is
built from this single constant so there's one place to fix if the
domain ever changes.

Sitemap contents, deliberately NOT "every URL that exists":
  - Static top-level pages (home, discover, search, potato, about,
    privacy, terms) — every one of these is a real, useful,
    server-reachable page.
  - Individual game pages (/search?app_id=<id>) for the verified
    Potato database (data/potato/verified_potato_games.json) — the
    one place in this codebase with a STABLE, persisted list of
    Steam app_ids. Nimlyx has no games database (see
    services/hardware/db.py's own docstring: "Nimlyx has no database
    today"); everything else (hero picks, trending, new releases) is
    live-fetched from Steam per-request/per-region and rotates
    hour-to-hour, which makes it exactly the kind of ephemeral,
    parameter-driven content a sitemap should NOT enumerate. The 219
    verified Potato games are the opposite: curated once, stable,
    genuinely indexable, real content.
  - /discover and /search (the bare, no-query pages) are included as
    entry points, not as a stand-in for every possible filter/app_id
    combination.

Query-parameter game pages are intentionally the sitemap's only
"deep" URLs (in lieu of clean per-game paths, which the app doesn't
route today) — see the search.py route change that made each one
carry its own <title>/description/canonical instead of the single
generic "Nimlyx | Game Details" that used to render for all of them.
"""
import json
import os
from pathlib import Path

from flask import Blueprint, Response, url_for

seo_bp = Blueprint("seo", __name__)

SITE_URL = os.environ.get("SITE_URL", "https://nimlyx.com").rstrip("/")

_POTATO_JSON_PATH = Path(__file__).resolve().parent.parent / "data" / "potato" / "verified_potato_games.json"

_STATIC_ROUTES = [
    # (endpoint, changefreq, priority)
    # Privacy/Terms are deliberately excluded here -- both carry
    # <meta name="robots" content="noindex, follow"> (see
    # templates/privacy.html, terms.html), so listing them in the
    # sitemap would tell Google "please index" out of one mouth and
    # "please don't" out of the other. A sitemap entry is a request
    # to index; it has no business contradicting an explicit noindex.
    ("pages.home", "daily", "1.0"),
    ("pages.discover", "weekly", "0.8"),
    ("pages.search_page", "weekly", "0.7"),
    ("potato.potato_page", "daily", "0.9"),
    ("pages.about_page", "monthly", "0.5"),
]


def _verified_potato_app_ids():
    """Stable (app_id, name) pairs from the verified Potato database.
    Returns [] on any read/parse problem rather than raising --  a
    sitemap generator must never 500 the route just because one data
    file is momentarily malformed mid-deploy."""
    try:
        with open(_POTATO_JSON_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return []

    out = []
    seen = set()
    for entry in data:
        app_id = entry.get("steam_app_id")
        if not app_id or app_id in seen:
            continue
        seen.add(app_id)
        out.append(app_id)
    return out


@seo_bp.route("/robots.txt")
def robots_txt():
    lines = [
        "User-agent: *",
        "Allow: /",
        # API endpoints are data plumbing for the frontend JS, not
        # content of their own -- indexing them would just hand
        # crawlers a pile of raw JSON with no canonical human-facing
        # page behind it.
        "Disallow: /api/",
        "",
        f"Sitemap: {SITE_URL}/sitemap.xml",
        "",
    ]
    return Response("\n".join(lines), mimetype="text/plain")


@seo_bp.route("/sitemap.xml")
def sitemap_xml():
    urls = []

    for endpoint, changefreq, priority in _STATIC_ROUTES:
        loc = f"{SITE_URL}{url_for(endpoint)}"
        urls.append((loc, changefreq, priority))

    for app_id in _verified_potato_app_ids():
        loc = f"{SITE_URL}{url_for('pages.search_page')}?app_id={app_id}"
        urls.append((loc, "monthly", "0.6"))

    body = ['<?xml version="1.0" encoding="UTF-8"?>']
    body.append('<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">')
    for loc, changefreq, priority in urls:
        body.append(
            "  <url>"
            f"<loc>{loc}</loc>"
            f"<changefreq>{changefreq}</changefreq>"
            f"<priority>{priority}</priority>"
            "</url>"
        )
    body.append("</urlset>")

    return Response("\n".join(body), mimetype="application/xml")
