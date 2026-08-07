"""Spec-derived tier_score heuristic -- IMPORT-TIME ONLY.

Per Sprint 6 spec: "Keep tier_score generation inside the seed/import
process. Do not place scoring logic inside the runtime compatibility
engine." This module is only ever imported by import_seed.py. The
future runtime compatibility engine (not built yet) will only ever
READ the already-computed tier_score column off hardware_devices --
it will never call anything in this file.

WHY SPEC-DERIVED, NOT BENCHMARK-DERIVED: PassMark's benchmark data is
a paid, licensed commercial product (confirmed directly from their own
site: "We license out the data") -- not something to bulk-import for
free. Rather than pay for a benchmark license just to produce a rough
0-100 ordering, this derives tier_score from spec fields the free
TechPowerUp API already provides (generation/series, VRAM, core count,
clock speed) using a transparent, documented formula. This matches
what the roadmap itself asked for: "The goal is NOT inaccurate FPS
prediction. The goal is a reliable compatibility verdict" -- a rough,
explainable ordering is the actual spec, not benchmark-grade
precision.

This is a HEURISTIC, not a measurement. It's isolated to this one
file specifically so it's easy to find, easy to replace (e.g. if a
PassMark license is purchased later, or a better free source appears)
without touching the importer's control flow or the runtime engine at
all -- only this module's two functions would need to change.
"""

import re

# ---------------- GPU ----------------

# Baseline anchor scores per recognized series/generation, roughly
# ordered by real-world relative performance. Anchors, not exact
# scores -- vram/model-number-within-series adjustments below refine
# within a series. Deliberately conservative/approximate; see module
# docstring on why this is a heuristic, not a benchmark.
_GPU_SERIES_ANCHORS = [
    # (regex, base_score)
    (re.compile(r"\bGTX\s?9\d{2}\b", re.IGNORECASE), 18),
    (re.compile(r"\bGTX\s?10\d{2}\b", re.IGNORECASE), 28),
    (re.compile(r"\bGTX\s?16\d{2}\b", re.IGNORECASE), 34),
    (re.compile(r"\bRTX\s?20\d{2}\b", re.IGNORECASE), 42),
    (re.compile(r"\bRTX\s?30\d{2}\b", re.IGNORECASE), 55),
    (re.compile(r"\bRTX\s?40\d{2}\b", re.IGNORECASE), 68),
    (re.compile(r"\bRX\s?[4-5]\d{2}\b", re.IGNORECASE), 20),
    (re.compile(r"\bRX\s?Vega\b", re.IGNORECASE), 32),
    (re.compile(r"\bRX\s?5\d{3}\b", re.IGNORECASE), 40),
    (re.compile(r"\bRX\s?6\d{3}\b", re.IGNORECASE), 52),
    (re.compile(r"\bRX\s?7\d{3}\b", re.IGNORECASE), 65),
    (re.compile(r"\bArc\s?A\d{3}\b", re.IGNORECASE), 38),
    (re.compile(r"\b(HD|UHD)\s?Graphics\b", re.IGNORECASE), 5),
]

# Within a series, the LAST 2 digits of the model number correlate
# loosely with tier (60 < 70 < 80 < 90 for NVIDIA; XT/Ti/SUPER push
# up). Small, capped adjustment -- this is intentionally a minor
# refinement on top of the series anchor, not a second scoring system.
_GPU_TIER_SUFFIX_RE = re.compile(r"(\d{2})(?:\s?(Ti|SUPER|XT|XTX))?\s*$", re.IGNORECASE)


