"""GPU/CPU tier scale -- the shared convention every hardware row's
`tier_score` (see models.py) and every future game-requirement
comparison will be measured against.

This module defines the SCALE ONLY. No tier assignment logic, no
lookup tables mapping specific GPUs to specific numbers -- that's
Sprint 6 population work, done by hand against real-world benchmark
data as each device row is added.

Scale:

    TIER_MIN = 0    -- weakest supported hardware (e.g. old Intel HD
                       integrated graphics, pre-2nd-gen CPUs)
    TIER_MAX = 100  -- current top-end enthusiast hardware

Reasoning for 0-100 rather than something narrower (e.g. 1-10):
Steam's own hardware spread is enormous -- a GT 710 and an RTX 4090
both need to be representable with meaningful separation between
every step in between, and 0-100 leaves enough headroom for new
device generations to slot in without renumbering everything below
them (e.g. leaving gaps like 10, 20, 35, 60 rather than sequential
1, 2, 3 makes room to insert a device released later that sits
between two existing tiers).

TIER_BANDS below groups the numeric scale into human-readable labels
purely for future UI use ("Entry", "Mid-range", etc.) -- these bands
are NOT used for compatibility comparisons themselves; the numeric
tier_score is. Comparisons are numeric so "GPU tier 42 vs. game
requires tier 35" can be evaluated precisely; the bands exist only so
a future UI isn't stuck showing a bare number.

GPU and CPU tiers share this SAME scale (both 0-100) rather than two
separate scales. This keeps a future compatibility verdict simple:
one game requirement tier per component type, compared against one
user-hardware tier of that same type, both on the same number line --
no cross-scale conversion needed anywhere in the comparison logic.
"""

TIER_MIN = 0
TIER_MAX = 100

# Human-readable bands over the numeric scale -- UI-facing labels
# only, never used in comparison logic (see module docstring).
# (min_inclusive, max_inclusive, label)
TIER_BANDS = (
    (0, 20, "Entry-Level"),
    (21, 40, "Budget"),
    (41, 60, "Mid-Range"),
    (61, 80, "High-End"),
    (81, 100, "Enthusiast"),
)


def tier_band_label(tier_score):
    """Maps a numeric tier_score to its human-readable band label, for
    future UI display only. Returns None if tier_score is outside
    TIER_MIN..TIER_MAX (an invalid/unset tier) rather than guessing
    at a label for a number the scale doesn't cover -- same
    "no fabricated data" principle as everywhere else in this app."""
    if tier_score is None or not (TIER_MIN <= tier_score <= TIER_MAX):
        return None
    for low, high, label in TIER_BANDS:
        if low <= tier_score <= high:
            return label
    return None  # unreachable given TIER_BANDS covers 0-100 fully, but never guess