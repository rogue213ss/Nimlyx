"""
POTATO CURATED SEED POOL -- guaranteed-included candidates for the
Potato ecosystem (🥔/🔧/💀), sourced from a user-researched name list.

WHAT THIS IS AND ISN'T
-----------------------
This module hardcodes GAME NAMES, never a tier, a badge, or an app id.

`CURATED_SEED_NAMES` below is a list the user personally researched --
titles they have real-world evidence run on genuinely low-end
hardware. The problem it solves: `services/hero/potato_pool.py`'s
budget-price scrape and the hero pool's top-sellers/new-releases scrape
are both real, unbiased Steam sweeps, but neither is guaranteed to
surface any SPECIFIC title on any given day (Steam's search ranking,
price changes, and a 100-per-band fetch cap all affect what comes
back). This module closes that gap by guaranteeing these specific
titles are always CONSIDERED -- it does not guarantee, or decide,
which tier any of them lands in.

Every name here is resolved against Steam's real, live search
(`fetch_search_by_term()`) at request time, enriched with the same
real `pc_requirements` appdetails fetch every other candidate pool
uses (`enrich_pool()`), and then run through the exact same unchanged
`classify_potato_tier()` model as everything else on the homepage and
/potato page. If a name doesn't resolve to a genuine Steam listing, or
its resolved requirements don't classify into any tier, it's silently
skipped here -- the same "never fabricate" contract every other pool
in this codebase follows. See the two flagged exceptions below for
known cases that will never resolve.

KNOWN GAPS (flagged, not silently swallowed)
----------------------------------------------
- "Diablo III" is not sold on Steam at all (Battle.net exclusive) --
  will never resolve to a Steam listing.
- "Minecraft Java" is not sold on Steam at all (Mojang launcher
  exclusive) -- will never resolve to a Steam listing.
Both are left in the list rather than silently dropped from it, so a
maintainer looking at this file sees exactly why they never appear,
instead of wondering if the resolver is broken.

WHERE THE TIER COMES FROM
---------------------------
Nowhere in this file. Resolution only produces a candidate; tier
assignment happens later, in the same
`services.hardware.homepage_classifier.classify_potato_tier_all()` /
`classify_homepage_hardware()` pipeline every other candidate goes
through, against whatever Steam's minimum/recommended spec for that
game says TODAY -- which will track reality even if Steam later
revises a game's listed requirements, unlike a hardcoded tier would.
"""

from services.hero.builder import enrich_pool
from services.hero.candidate import HeroCandidate
from steam import fetch_search_by_term

# ------------------------------------------------------------------
# 🥔 Potato Friendly -- user-researched candidates
# ------------------------------------------------------------------
_FRIENDLY_SEED_NAMES = [
    "Stardew Valley", "Terraria", "Undertale", "Portal 2",
    "Left 4 Dead 2", "Team Fortress 2", "Half-Life 2",
    "Counter-Strike: Source", "Counter-Strike 1.6", "Age of Empires II",
    "Civilization V", "Diablo III", "Starbound", "Fallout 3",
    "Fallout: New Vegas", "The Elder Scrolls IV: Oblivion", "BioShock",
    "BioShock 2", "Call of Duty 4: Modern Warfare",
    "Call of Duty: Modern Warfare 2", "Call of Duty: Black Ops",
    "Bully: Scholarship Edition", "Darksiders II",
    "Batman: Arkham City", "Max Payne 3", "Driver: San Francisco",
    "F1 2012", "DiRT 3", "Rage", "Dishonored", "Portal",
    "Don't Starve", "Limbo", "Hotline Miami", "Bastion",
    "Torchlight II", "Papers, Please", "The Binding of Isaac: Rebirth",
]