def score_gpu(model_name, vram_mb=None):
    """Returns an int 0-100 tier_score, or None if model_name doesn't
    match any known GPU series (caller should skip/flag such rows
    rather than storing a fabricated score). Never raises."""
    if not model_name or not isinstance(model_name, str):
        return None
    try:
        base = None
        for pattern, anchor in _GPU_SERIES_ANCHORS:
            if pattern.search(model_name):
                base = anchor
                break
        if base is None:
            return None

        score = base

        # Within-series nudge from the trailing model number/suffix.
        suffix_match = _GPU_TIER_SUFFIX_RE.search(model_name.strip())
        if suffix_match:
            last_two_digits = int(suffix_match.group(1))
            # 50/60-class ~ +0, 70-class ~ +4, 80-class ~ +8, 90-class ~ +12
            score += max(0, (last_two_digits - 50) // 10) * 4
            if suffix_match.group(2):
                score += 3  # Ti/SUPER/XT/XTX bump

        # VRAM nudge -- capped small contribution, never the dominant
        # factor (a low-tier GPU with unusually high VRAM shouldn't
        # leapfrog a genuinely faster card).
        if vram_mb:
            vram_gb = vram_mb / 1024
            score += min(6, int(vram_gb))

        return max(0, min(100, round(score)))
    except Exception:
        return None


# ---------------- CPU ----------------

_CPU_FAMILY_ANCHORS = [
    (re.compile(r"\bi3-", re.IGNORECASE), 25),
    (re.compile(r"\bi5-", re.IGNORECASE), 45),
    (re.compile(r"\bi7-", re.IGNORECASE), 62),
    (re.compile(r"\bi9-", re.IGNORECASE), 78),
    (re.compile(r"\bCore\s?Ultra\s?3\b", re.IGNORECASE), 45),
    (re.compile(r"\bCore\s?Ultra\s?5\b", re.IGNORECASE), 60),
    (re.compile(r"\bCore\s?Ultra\s?7\b", re.IGNORECASE), 72),
    (re.compile(r"\bCore\s?Ultra\s?9\b", re.IGNORECASE), 85),
    (re.compile(r"\bFX-?\d{4}\b", re.IGNORECASE), 22),
    (re.compile(r"\bRyzen\s?3\b", re.IGNORECASE), 30),
    (re.compile(r"\bRyzen\s?5\b", re.IGNORECASE), 48),
    (re.compile(r"\bRyzen\s?7\b", re.IGNORECASE), 65),
    (re.compile(r"\bRyzen\s?9\b", re.IGNORECASE), 82),
    (re.compile(r"\bAthlon\b", re.IGNORECASE), 12),
]

# Intel generation digit (see coverage.py for the same encoding logic)
# and AMD Ryzen series digit both nudge score up slightly per
# generation -- a 13th-gen i7 should rank a bit above a 4th-gen i7.
_INTEL_GEN_RE = re.compile(r"\bi[3579]-([4-9]|1[0-4])\d{3}", re.IGNORECASE)
_RYZEN_SERIES_RE = re.compile(r"\bRyzen\s?[3579]\s?(\d)\d{3}", re.IGNORECASE)


def score_cpu(model_name):
    """Returns an int 0-100 tier_score, or None if model_name doesn't
    match any known CPU family. Never raises."""
    if not model_name or not isinstance(model_name, str):
        return None
    try:
        base = None
        for pattern, anchor in _CPU_FAMILY_ANCHORS:
            if pattern.search(model_name):
                base = anchor
                break
        if base is None:
            return None

        score = base

        gen_match = _INTEL_GEN_RE.search(model_name)
        if gen_match:
            gen = int(gen_match.group(1))
            score += max(0, gen - 4) * 1.5  # +1.5 per gen above 4th

        ryzen_match = _RYZEN_SERIES_RE.search(model_name)
        if ryzen_match:
            series = int(ryzen_match.group(1))
            score += max(0, series - 1) * 3  # +3 per Ryzen series above 1000

        return max(0, min(100, round(score)))
    except Exception:
        return None


def score_device(device_type, model_name, vram_mb=None):
    """Single entry point the importer calls."""
    if device_type == "gpu":
        return score_gpu(model_name, vram_mb=vram_mb)
    if device_type == "cpu":
        return score_cpu(model_name)
    return None