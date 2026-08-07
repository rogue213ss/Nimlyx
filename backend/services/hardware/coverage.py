"""Sprint 6 V1 hardware coverage scope -- what the importer will and
won't pull in, decided explicitly rather than importing "everything
TechPowerUp has." Matches the exact scope given for this sprint:

GPU:
  - NVIDIA GeForce GTX 900 series and newer (900, 10xx, 16xx)
  - NVIDIA GeForce RTX 20/30/40 series
  - AMD Radeon RX 400 series and newer (400, 500, Vega, 5000, 6000, 7000)
  - Intel Arc A-series
  - Intel HD Graphics / UHD Graphics integrated GPUs common in gaming PCs

CPU:
  - Intel Core 4th generation and newer, and Core Ultra
  - AMD FX series
  - AMD Ryzen 1000 series and newer
  - AMD Athlon models still relevant for compatibility checks

Deliberately NOT in V1 scope (excluded, not "not yet found"): GTX 700
series and older, GT/GTS/GTS-prefixed low-end pre-900 parts, AMD HD-
series discrete GPUs, R7/R9-series discrete GPUs, pre-4th-gen Intel
Core, Pentium/Celeron. These exist on the long-term roadmap (see the
original hardware list) but are explicitly out of this import pass --
"do not attempt to populate every historical CPU/GPU ever released in
V1" per spec.

Classification works off the device's own model_name string via
regex, not off any TechPowerUp-specific field -- this keeps coverage
filtering independent of exactly what shape the API adapter ends up
returning, and testable right now with plain strings (see the
self-test at the bottom of this file).
"""

import re

# ---------------- GPU ----------------

_NVIDIA_GTX_RE = re.compile(r"\bGTX\s?(9\d{2}|10\d{2}|16\d{2})\b", re.IGNORECASE)
_NVIDIA_RTX_RE = re.compile(r"\bRTX\s?(20|30|40)\d{2}\b", re.IGNORECASE)

# RX 400/500: 3-digit models in the 400-599 range (RX 460...RX 590).
# RX Vega: named, not numbered ("Radeon RX Vega 56/64").
# RX 5000/6000/7000: 4-digit models starting 5/6/7 (RX 5500 XT...7900 XTX).
_AMD_RX_3DIGIT_RE = re.compile(r"\bRX\s?([4-5]\d{2})\b", re.IGNORECASE)
_AMD_RX_VEGA_RE = re.compile(r"\bRX\s?Vega\b", re.IGNORECASE)
_AMD_RX_4DIGIT_RE = re.compile(r"\bRX\s?([5-7]\d{3})\b", re.IGNORECASE)

_INTEL_ARC_RE = re.compile(r"\bArc\s?A\d{3}\b", re.IGNORECASE)

# Integrated Intel graphics that actually show up in real gaming-PC
# compatibility checks -- a CURATED list of specific model numbers,
# not a blanket "any 3-4 digit HD/UHD Graphics" match. A blanket digit
# regex would also catch genuinely ancient, essentially-non-gaming
# parts like "HD Graphics 2000/3000" (Sandy Bridge, 2011) -- out of
# scope per "appear frequently in gaming PCs," not every SKU ever
# shipped. List covers Haswell through Raptor Lake-era parts that
# actually show up in real-world budget/prebuilt gaming systems.
_INTEL_IGPU_MODELS = {
    "4000", "4400", "4600",  # HD Graphics (Ivy Bridge/Haswell)
    "5500", "5600",           # HD Graphics (Broadwell/Skylake)
    "520", "530",              # HD Graphics (Skylake)
    "620", "630",              # UHD Graphics (Kaby Lake/Coffee Lake) -- also matches HD Graphics 620/630 naming
    "600", "605", "610", "615", "617",  # UHD Graphics (low-end Gemini Lake etc.)
    "730", "750", "770",       # UHD Graphics 7xx (Alder/Raptor Lake)
}
_INTEL_IGPU_RE = re.compile(
    r"\b(?:HD|UHD)\s?Graphics\s?(" + "|".join(sorted(_INTEL_IGPU_MODELS, key=len, reverse=True)) + r")\b",
    re.IGNORECASE,
)


def is_gpu_in_scope(model_name):
    """True if model_name falls within Sprint 6's explicit GPU scope.
    Never raises on odd input -- an unparseable/empty name is simply
    out of scope, not an error."""
    if not model_name or not isinstance(model_name, str):
        return False
    return bool(
        _NVIDIA_GTX_RE.search(model_name)
        or _NVIDIA_RTX_RE.search(model_name)
        or _AMD_RX_3DIGIT_RE.search(model_name)
        or _AMD_RX_VEGA_RE.search(model_name)
        or _AMD_RX_4DIGIT_RE.search(model_name)
        or _INTEL_ARC_RE.search(model_name)
        or _INTEL_IGPU_RE.search(model_name)
    )


# ---------------- CPU ----------------