# ------------------------------------------------------------------
# 🔧 Potato + Tweaks -- user-researched candidates
# ------------------------------------------------------------------
_TWEAKS_SEED_NAMES = [
    "Far Cry 3", "Far Cry 4", "BioShock Infinite", "Tomb Raider",
    "Metal Gear Solid V: Ground Zeroes",
    "Metal Gear Solid V: The Phantom Pain", "Dark Souls: Remastered",
    "Dark Souls II", "Dark Souls III", "Resident Evil 5",
    "Resident Evil 6", "DmC: Devil May Cry", "Remember Me",
    "Euro Truck Simulator 2", "Payday 2", "Killing Floor 2",
    "Prototype", "Prototype 2", "The Sims 3", "The Sims 4",
    "FIFA 17", "FIFA 20", "Warframe", "Grand Theft Auto IV",
    "Grand Theft Auto V", "Battlefield 3", "Battlefield 4",
    "Call of Duty: Advanced Warfare", "Call of Duty: Black Ops III",
    "Crysis 2", "Dragon Age: Inquisition", "The Forest",
    "Project Zomboid", "Valheim", "7 Days to Die",
    "The Elder Scrolls V: Skyrim", "Minecraft Java", "Hitman: Absolution",
    "Sonic Generations", "Assetto Corsa", "Project CARS",
]

# ------------------------------------------------------------------
# 💀 Extreme Tweaks -- user-researched candidates
# ------------------------------------------------------------------
_EXTREME_SEED_NAMES = [
    "Dying Light", "Fallout 4", "The Elder Scrolls V: Skyrim Special Edition",
    "The Witcher 3: Wild Hunt", "Dark Souls III", "Dragon Age: Inquisition",
    "Metal Gear Solid V: The Phantom Pain", "The Forest", "7 Days to Die",
    "Valheim", "DayZ", "Resident Evil 2", "Grand Theft Auto V",
    "Battlefield 4", "Call of Duty: Black Ops III", "Crysis 2",
    "Crysis 3", "Far Cry 4", "Watch Dogs", "Watch Dogs 2",
    "Rise of the Tomb Raider", "Mad Max",
    "Middle-earth: Shadow of Mordor", "Batman: Arkham Knight",
    "Just Cause 2", "Just Cause 3",
]

# Deduped, order-preserved union -- resolution and classification are
# identical regardless of which of the user's three lists a name came
# from, since the REAL tier comes from live Steam data, not from
# which list the name happened to sit in (see module docstring for
# why: the user's own three lists disagreed with each other on a few
# titles, e.g. Far Cry 4 appeared in both Tweaks and Extreme).
CURATED_SEED_NAMES = list(dict.fromkeys(
    _FRIENDLY_SEED_NAMES + _TWEAKS_SEED_NAMES + _EXTREME_SEED_NAMES
))


def _resolve_seed_name(name, cc="US"):
    """Looks the name up against Steam's real search -- returns the
    first genuine app-row match (already filtered by
    _is_genuine_app_row inside fetch_search_by_term/_scrape_search_
    results, so bundles/packages/DLC are already excluded), or None if
    Steam's search returns nothing for it. A near-miss title match
    (Steam search is fuzzy) is accepted here the same way a person
    typing the name into Steam's own search box would accept the top
    result -- this module doesn't re-verify the name string against
    the result, since Steam's own relevance ranking already handles
    that better than a substring check would."""
    try:
        results = fetch_search_by_term(name, count=5, cc=cc)
    except Exception:
        return None
    return results[0] if results else None


def build_curated_seed_pool(cc="US"):
    """Resolves every name in CURATED_SEED_NAMES against live Steam
    search, dedupes by app id, and enriches the survivors with real
    pc_requirements via enrich_pool() -- the exact same enrichment
    step services/hero/potato_pool.py already uses, so this pool's
    HeroCandidate objects are indistinguishable in shape from any
    other candidate source by the time they reach the classifier.

    A name that fails to resolve (typo, not on Steam at all -- see
    the two flagged cases in this module's docstring, or a genuine
    Steam outage) is simply absent from the returned pool. Never
    raises for an individual failed name; only an exception fetching
    Steam search itself for a given name is caught, per-name, so one
    bad lookup can't take the rest of the list down with it.
    """
    pool_by_id = {}

    for name in CURATED_SEED_NAMES:
        game = _resolve_seed_name(name, cc=cc)
        if not game:
            continue

        app_id = game.get("id")
        resolved_name = (game.get("name") or "").strip()
        if not app_id or not resolved_name or resolved_name == "Unknown":
            continue

        if app_id not in pool_by_id:
            pool_by_id[app_id] = {**game, "sources": ["curated_seed"]}

    enriched = enrich_pool(list(pool_by_id.values()), cc=cc)

    return [
        HeroCandidate(
            game=game,
            category="potato_curated_seed",
            confidence=1.0,
            insight="",
            why_it_matters="",
        )
        for game in enriched
    ]
