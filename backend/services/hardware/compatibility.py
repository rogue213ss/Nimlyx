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
    """A user's PC.

    cpu_tier / gpu_tier / ram_gb (ORIGINAL fields, unchanged): the
    shape intended for the dormant SQL/HardwareDevice track
    (tier_score 0-100). That track remains untouched and unpopulated;
    these fields are preserved as-is in case it's revived later.

    cpu_external_id / gpu_external_id (ADDED -- additive only, nothing
    removed or repurposed): the shape the actual implemented engine
    below uses. The compatibility engine was built against the
    validated hardware ranking catalog
    (services.hardware.rankings_loader) rather than the empty SQL
    table -- see the compatibility-engine architectural inspection for
    why. These identify the user's selected hardware by the ranking
    catalog's own external_id (e.g. "nvidia-geforce-rtx-4090"),
    letting evaluate_compatibility() read the user's actual
    performance_score / compute_capability_score directly via
    rankings_loader, with no separate tier-resolution step.

    Every field is Optional because a real "Can I Run This?" form may
    reasonably let someone skip RAM entry, etc. -- the engine's job is
    to score whatever IS provided and mark the rest as "unknown"
    rather than silently assuming a value.
    """
    cpu_tier: Optional[int] = None
    gpu_tier: Optional[int] = None
    ram_gb: Optional[float] = None
    cpu_external_id: Optional[str] = None
    gpu_external_id: Optional[str] = None


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


def _evaluate_ram(minimum_text, recommended_text, user_ram_gb):
    """RAM comparison -- plain numeric, no vendor concerns. Returns a
    ComponentVerdict. Any side (requirement text or user_ram_gb) that
    can't be reliably parsed/wasn't provided yields None for the
    corresponding meets_* field rather than a guess."""
    from services.hardware.ram_parsing import parse_ram_gb

    min_gb = parse_ram_gb(minimum_text)
    rec_gb = parse_ram_gb(recommended_text)

    meets_minimum = None
    meets_recommended = None
    notes = []

    if user_ram_gb is None:
        notes.append("RAM: no user RAM amount provided -- cannot evaluate.")
    else:
        if min_gb is not None:
            meets_minimum = user_ram_gb >= min_gb
        else:
            notes.append("RAM: minimum requirement text could not be parsed into a GB value.")
        if rec_gb is not None:
            meets_recommended = user_ram_gb >= rec_gb
        else:
            notes.append("RAM: recommended requirement text could not be parsed into a GB value.")

    return ComponentVerdict(component="ram", meets_minimum=meets_minimum, meets_recommended=meets_recommended), notes


def _evaluate_alternatives_same_kind(alternatives, user_score):
    """Shared logic for CPU (no vendor gating) and for the
    same-vendor-judgeable subset of GPU alternatives: given a list of
    (alt, judgeable, score) tuples that are all directly comparable to
    user_score, and knowing whether every alternative in the original
    'or' list was judgeable, return True/False/None per the rule:

      - any judgeable alternative passes -> True (the "or" is satisfied)
      - no judgeable alternative exists -> None (nothing could be checked)
      - at least one judgeable alternative exists, none pass, but some
        alternatives were NOT judgeable (unresolved or, for GPU,
        cross-vendor) -> None (we only know some branches failed, not
        all of them -- see approved GPU rule: never report a definitive
        fail when part of the "or" was never actually checked)
      - every alternative was judgeable and none pass -> False
        (a genuinely definitive result: every possible branch was
        checked and all failed)
    """
    judgeable = [s for (judgeable_flag, s) in alternatives if judgeable_flag]
    all_judgeable = all(judgeable_flag for judgeable_flag, _ in alternatives) if alternatives else False

    if not alternatives:
        return None
    if any(user_score is not None and s is not None and user_score >= s for s in judgeable):
        return True
    if not judgeable:
        return None
    if all_judgeable:
        return False
    return None