# Intel Core "4th gen and newer": Intel's own model-number encoding is
# [generation digit(s)][3-digit SKU], e.g. "i5-4460" = gen 4 + "460",
# "i7-9700K" = gen 9 + "700" (+K suffix), "i9-13900K" = gen 13 + "900"
# (+K suffix). Single-digit gens (4-9) -> 4 total digits before any
# suffix; two-digit gens (10-14) -> 5 total digits before any suffix.
_INTEL_CORE_GEN_RE = re.compile(r"\bi[3579]-([4-9]\d{3}|1[0-4]\d{3})[A-Z]{0,2}\b", re.IGNORECASE)
_INTEL_CORE_ULTRA_RE = re.compile(r"\bCore\s?Ultra\s?[3579]\b", re.IGNORECASE)

_AMD_FX_RE = re.compile(r"\bFX-?\d{4}\b", re.IGNORECASE)
# Suffix after the 4-digit model can mix letters and digits (X3D, XT,
# G, GE) -- not letters-only, hence [A-Z0-9] rather than [A-Z].
_AMD_RYZEN_RE = re.compile(r"\bRyzen\s?[3579]\s?\d{4}[A-Z0-9]{0,4}\b", re.IGNORECASE)

# Athlon: only the still-relevant modern line (Athlon 200GE/220GE/
# 3000G-style AM4 parts), not the entire 2000s-era Athlon XP/64
# lineage -- "models still relevant for compatibility checks" per spec.
_AMD_ATHLON_MODERN_RE = re.compile(r"\bAthlon\s?(200GE|220GE|240GE|300GE|300U|3000G)\b", re.IGNORECASE)


def is_cpu_in_scope(model_name):
    """True if model_name falls within Sprint 6's explicit CPU scope.
    Never raises on odd input."""
    if not model_name or not isinstance(model_name, str):
        return False
    return bool(
        _INTEL_CORE_GEN_RE.search(model_name)
        or _INTEL_CORE_ULTRA_RE.search(model_name)
        or _AMD_FX_RE.search(model_name)
        or _AMD_RYZEN_RE.search(model_name)
        or _AMD_ATHLON_MODERN_RE.search(model_name)
    )


def is_in_scope(device_type, model_name):
    """Single entry point the importer calls -- dispatches on
    device_type ("gpu"/"cpu"). Unknown device_type -> out of scope,
    never a crash."""
    if device_type == "gpu":
        return is_gpu_in_scope(model_name)
    if device_type == "cpu":
        return is_cpu_in_scope(model_name)
    return False


if __name__ == "__main__":
    # Self-test -- run directly (`python -m services.hardware.coverage`)
    # to sanity-check the regexes against representative real names,
    # independent of any live API call. Not part of the app's request
    # path; a development-time check only.
    should_include_gpu = [
        "NVIDIA GeForce GTX 960", "NVIDIA GeForce GTX 1060", "NVIDIA GeForce GTX 1660 Ti",
        "NVIDIA GeForce RTX 2060", "NVIDIA GeForce RTX 3060", "NVIDIA GeForce RTX 4090",
        "AMD Radeon RX 480", "AMD Radeon RX 580", "AMD Radeon RX Vega 64",
        "AMD Radeon RX 5700 XT", "AMD Radeon RX 6600 XT", "AMD Radeon RX 7900 XTX",
        "Intel Arc A770", "Intel Arc A380",
        "Intel UHD Graphics 630", "Intel HD Graphics 4600",
    ]
    should_exclude_gpu = [
        "NVIDIA GeForce GTX 750 Ti", "NVIDIA GeForce GT 710", "NVIDIA GeForce GTX 650",
        "AMD Radeon HD 7970", "AMD Radeon R9 290X", "AMD Radeon R7 260X",
        "Intel HD Graphics 2000",
    ]
    should_include_cpu = [
        "Intel Core i5-4460", "Intel Core i7-9700K", "Intel Core i9-13900K",
        "Intel Core Ultra 7", "AMD FX-8350", "AMD Ryzen 5 1600",
        "AMD Ryzen 7 5800X3D", "AMD Ryzen 9 7950X", "AMD Athlon 200GE",
    ]
    should_exclude_cpu = [
        "Intel Core i5-3570K", "Intel Pentium G4560", "Intel Celeron G3900",
        "AMD Athlon 64 X2 5000+", "AMD Athlon XP 3000+",
    ]

    failures = []
    for name in should_include_gpu:
        if not is_gpu_in_scope(name):
            failures.append(f"GPU should include but didn't: {name}")
    for name in should_exclude_gpu:
        if is_gpu_in_scope(name):
            failures.append(f"GPU should exclude but included: {name}")
    for name in should_include_cpu:
        if not is_cpu_in_scope(name):
            failures.append(f"CPU should include but didn't: {name}")
    for name in should_exclude_cpu:
        if is_cpu_in_scope(name):
            failures.append(f"CPU should exclude but included: {name}")

    if failures:
        print(f"{len(failures)} coverage self-test failure(s):")
        for f in failures:
            print(" -", f)
    else:
        print(f"All coverage self-tests passed ({len(should_include_gpu) + len(should_exclude_gpu) + len(should_include_cpu) + len(should_exclude_cpu)} cases).")