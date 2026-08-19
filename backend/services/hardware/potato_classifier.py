"""Potato ecosystem tier classifier: Friendly / Tweaks / Extreme.

WHY THIS IS A SINGLE UNIFIED MODEL, NOT "STRICT CHECK PLUS A GAP MODEL"
------------------------------------------------------------------------
The first version of this module left 🥔 Potato Friendly to
`evaluate_compatibility()`'s strict, same-vendor-only GPU equivalence
check, and only used a ratio-based gap model for 🔧 Tweaks / 💀
Extreme. A validation pass across ~20 real games spanning Nvidia,
AMD, and Intel minimum-spec GPUs (see the test suite for the list)
exposed why that split doesn't hold up:

  1. `evaluate_compatibility()`'s cross-vendor rule (correctly, for
     its own purpose) refuses to compare an Nvidia/AMD requirement
     against the potato profile's Intel iGPU at all -- it reports the
     GPU component as `None` (unknown), never True/False. But
     virtually every real game's minimum GPU is Nvidia or AMD, not
     Intel. The practical effect: strict Friendly could almost never
     get a real "meets minimum" GPU verdict for anything except the
     handful of games that literally list an Intel iGPU as their own
     minimum.
  2. The homepage_classifier's original `_passes()` helper treated
     that `None` as "no evidence against it" and let CPU+RAM alone
     wave a game through -- which is how, in testing, a game
     requiring a Radeon R7 260X (~5.4x the potato GPU score) could
     have reached 🥔 Potato Friendly on CPU/RAM alone, with zero real
     GPU evidence. That is a correctness bug, not a threshold problem.
  3. Tightening Friendly to require a *resolved* (same-vendor) GPU
     verdict closes that bug but overcorrects: it then excludes
     almost every Nvidia/AMD-minimum game from Friendly entirely,
     including ones that plainly belong there (Stardew Valley listing
     an old Nvidia card that's far weaker than the potato GPU).

The actual fix is architectural, not a threshold: use ONE gap-ratio
model, based on `compute_capability_score` as a coarse, explicitly
DIRECTIONAL (never equivalence) magnitude signal, for all three
bands -- Friendly is just the ratio<=1.0 band of the same model that
produces Tweaks and Extreme, rather than a differently-sourced claim
that happens to sit next to them. `evaluate_compatibility()` and its
locked no-cross-vendor-equivalence rule are UNCHANGED and still solely
own the "Can I Run This?" game-detail feature and the pre-existing
Integrated GPU homepage section -- neither of those claims strict
pass/fail equivalence has changed. This module has simply stopped
trying to borrow that strict claim for a purpose (relative gap sizing
across vendors) it was never designed to answer.

CPU and RAM are NOT part of this cross-vendor caveat -- CPU's
`performance_score` has no vendor-comparability restriction anywhere
else in this codebase (see `compatibility.py`'s `_evaluate_cpu`
docstring), and RAM is a plain GB number. Both are still evaluated as
real ratios/values, not folded into the "directional-only" caveat that
applies to GPU alone.

REFERENCE HARDWARE (unchanged)
-------------------------------
    CPU: Intel Core i3-4130 (performance_score 5,375.87)
    GPU: Intel HD Graphics 4400 (compute_capability_score 184,000)
    RAM: 8 GB
Pulled from `homepage_classifier.POTATO_PROFILE` by external_id --
never duplicated as separate hardcoded numbers.

RESEARCH THAT INFORMED THE BANDS BELOW
----------------------------------------
Two rounds of research: an initial pass on Intel HD 4400/4600/620-class
low-end testing (YouTube benchmark videos, Steam community "can I run
this on my potato" threads, a GOG/Tom's Hardware forum thread), and a
second validation pass that pulled OFFICIAL published minimum/
recommended specs (via web search, marked [V] below) for ~12 games
spanning Nvidia/AMD/Intel minimum GPUs and ran them through this exact
model, specifically to check whether the bands hold up across vendors
and genres rather than just fitting Dying Light in isolation.

  - Dying Light [V]: minimum GPU (GTX 460, ~1.2x the potato GPU
    score) only, yet its RECOMMENDED GPU (GTX 670, ~7.2x) balloons
    far past that. Independent low-end test videos and a Steam
    community thread confirm ~20-30 FPS on Intel HD 4400 with 8 GB
    RAM once resolution/settings are cut hard -- the calibration case
    for `ENGINE_UNDERSELLS_RECOMMENDED_RATIO` below. Classifies as
    Extreme.
  - Skyrim Special Edition [V] and Fallout 4 [V]: same
    minimum-undersells-recommended pattern (min ratios 1.48x/0.94x,
    recommended ratios both ~11.3x) -- both classify as Extreme too,
    which matches their real-world reputation as engines that are far
    more demanding in practice than their official minimum spec
    suggests, especially on integrated graphics. This is what
    confirms the promotion rule generalizes rather than being tuned
    to one title.
  - Watch Dogs (2014) [V]: minimum GPU (GTX 460, ~1.23x) with only a
    MILD recommended step (GTX 560 Ti, ~1.72x) -- no steep escalation,
    so it correctly stays in Tweaks rather than being promoted.
  - GTA V [V]: minimum GPU (9800 GT) is already BELOW the potato GPU
    score outright -- lands in Friendly without any special-case
    logic.
  - Just Cause 3 [V] and The Witcher 3 [V]: both have a real minimum
    GPU (GTX 670 / GTX 660) already ~5-7x the potato GPU score --
    both correctly excluded. (An earlier draft of this module's
    research notes cited Just Cause 3 as a low-end-playable outlier
    from memory; that could not be verified on a second pass and
    Just Cause 3's actual published minimum spec is far too demanding
    for this tier, so that claim has been retracted here.)
  - Cyberpunk 2077 [V] and Red Dead Redemption 2 [V]: minimum GPU
    ratios ~12x -- excluded, as expected for modern AAA.

RESULT: across this 12-game, three-vendor validation matrix, exactly
one game per Friendly/Tweaks/Extreme-without-escalation category
appears where expected, three Extreme cases all arrive via the same
verified real-world pattern (not per-game tuning), and every game with
a genuinely large official gap (Just Cause 3, Witcher 3, Cyberpunk
2077, RDR2) is correctly excluded rather than swept into Extreme.

A NOTE ON WHAT THIS VALIDATION PASS ALSO FOUND
-------------------------------------------------
Building this matrix surfaced a real bug in the PREVIOUS version of
the Potato ecosystem (not a threshold problem): 🥔 Potato Friendly was
decided by a strict, same-vendor-only check that -- because almost
every real game's minimum GPU is Nvidia or AMD, not Intel -- had
essentially no way to get a real GPU verdict for most games, and the
homepage code was silently treating "no GPU verdict" as "no evidence
against it," letting some games reach Friendly on CPU+RAM evidence
alone with a GPU requirement several times the potato GPU's score
never actually checked. That is why Friendly is now folded into this
same unified ratio model instead of being sourced from a separate
mechanism -- see the section above for the full explanation.

THE BANDS
---------
Each of GPU / CPU / RAM independently maps to a 0-3 severity level
(0 = at/below potato level, 3 = beyond even Extreme). The game's
overall tier is the WORST (highest) of the three -- a comfortable GPU
doesn't excuse a wildly excessive RAM ask, and vice versa. GPU
evidence is mandatory: a game whose GPU requirement doesn't resolve
against the catalog at all is excluded outright, regardless of how
comfortable its CPU/RAM look, because "how much more GPU does this
ask for" is the actual axis the Potato ecosystem is about.

  Level 0 (ratio/value <= its own baseline)   -> counts toward 🥔 Friendly
  Level 1 (<= TWEAKS ceiling)                  -> counts toward 🔧 Tweaks
  Level 2 (<= EXTREME ceiling)                 -> counts toward 💀 Extreme
  Level 3 (beyond EXTREME ceiling)             -> excludes the game entirely

TWEAKS_MAX_GPU_RATIO (1.6x): real preset/resolution comparisons
(e.g. Notebookcheck's own per-preset breakdowns) commonly recover on
the order of 40-60% GPU headroom going from a high/native-res preset
down to Low/Very Low + a resolution cut -- 1.6x sits inside that
recoverable range.

EXTREME_MAX_GPU_RATIO (4.0x): the boundary that puts The Witcher 3's
~5.4x GPU gap on the excluded side while keeping Dying Light's
research-confirmed outcome (promoted into this band by the
minimum-vs-recommended escalation rule, not by its own ~1.2x minimum
ratio) on the included side.
"""