def _evaluate_cpu(minimum_text, recommended_text, user_cpu_record):
    """CPU comparison -- performance_score is directly comparable
    regardless of manufacturer (no cross-vendor restriction applies to
    CPU per the approved ranking methodology; that restriction is
    GPU-specific, see module docstring / _evaluate_gpu below)."""
    from services.hardware.requirement_matching import resolve_cpu_requirement

    notes = []
    user_score = None
    if user_cpu_record is not None:
        user_score = user_cpu_record["ranking"]["performance_score"] if user_cpu_record["ranking"] else None
        if user_score is None:
            notes.append("CPU: user's selected CPU has no computable performance_score.")
    else:
        notes.append("CPU: no user CPU selected -- cannot evaluate.")

    def _judge(text, tier_label):
        alts = resolve_cpu_requirement(text)
        if not alts:
            if text:
                notes.append(f"CPU {tier_label}: requirement could not be resolved to a known CPU ('{text}').")
            return None
        unresolved = [a for a in alts if not a.resolved]
        if unresolved:
            notes.append(
                f"CPU {tier_label}: {len(unresolved)} alternative(s) could not be resolved "
                f"({', '.join(a.raw_text for a in unresolved)})."
            )
        pairs = [(a.resolved, a.score) for a in alts]
        return _evaluate_alternatives_same_kind(pairs, user_score)

    meets_minimum = _judge(minimum_text, "minimum") if user_score is not None else None
    meets_recommended = _judge(recommended_text, "recommended") if user_score is not None else None

    return ComponentVerdict(component="cpu", meets_minimum=meets_minimum, meets_recommended=meets_recommended), notes


def _evaluate_gpu(minimum_text, recommended_text, user_gpu_record):
    """GPU comparison -- enforces the approved vendor-aware rule:
    compute_capability_score is only compared between GPUs of the SAME
    vendor. A cross-vendor comparison is never scored; it's treated as
    not-judgeable, exactly like an unresolved requirement (see
    _evaluate_alternatives_same_kind's handling of "not every
    alternative was judgeable").

    This is NOT the same as an architecture multiplier or a conversion
    factor -- no correction is applied to make cross-vendor scores
    comparable; they are simply excluded from being compared at all,
    per the approved methodology."""
    from services.hardware.requirement_matching import resolve_gpu_requirement

    notes = []
    user_score = None
    user_vendor = None
    if user_gpu_record is not None:
        user_vendor = user_gpu_record["vendor"]
        user_score = user_gpu_record["ranking"]["compute_capability_score"] if user_gpu_record["ranking"] else None
        if user_score is None:
            notes.append("GPU: user's selected GPU has no computable compute_capability_score.")
    else:
        notes.append("GPU: no user GPU selected -- cannot evaluate.")

    cross_vendor_seen = [False]  # mutable flag for the closure below

    def _judge(text, tier_label):
        alts = resolve_gpu_requirement(text)
        if not alts:
            if text:
                notes.append(f"GPU {tier_label}: requirement could not be resolved to a known GPU ('{text}').")
            return None

        unresolved = [a for a in alts if not a.resolved]
        if unresolved:
            notes.append(
                f"GPU {tier_label}: {len(unresolved)} alternative(s) could not be resolved "
                f"({', '.join(a.raw_text for a in unresolved)})."
            )

        pairs = []
        for a in alts:
            if not a.resolved:
                pairs.append((False, None))
                continue
            same_vendor = user_vendor is not None and a.vendor == user_vendor
            if not same_vendor:
                cross_vendor_seen[0] = True
                pairs.append((False, None))  # not judgeable -- cross-vendor
                continue
            pairs.append((True, a.score))

        return _evaluate_alternatives_same_kind(pairs, user_score)

    meets_minimum = _judge(minimum_text, "minimum") if user_score is not None else None
    meets_recommended = _judge(recommended_text, "recommended") if user_score is not None else None

    if cross_vendor_seen[0]:
        notes.append(
            "GPU: this game's requirement lists a GPU from a different vendor than your "
            "selected GPU for at least one tier. Shader-unit counts (CUDA cores / stream "
            "processors / execution units) are not directly comparable across vendors, so "
            "that comparison could not be reliably evaluated and was treated as unknown "
            "rather than a pass or fail."
        )

    return ComponentVerdict(component="gpu", meets_minimum=meets_minimum, meets_recommended=meets_recommended), notes


