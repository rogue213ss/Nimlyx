"""Real classification for the homepage's hardware sections.

Investigation finding (see routes/pages.py history): the homepage's
Integrated GPU / Potato Friendly sections were shipped in V1 with a
static badge string ("Analysis Pending" / "Pending Check") because
nothing on the homepage path called the compatibility engine. The
engine itself (services.hardware.compatibility.evaluate_compatibility)
was already fully implemented and already live on the Game Detail
"Can I Run This?" feature -- it just wasn't reused here.

This module closes that gap WITHOUT adding any new Steam calls. The
hero engine (services.hero.builder.enrich_pool) already fetches full
raw appdetails -- pc_requirements included -- for a ~30-75 game pool
on a background thread, refreshed every 15 minutes, cached in
routes/pages.py's _HERO_CACHE. That's the same shape of data
Game Detail parses; this module just runs it through
parse_requirements() + evaluate_compatibility() using two fixed,
real hardware profiles pulled from the ranking catalog.

No fabrication: a game whose requirements text doesn't resolve
cleanly is simply left out of the section. It never gets a fallback
"probably fine" classification.
"""

from services.game.requirements import parse_requirements
from services.hardware.compatibility import evaluate_compatibility, HardwareProfile
from steam_images import build_image_candidates

# Representative iGPU rig: a very common ultrabook pairing (Intel
# i5-8350U ships with UHD 630 by default). Chosen deliberately on the
# older/weaker side of "still commonly owned integrated graphics" so a
# pass here is a meaningful, conservative signal -- not cherry-picking
# a strong modern iGPU to inflate the section.
INTEGRATED_GPU_PROFILE = HardwareProfile(
    cpu_external_id="cpu-intelcorei58350u",
    gpu_external_id="intel-uhd-graphics-630",
    ram_gb=8,
)

# Representative "potato" rig: 8GB RAM (explicit spec) paired with a
# genuinely old, weak integrated GPU (Intel HD Graphics 4400, 2013 --
# a full generation+ below the UHD 630 used for the Integrated GPU
# profile above) and a budget-era CPU. Deliberately the weaker of the
# two profiles in this file: a game passing Potato should mean "runs
# on genuinely old/low hardware," not just "no dedicated GPU needed."
POTATO_PROFILE = HardwareProfile(
    cpu_external_id="cpu-intelcorei34130",
    gpu_external_id="intel-hd-graphics-4400",
    ram_gb=8,
)


def _passes(game_requirements, profile):
    """True only if every component that could actually be resolved
    meets minimum. A component the engine couldn't resolve (unknown
    CPU/GPU string, missing requirements) does NOT count as a pass --
    it's simply not evidence either way, so a game with no resolvable
    signal at all is correctly excluded rather than defaulted in."""
    result = evaluate_compatibility(game_requirements, profile)
    resolved_any = False
    for component in result.components:
        if component.meets_minimum is None:
            continue
        resolved_any = True
        if component.meets_minimum is False:
            return False
    return resolved_any


# NOTE: `_passes()` above is still used for the Integrated GPU section
# (INTEGRATED_GPU_PROFILE) -- that section's semantics are unchanged
# and out of this task's scope. It is deliberately NOT used for the
# Potato ecosystem (Friendly/Tweaks/Extreme) any more; see
# potato_classifier.classify_potato_tier()'s module docstring for why
# a strict, same-vendor-only check can't carry the Friendly tier on
# its own once tested against real Nvidia/AMD-minimum-spec games.


def _to_homepage_card(candidate, hardware_badge, orientation="landscape"):
    """to_pick_dict() already builds the {app_id, name, image,
    image_candidates, price, url, ...} shape from the candidate's raw
    appdetails -- reused here rather than re-deriving image/URL logic.
    Just renamed to the field names index.html's homepage cards use
    everywhere else (header_image/analyze_url), matching
    format_basic_game()'s output shape. image_candidates is rebuilt
    with the requested orientation (to_pick_dict() always builds
    landscape) since Potato Friendly renders as a portrait card."""
    base = candidate.to_pick_dict()
    return {
        "id": base["app_id"],
        "name": base["name"],
        "header_image": base["image"],
        "image_candidates": build_image_candidates(
            base["app_id"], orientation=orientation, fallback_image=candidate.game.get("scraped_image")
        ),
        "analyze_url": base["url"],
        "price": base["price"],
        "hardware_badge": hardware_badge,
    }