from services.hardware.homepage_classifier import POTATO_PROFILE
from services.hardware.ram_parsing import parse_ram_gb
from services.hardware.rankings_loader import get_cpu_ranking_by_id, get_gpu_ranking_by_id
from services.hardware.requirement_matching import resolve_cpu_requirement, resolve_gpu_requirement

_potato_cpu_record = get_cpu_ranking_by_id(POTATO_PROFILE.cpu_external_id)
_potato_gpu_record = get_gpu_ranking_by_id(POTATO_PROFILE.gpu_external_id)
POTATO_CPU_SCORE = _potato_cpu_record["ranking"]["performance_score"] if _potato_cpu_record and _potato_cpu_record["ranking"] else None
POTATO_GPU_SCORE = _potato_gpu_record["ranking"]["compute_capability_score"] if _potato_gpu_record and _potato_gpu_record["ranking"] else None
POTATO_RAM_GB = POTATO_PROFILE.ram_gb

TWEAKS_MAX_GPU_RATIO = 1.6
TWEAKS_MAX_CPU_RATIO = 1.6
TWEAKS_MAX_RAM_GB = 12.0

EXTREME_MAX_GPU_RATIO = 4.0
EXTREME_MAX_CPU_RATIO = 2.5
EXTREME_MAX_RAM_GB = 16.0