def evaluate_compatibility(game_requirements, hardware_profile):
    """THE REAL IMPLEMENTATION.

    game_requirements: the normalized dict from
      services.game.requirements.parse_requirements() --
      {"minimum": {os,cpu,gpu,ram,storage}, "recommended": {...}}.
    hardware_profile: a HardwareProfile with cpu_external_id /
      gpu_external_id / ram_gb set (see HardwareProfile docstring for
      why this engine uses those fields rather than cpu_tier/gpu_tier).

    Returns a CompatibilityResult. Deterministic: identical inputs
    always produce identical output (no randomness, no population-
    relative lookups -- every score comes from the already-generated,
    already-validated ranking files via rankings_loader).

    Overall verdict rule (approved):
      NOT_RECOMMENDED - any RELIABLY DETERMINED component is below
        minimum (meets_minimum is False for at least one component;
        None does not count as a failure here).
      RUNS_WELL - every component that could be reliably evaluated
        meets recommended (meets_recommended is True for every
        component; a component still at None keeps the result out of
        this bucket, since "all reliably meet recommended" cannot be
        claimed when a component's recommended check is unknown).
      PLAYABLE - everything else that isn't NOT_RECOMMENDED (i.e. no
        confirmed minimum failure, but not every component confirmed
        at recommended either -- including cases where some components
        are simply unknown, per the approved "uncertainty is preserved
        in notes, not silently turned into a pass or fail" rule).
    """
    from services.hardware.rankings_loader import get_cpu_ranking_by_id, get_gpu_ranking_by_id

    minimum = (game_requirements or {}).get("minimum") or {}
    recommended = (game_requirements or {}).get("recommended") or {}

    user_cpu_record = (
        get_cpu_ranking_by_id(hardware_profile.cpu_external_id)
        if hardware_profile and hardware_profile.cpu_external_id else None
    )
    user_gpu_record = (
        get_gpu_ranking_by_id(hardware_profile.gpu_external_id)
        if hardware_profile and hardware_profile.gpu_external_id else None
    )
    user_ram_gb = hardware_profile.ram_gb if hardware_profile else None

    cpu_verdict, cpu_notes = _evaluate_cpu(minimum.get("cpu", ""), recommended.get("cpu", ""), user_cpu_record)
    gpu_verdict, gpu_notes = _evaluate_gpu(minimum.get("gpu", ""), recommended.get("gpu", ""), user_gpu_record)
    ram_verdict, ram_notes = _evaluate_ram(minimum.get("ram", ""), recommended.get("ram", ""), user_ram_gb)

    components = [cpu_verdict, gpu_verdict, ram_verdict]
    notes = cpu_notes + gpu_notes + ram_notes

    any_reliable_failure = any(c.meets_minimum is False for c in components)
    all_reliable_recommended = all(c.meets_recommended is True for c in components)

    if any_reliable_failure:
        verdict = VerdictLevel.NOT_RECOMMENDED
    elif all_reliable_recommended:
        verdict = VerdictLevel.RUNS_WELL
    else:
        verdict = VerdictLevel.PLAYABLE

    return CompatibilityResult(verdict=verdict, components=components, notes=notes)

def serialize_compatibility_result(result):
    """JSON-safe dict for a CompatibilityResult -- the ONLY new piece
    needed to expose evaluate_compatibility() over HTTP. Pure
    serialization, no new logic: None stays None (never coerced to
    false/0), the VerdictLevel enum becomes its plain string value,
    and every note is passed through unchanged and in full.

    Deliberately excludes internal-only detail (e.g. the raw
    ResolvedAlternative objects from requirement_matching.py never
    reach this boundary at all -- evaluate_compatibility() already
    reduces those down to the meets_minimum/meets_recommended
    booleans-or-None plus explanatory notes, which is exactly what
    gets serialized here)."""
    return {
        "verdict": result.verdict.value,
        "components": [
            {
                "component": c.component,
                "meets_minimum": c.meets_minimum,
                "meets_recommended": c.meets_recommended,
            }
            for c in result.components
        ],
        "notes": list(result.notes),
    }