def classify_homepage_hardware(candidates, seen_ids, limit=14):
    """Given the hero pool's HeroCandidate objects (the same
    `all_candidates` already sitting in _HERO_CACHE[cc]["all_candidates"]
    -- no new Steam calls), return
    (igpu_games, potato_friendly, potato_tweaks, potato_extreme):
    homepage-ready game dicts for games whose parsed requirements
    actually clear the respective profile/tier.

    `seen_ids` is the running set of app_ids already used elsewhere on
    the homepage (hero, picks, trending, ...) -- passed in rather than
    imported so this module has no coupling to routes/pages.py's
    request-scoped state.

    Every list is capped at `limit` and preserves the candidate pool's
    original order (already popularity/relevance sorted upstream).
    Games with no pc_requirements, requirement text that doesn't
    resolve against the catalog, or that are already used elsewhere
    on the page, are silently skipped -- never force-included with a
    placeholder badge.

    Tier assignment for the Potato ecosystem (Friendly/Tweaks/Extreme)
    is mutually exclusive and comes from ONE model,
    `services.hardware.potato_classifier.classify_potato_tier()` --
    see that module's docstring for the real-world research behind
    the thresholds, and for why Friendly is decided by that same
    model rather than by a separately-sourced strict check (the
    Integrated GPU section's `_passes()` above is unrelated and
    unchanged). A game with no resolvable GPU signal at all is
    excluded from every Potato tier rather than guessed into one.
    """
    from services.hardware.potato_classifier import classify_potato_tier

    igpu_games = []
    potato_friendly = []
    potato_tweaks = []
    potato_extreme = []
    igpu_used_ids = set()
    potato_used_ids = set()

    for candidate in candidates:
        if (
            len(igpu_games) >= limit
            and len(potato_friendly) >= limit
            and len(potato_tweaks) >= limit
            and len(potato_extreme) >= limit
        ):
            break

        app_id = str(candidate.app_id) if candidate.app_id else None
        if not app_id or app_id in seen_ids:
            continue

        pc_requirements = candidate.game.get("pc_requirements")
        if not pc_requirements:
            continue

        try:
            reqs = parse_requirements(pc_requirements)
        except Exception:
            # Malformed/unexpected requirements HTML for this one game
            # -- skip it, don't let it take the whole section down.
            continue

        if not any(reqs.get("minimum", {}).values()):
            continue

        wants_igpu = len(igpu_games) < limit and app_id not in igpu_used_ids
        if wants_igpu and _passes(reqs, INTEGRATED_GPU_PROFILE):
            card = _to_homepage_card(candidate, "Meets iGPU Minimum", orientation="landscape")
            igpu_games.append(card)
            igpu_used_ids.add(app_id)

        if app_id in potato_used_ids:
            continue

        # Potato Friendly / Tweaks / Extreme all now come from ONE
        # model -- see services/hardware/potato_classifier.py's module
        # docstring for why splitting Friendly off into a separately-
        # sourced strict check (the original design) doesn't hold up
        # once tested against real Nvidia/AMD/Intel minimum specs.
        try:
            tier = classify_potato_tier(reqs)
        except Exception:
            tier = None

        if tier == "friendly" and len(potato_friendly) < limit:
            card = _to_homepage_card(candidate, "Meets Low-End Minimum", orientation="portrait")
            potato_friendly.append(card)
            potato_used_ids.add(app_id)
        elif tier == "tweaks" and len(potato_tweaks) < limit:
            card = _to_homepage_card(candidate, "Playable With Tweaks", orientation="landscape")
            potato_tweaks.append(card)
            potato_used_ids.add(app_id)
        elif tier == "extreme" and len(potato_extreme) < limit:
            card = _to_homepage_card(candidate, "Extreme Settings Only", orientation="landscape")
            potato_extreme.append(card)
            potato_used_ids.add(app_id)

    return igpu_games, potato_friendly, potato_tweaks, potato_extreme