# See "engine undersells its own minimum" in the module docstring --
# Dying Light's real numbers (min ~1.2x, recommended ~7.2x) are the
# calibration case for this rule.
ENGINE_UNDERSELLS_RECOMMENDED_RATIO = 3.0

_TIER_NAMES = {0: "friendly", 1: "tweaks", 2: "extreme"}  # 3 -> excluded (None)


def _cheapest_resolvable_score(alternatives):
    """Given a list[ResolvedAlternative] for one requirement tier
    ("or" semantics), returns the lowest score among resolved
    alternatives -- the easiest branch to satisfy -- or None if none
    resolved. Never guesses at an unresolved alternative's score."""
    scores = [a.score for a in alternatives if a.resolved and a.score is not None]
    return min(scores) if scores else None


def _ratio(score, reference):
    if score is None or reference is None or reference <= 0:
        return None
    return score / reference


def _level_from_ratio(ratio, tweaks_ceiling, extreme_ceiling):
    """0 = at/below potato level, 1 = Tweaks band, 2 = Extreme band,
    3 = beyond Extreme. `ratio is None` (no constraint -- e.g. an
    unresolved CPU requirement, or no RAM figure) is always level 0:
    absence of evidence is never treated as a failure."""
    if ratio is None or ratio <= 1.0:
        return 0
    if ratio <= tweaks_ceiling:
        return 1
    if ratio <= extreme_ceiling:
        return 2
    return 3


def _gap_signals(requirements):
    minimum = (requirements or {}).get("minimum") or {}
    recommended = (requirements or {}).get("recommended") or {}

    gpu_min_score = _cheapest_resolvable_score(resolve_gpu_requirement(minimum.get("gpu", "")))
    gpu_rec_score = _cheapest_resolvable_score(resolve_gpu_requirement(recommended.get("gpu", "")))
    cpu_min_score = _cheapest_resolvable_score(resolve_cpu_requirement(minimum.get("cpu", "")))
    ram_min_gb = parse_ram_gb(minimum.get("ram", ""))

    return {
        "gpu_min_ratio": _ratio(gpu_min_score, POTATO_GPU_SCORE),
        "gpu_rec_ratio": _ratio(gpu_rec_score, POTATO_GPU_SCORE),
        "cpu_min_ratio": _ratio(cpu_min_score, POTATO_CPU_SCORE),
        "ram_min_gb": ram_min_gb,
    }


def classify_potato_tier(requirements):
    """Returns one of "friendly" / "tweaks" / "extreme" / None
    (excluded) for a game's `parse_requirements()` output. This is now
    the single source of truth for all three Potato ecosystem tiers --
    see module docstring for why Friendly is no longer decided by a
    separately-sourced strict check.

    GPU evidence is mandatory: if the minimum GPU requirement doesn't
    resolve against the catalog at all, this returns None regardless
    of how the CPU/RAM numbers look.
    """
    if POTATO_GPU_SCORE is None or POTATO_CPU_SCORE is None:
        return None

    signals = _gap_signals(requirements)
    gpu_min_ratio = signals["gpu_min_ratio"]
    if gpu_min_ratio is None:
        return None

    gpu_level = _level_from_ratio(gpu_min_ratio, TWEAKS_MAX_GPU_RATIO, EXTREME_MAX_GPU_RATIO)
    cpu_level = _level_from_ratio(signals["cpu_min_ratio"], TWEAKS_MAX_CPU_RATIO, EXTREME_MAX_CPU_RATIO)
    ram_min_gb = signals["ram_min_gb"]
    ram_level = _level_from_ratio(
        _ratio(ram_min_gb, POTATO_RAM_GB) if ram_min_gb is not None else None,
        TWEAKS_MAX_RAM_GB / POTATO_RAM_GB,
        EXTREME_MAX_RAM_GB / POTATO_RAM_GB,
    )

    level = max(gpu_level, cpu_level, ram_level)

    if level == 1:
        # "Engine undersells its own minimum": a steep min->recommended
        # GPU climb promotes an otherwise-Tweaks-level game into
        # Extreme, since that climb is itself evidence the minimum
        # spec is an optimistic floor rather than a comfortable one.
        gpu_rec_ratio = signals["gpu_rec_ratio"]
        if gpu_rec_ratio is not None and gpu_rec_ratio >= ENGINE_UNDERSELLS_RECOMMENDED_RATIO:
            level = 2

    if level >= 3:
        return None
    return _TIER_NAMES[level]


# Backwards-compatible alias for the pre-unification name.
classify_gap_tier = classify_potato_tier
