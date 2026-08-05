"""Compatibility engine -- data contracts only (Sprint 5 foundation).

This module defines the SHAPES a real compatibility engine (Sprint 6)
will consume and return. It contains no scoring logic, no hardware
lookups, and no route wiring. `evaluate_compatibility()` below is a
stub that documents the intended contract and deliberately raises
NotImplementedError -- so if anything ever calls it before Sprint 6
builds the real implementation, that's an immediate, obvious failure
instead of a fabricated verdict.

The two inputs this engine will eventually combine:

  1. Game-side data -- ALREADY DONE. See
     services/game/requirements.py's parse_requirements(), already
     live in build_game_detail()'s `requirements` field:
         {"minimum": {os,cpu,gpu,ram,storage}, "recommended": {...}}
     Each cpu/gpu value is Steam's own free-text string (e.g.
     "Intel i5-2500K") -- Sprint 6 will need to match this text
     against HardwareDevice.aliases (models.py) to resolve a tier.

  2. User-side data -- NOT YET BUILT. HardwareProfile below is the
     placeholder shape for what a future "enter your PC" form will
     collect. No input UI, no persistence, nothing collecting this
     yet -- Sprint 6+/Phase 2 UI work.

Verdict shape (ComponentVerdict / CompatibilityResult) mirrors the
three-state output already specified in the roadmap:
    🟢 Runs Well / 🟡 Playable / 🔴 Not Recommended
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class VerdictLevel(str, Enum):
    """The three roadmap-specified outcomes. String-backed so this
    serializes cleanly to JSON later without a separate mapping."""
    RUNS_WELL = "runs_well"           # 🟢 all components meet/exceed recommended
    PLAYABLE = "playable"             # 🟡 meets minimum, below recommended somewhere
    NOT_RECOMMENDED = "not_recommended"  # 🔴 below minimum on at least one component


@dataclass
class HardwareProfile:
    """A user's PC, once Sprint 6+ collects it. Tier scores are
    resolved (via HardwareDevice lookups) BEFORE this is constructed
    -- this dataclass holds resolved tiers, not raw strings, so the
    engine itself never has to know about alias-matching.

    Every field is Optional because a real "Can I Run This?" form
    may reasonably let someone skip RAM entry, etc. -- the engine's
    future job is to score whatever IS provided and mark the rest
    as "unknown" rather than silently assuming a value.
    """
    cpu_tier: Optional[int] = None
    gpu_tier: Optional[int] = None
    ram_gb: Optional[int] = None


@dataclass
class ComponentVerdict:
    """One component's (cpu/gpu/ram) individual result -- the
    "CPU: Good / GPU: Good / RAM: Good" breakdown rows the roadmap's
    example output shows. `meets_recommended` and `meets_minimum` are
    kept as two separate booleans (not derived from one score) so the
    engine can be explicit about a component that's below minimum
    entirely, vs. one that clears minimum but not recommended --
    two genuinely different situations the roadmap's tiered verdict
    output depends on being able to tell apart.
    """
    component: str  # "cpu" | "gpu" | "ram"
    meets_minimum: Optional[bool] = None      # None = insufficient data to judge
    meets_recommended: Optional[bool] = None  # None = insufficient data to judge


@dataclass
class CompatibilityResult:
    """The full verdict for one (game, hardware_profile) pair."""
    verdict: VerdictLevel
    components: list = field(default_factory=list)  # list[ComponentVerdict]
    # Free-text notes for edge cases the roadmap's simple 3-state
    # verdict can't fully capture on its own (e.g. "GPU tier could not
    # be determined from this game's listed requirements") -- kept as
    # a list so the engine can report more than one caveat without
    # cramming them into a single string.
    notes: list = field(default_factory=list)


def evaluate_compatibility(game_requirements, hardware_profile):
    """THE FUTURE ENTRY POINT -- not implemented yet.

    Intended signature once built:
      game_requirements: the normalized dict from
        services.game.requirements.parse_requirements() (already
        produced today by build_game_detail()).
      hardware_profile: a HardwareProfile (above), already resolved
        against services.hardware.models.HardwareDevice.

      Returns: a CompatibilityResult.

    Deliberately raises rather than returning a placeholder verdict --
    a fabricated "Playable" for hardware nobody actually checked would
    violate the same no-fabricated-data principle every other part of
    this app follows. Sprint 6 replaces this body with the real
    comparison logic (game requirement tier vs. hardware_profile tier,
    per component, per the VerdictLevel rules documented above)."""
    raise NotImplementedError(
        "Compatibility scoring is Sprint 6 scope. "
        "This function is a structural placeholder only -- see module docstring."
    )