"""
BADGES — single source of truth for how each Insight Provider
category presents itself visually. Nothing outside this file should
hardcode a badge label, CSS class, or icon for a category — Jinja
templates render whatever HeroCandidate.to_pick_dict() hands them,
and to_pick_dict() looks everything up from here.

Adding a 6th provider/category later means adding one entry here —
no template changes, no CSS `if` chains, no risk of a label drifting
out of sync between Python and Jinja.

CSS classes referenced here (badge-worth, badge-hidden, etc.) must
exist in static/css/style.css using the site's real --home-verdict-*
tokens.
"""

CATEGORY_BADGES = {
    "discount": {
        "label": "Worth Buying",
        "class": "badge-worth",
        "icon": "⭐",
    },
    "hidden_gem": {
        "label": "Hidden Value",
        "class": "badge-hidden",
        "icon": "💎",
    },
    "fresh_release": {
        "label": "Fresh Pick",
        "class": "badge-fresh",
        "icon": "🔥",
    },
    "critic_gap": {
        "label": "Critic Gap",
        "class": "badge-critic",
        "icon": "⚖️",
    },
    "mixed_contrarian": {
        "label": "Mixed Opinions",
        "class": "badge-split",
        "icon": "🌓",
    },
}

# Used if a category somehow has no badge defined (should never
# happen with the providers we ship, but to_pick_dict() should never
# raise a KeyError over a missing badge — a card with a generic
# fallback badge is better than a broken page).
FALLBACK_BADGE = {
    "label": "Nimlyx Pick",
    "class": "badge-fallback",
    "icon": "📌",
}


def get_badge(category):
    return CATEGORY_BADGES.get(category, FALLBACK_BADGE)
