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


def to_homepage_card(candidate, hardware_badge, orientation="landscape"):
    """to_pick_dict() already builds the {app_id, name, image,
    image_candidates, price, url, ...} shape from the candidate's raw
    appdetails -- reused here rather than re-deriving image/URL logic.
    Just renamed to the field names index.html's homepage cards use
    everywhere else (header_image/analyze_url), matching
    format_basic_game()'s output shape. image_candidates is rebuilt
    with the requested orientation (to_pick_dict() always builds
    landscape) since Potato Friendly renders as a portrait card.

    Public (not `_to_homepage_card`) since this is now called from
    both this module and services/hardware/verified_potato_pool.py's
    consumers (routes/pages.py, routes/potato.py) -- it's pure display
    formatting with no opinion on WHERE a candidate's tier came from,
    so there's no reason to keep it module-private."""
    base = candidate.to_pick_dict()
    card = {
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
    # Only present for verified-database candidates (see
    # services/hardware/verified_potato_pool.py) -- the dynamic
    # classifier's candidates never set this, so it's simply absent
    # (never a fabricated/empty placeholder) for iGPU cards and any
    # future research-mode use of this same card builder.
    verified_evidence = candidate.game.get("verified_evidence")
    if verified_evidence:
        card["evidence"] = verified_evidence
    return card


# Old name kept as an alias -- this module's own two functions below
# still use it internally, and it avoids a churny rename of every call
# site in this file for no behavioral reason.
_to_homepage_card = to_homepage_card


def classify_igpu_only(candidates, seen_ids, limit=14):
    """Just the Integrated GPU section of what classify_homepage_hardware()
    used to compute in one combined pass. Split out because the Potato
    ecosystem (Friendly/Tweaks/Extreme) no longer sources from this
    dynamic classifier at all -- see
    services/hardware/verified_potato_pool.py and
    services/hardware/verified_potato_db.py, now the homepage's
    authoritative source for those three tiers. Computing and then
    discarding 3/4 of classify_homepage_hardware()'s return value on
    every homepage request would be wasteful and confusing to read;
    this is the honest subset that's actually still used live.

    classify_homepage_hardware() and classify_potato_tier_all() below
    are UNCHANGED and still fully correct -- they're kept for their
    now-secondary role (research / validating candidate games before
    they're added to the verified database), not deleted, per
    explicit instruction not to remove code that's still useful for
    that purpose. Nothing on the live homepage or /potato page calls
    them for Potato tiers any more.
    """
    igpu_games = []
    igpu_used_ids = set()

    for candidate in candidates:
        if len(igpu_games) >= limit:
            break

        app_id = str(candidate.app_id) if candidate.app_id else None
        if not app_id or app_id in seen_ids or app_id in igpu_used_ids:
            continue

        pc_requirements = candidate.game.get("pc_requirements")
        if not pc_requirements:
            continue

        try:
            reqs = parse_requirements(pc_requirements)
        except Exception:
            continue

        if not any(reqs.get("minimum", {}).values()):
            continue

        if _passes(reqs, INTEGRATED_GPU_PROFILE):
            card = to_homepage_card(candidate, "Meets iGPU Minimum", orientation="landscape")
            igpu_games.append(card)
            igpu_used_ids.add(app_id)

    return igpu_games


def classify_homepage_hardware(candidates, seen_ids, limit=14):
    """RESEARCH / CANDIDATE-VALIDATION USE ONLY as of the verified-
    database migration -- the live homepage no longer calls this for
    its Potato Friendly/Tweaks/Extreme rows (see
    services/hardware/verified_potato_pool.py). Kept fully working and
    unmodified so it can still validate a candidate game's dynamic
    classification before it's added to
    data/potato/verified_potato_games.json, and so classify_igpu_only()
    above (the live iGPU section) can be checked against it.

    Given the hero pool's HeroCandidate objects (the same
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


_POTATO_TIER_BADGES = {
    "friendly": "Meets Low-End Minimum",
    "tweaks": "Playable With Tweaks",
    "extreme": "Extreme Settings Only",
}
_POTATO_TIER_ORIENTATIONS = {
    "friendly": "portrait",
    "tweaks": "landscape",
    "extreme": "landscape",
}


def classify_potato_tier_all(candidates, tier):
    """RESEARCH / CANDIDATE-VALIDATION USE ONLY as of the verified-
    database migration -- routes/potato.py's "view more" page no
    longer calls this (it pages through
    services.hardware.verified_potato_pool.get_verified_potato_tiers()
    instead). Kept unmodified as a way to dynamically re-check a
    candidate game's classification -- e.g. before adding it to
    data/potato/verified_potato_games.json, or to see how the
    ratio-based model alone would have classified something already in
    the verified database.

    The /potato "view more" page's variant of this module's Potato
    classification. Same parse -> classify_potato_tier() pipeline as
    classify_homepage_hardware() above (same "never fabricate a tier"
    behavior -- a game whose requirements don't resolve is left out,
    never defaulted in), but deliberately different in two ways that
    only make sense for a standalone, dedicated tier page rather than
    a homepage row:

      - No `limit` and no homepage `seen_ids` exclusion. The homepage
        rows cap at 14 and skip anything already shown elsewhere on
        the page; this returns EVERY matching game in `candidates` for
        the one requested tier, so the /api/potato/<tier> route can
        paginate over the full match list itself.
      - Only computes the ONE requested tier, not all three tiers plus
        the unrelated Integrated GPU section -- there's no reason to
        pay for that extra work on a page that only ever renders one
        tier's list at a time.

    `tier` must be one of "friendly" / "tweaks" / "extreme" -- raises
    ValueError otherwise, same fail-loud contract the API route relies
    on to turn a bad tier into a 400 rather than silently returning an
    empty list.

    Still dedupes by app_id within its own output, matching the same
    hero-pool + potato-pool merge routes/pages.py already does before
    calling classify_homepage_hardware() -- a game appearing in both
    source pools should only ever produce one card here too.
    """
    if tier not in _POTATO_TIER_BADGES:
        raise ValueError(f"Unknown potato tier: {tier!r}")

    from services.hardware.potato_classifier import classify_potato_tier

    badge = _POTATO_TIER_BADGES[tier]
    orientation = _POTATO_TIER_ORIENTATIONS[tier]

    games = []
    seen_ids = set()
    for candidate in candidates:
        app_id = str(candidate.app_id) if candidate.app_id else None
        if not app_id or app_id in seen_ids:
            continue

        pc_requirements = candidate.game.get("pc_requirements")
        if not pc_requirements:
            continue

        try:
            reqs = parse_requirements(pc_requirements)
        except Exception:
            continue

        if not any(reqs.get("minimum", {}).values()):
            continue

        try:
            candidate_tier = classify_potato_tier(reqs)
        except Exception:
            candidate_tier = None

        if candidate_tier != tier:
            continue

        games.append(_to_homepage_card(candidate, badge, orientation=orientation))
        seen_ids.add(app_id)

    return games
