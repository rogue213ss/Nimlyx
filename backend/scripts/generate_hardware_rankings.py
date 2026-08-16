"""
Nimlyx Hardware Ranking Engine
==============================

Generates deterministic, specification-derived CPU and GPU hardware scores
from the normalized hardware databases (backend/data/hardware/normalized/).

This implements the v3 ranking methodology as approved. Key properties of
that methodology, enforced throughout this script:

  * No architecture-generation multipliers. `architecture` is carried through
    as metadata only and never multiplies a score. We do not have benchmark
    data in the schema to derive true cross-architecture IPC or shader
    efficiency ratios, so we do not pretend to.
  * No release-date/release-year performance multiplier. Age is not used as
    a performance signal anywhere in the scoring path.
  * No vendor/manufacturer scoring coefficient.
  * No percentile, cohort-relative, or database-relative normalization.
    Every score is a pure function of that single record's own fields plus a
    small number of fixed, documented constants. This is what makes the
    output deterministic and stable under database growth (adding one new
    record cannot change any other record's score).
  * TDP never affects a raw performance score. It only feeds a separately
    computed efficiency_score (performance / TDP), and only when TDP is
    present.
  * Missing required fields are never coerced to zero. A record missing a
    required input for a given score gets `null` for that score plus a
    `partial_data` flag, not a fabricated number.

GPU memory bandwidth was evaluated and intentionally EXCLUDED from
compute_capability_score. See generate_hardware_rankings.py header notes /
implementation report for the reasoning: true bandwidth requires a
memory-type-specific data-rate multiplier (SDR/DDR/GDDR3.../HBM all differ),
and inventing that multiplier table was explicitly out of scope for this
pass. Raw `memory_bus_bits` / `memory_clock_mhz` are passed through as
reference fields only, not scored.

Locked constants (approved before implementation):
  SMT_FACTOR = 0.25   (CPU effective_cores diminishing-returns factor for
                        SMT/Hyper-Threading extra threads)

No other constants are used. GPU compute_capability_score is a direct
product (shaders * clock_component) with no weight split, since a weighted
sum of unlike-scaled terms would require an unapproved weight constant;
a direct product requires none.
"""

import json
import math
import os
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.dirname(SCRIPT_DIR)
HARDWARE_DIR = os.path.join(BACKEND_DIR, "data", "hardware")
NORMALIZED_DIR = os.path.join(HARDWARE_DIR, "normalized")
RANKINGS_DIR = os.path.join(HARDWARE_DIR, "rankings")

GPUS_PATH = os.path.join(NORMALIZED_DIR, "gpus.json")
CPUS_PATH = os.path.join(NORMALIZED_DIR, "cpus.json")

CPU_OUTPUT_PATH = os.path.join(RANKINGS_DIR, "cpu_rankings.json")
GPU_OUTPUT_PATH = os.path.join(RANKINGS_DIR, "gpu_rankings.json")
MANIFEST_OUTPUT_PATH = os.path.join(RANKINGS_DIR, "manifest.json")

# ---------------------------------------------------------------------------
# Locked constants
# ---------------------------------------------------------------------------

SMT_FACTOR = 0.25


# ---------------------------------------------------------------------------
# CPU scoring
# ---------------------------------------------------------------------------

def score_cpu(record):
    """
    Compute single_thread_score, multi_thread_score, performance_score,
    and efficiency_score for one normalized CPU record.

    Formula (locked, approved):
        clock_component = boost_clock_mhz, falling back to base_clock_mhz
                           when boost is null
        single_thread_score = clock_component
        effective_cores = physical_cores + (max(0, threads - cores) * SMT_FACTOR)
        multi_thread_score = effective_cores * clock_component
        performance_score = geometric_mean(single_thread_score, multi_thread_score)
        efficiency_score = performance_score / tdp_w   (null if tdp_w is null)

    Explicitly NOT used as inputs, per the approved methodology:
        manufacturer, architecture, release_year, has_integrated_graphics,
        mobile/desktop classification (not even computed here, since the
        schema doesn't carry it and it would not affect scoring regardless).
    """
    cores = record["cpu_cores"]
    threads = record["cpu_threads"]
    base_clock = record["base_clock_mhz"]
    boost_clock = record["boost_clock_mhz"]
    tdp = record["tdp_w"]

    boost_estimated = boost_clock is None
    clock_component = boost_clock if boost_clock is not None else base_clock

    partial_data = boost_estimated  # true if we had to fall back to base clock

    # clock_component should always be present (base_clock_mhz has 0 nulls in
    # the normalized DB per inspection), but guard defensively rather than
    # assume that will always hold true for future data additions.
    if clock_component is None:
        return {
            "single_thread_score": None,
            "multi_thread_score": None,
            "performance_score": None,
            "efficiency_score": None,
            "boost_clock_estimated": boost_estimated,
            "partial_data": True,
            "partial_data_reason": "missing both base_clock_mhz and boost_clock_mhz",
        }

    single_thread_score = float(clock_component)

    extra_threads = max(0, threads - cores)
    effective_cores = cores + (extra_threads * SMT_FACTOR)
    multi_thread_score = effective_cores * clock_component

    # Geometric mean of the two component scores. Both are guaranteed > 0
    # here (clock_component > 0 for any real CPU, effective_cores >= 1),
    # so no domain issues.
    performance_score = math.sqrt(single_thread_score * multi_thread_score)

    if tdp is not None and tdp > 0:
        efficiency_score = performance_score / tdp
    else:
        efficiency_score = None

    return {
        "single_thread_score": round(single_thread_score, 4),
        "multi_thread_score": round(multi_thread_score, 4),
        "performance_score": round(performance_score, 4),
        "efficiency_score": round(efficiency_score, 6) if efficiency_score is not None else None,
        "boost_clock_estimated": boost_estimated,
        "partial_data": partial_data,
        "partial_data_reason": "boost_clock_mhz missing, used base_clock_mhz" if boost_estimated else None,
    }


def build_cpu_rankings(cpus):
    ranked = []
    for record in cpus:
        scores = score_cpu(record)
        ranked.append({
            "external_id": record["external_id"],
            "model_name": record["model_name"],
            "manufacturer": record["manufacturer"],  # metadata only, never a coefficient
            "architecture": record["architecture"],  # metadata only, never a multiplier
            "release_year": record["release_year"],  # metadata only, never a multiplier
            "cpu_cores": record["cpu_cores"],
            "cpu_threads": record["cpu_threads"],
            "tdp_w": record["tdp_w"],
            "has_integrated_graphics": record["has_integrated_graphics"],
            **scores,
        })

    # Deterministic rank assignment: sort by performance_score descending,
    # nulls last, tie-broken by external_id for full determinism.
    def sort_key(r):
        score = r["performance_score"]
        has_score = score is not None
        return (not has_score, -score if has_score else 0, r["external_id"])

    ranked_sorted = sorted(ranked, key=sort_key)
    rank = 0
    last_score = object()
    for i, r in enumerate(ranked_sorted):
        if r["performance_score"] is None:
            r["performance_rank"] = None
            continue
        rank += 1
        r["performance_rank"] = rank

    return ranked  # preserve original source order in the output file itself


# ---------------------------------------------------------------------------
# GPU scoring
# ---------------------------------------------------------------------------

def score_gpu(record):
    """
    Compute compute_capability_score and efficiency_score for one normalized
    GPU record.

    Formula (locked, approved):
        clock_component = boost_clock_mhz, falling back to base_clock_mhz
                           when boost is null (defensive fallback; in
                           practice both fields have 0 nulls in this DB)
        compute_capability_score = shaders * clock_component
            (null, partial_data=True, if shaders is null -- 661 records)
        efficiency_score = compute_capability_score / tdp_w
            (null if tdp_w is null -- 585 records -- or if
             compute_capability_score itself is null)

    Explicitly NOT used as inputs, per the approved methodology:
        vendor, architecture, release_date, vram_gb, process_node_nm,
        memory_bus_bits / memory_clock_mhz (see module docstring: true
        bandwidth cannot be derived without an unapproved memory-type
        data-rate multiplier table, so it is excluded from the score
        entirely and passed through only as unscored reference fields).
    """
    shaders = record["shaders"]
    base_clock = record["base_clock_mhz"]
    boost_clock = record["boost_clock_mhz"]
    tdp = record["tdp_w"]

    boost_estimated = boost_clock is None
    clock_component = boost_clock if boost_clock is not None else base_clock

    if clock_component is None:
        # Not expected given current data (0 nulls on both clock fields),
        # but handled honestly rather than assumed impossible.
        return {
            "compute_capability_score": None,
            "efficiency_score": None,
            "boost_clock_estimated": boost_estimated,
            "partial_data": True,
            "partial_data_reason": "missing both base_clock_mhz and boost_clock_mhz",
            "memory_bandwidth_derivable": False,
        }

    if shaders is None:
        compute_capability_score = None
        partial_data = True
        partial_data_reason = "shaders is null; compute_capability_score cannot be computed"
    else:
        compute_capability_score = float(shaders) * float(clock_component)
        partial_data = boost_estimated
        partial_data_reason = "boost_clock_mhz missing, used base_clock_mhz" if boost_estimated else None

    if compute_capability_score is not None and tdp is not None and tdp > 0:
        efficiency_score = compute_capability_score / tdp
    else:
        efficiency_score = None

    # Memory bandwidth was evaluated and intentionally excluded from the
    # score (see module docstring). We still report whether the raw fields
    # needed to attempt a bandwidth calculation are even present, purely as
    # an informational flag for future work -- NOT used in any score here.
    memory_bandwidth_derivable = (
        record["memory_bus_bits"] is not None and record["memory_clock_mhz"] is not None
    )

    return {
        "compute_capability_score": round(compute_capability_score, 4) if compute_capability_score is not None else None,
        "efficiency_score": round(efficiency_score, 6) if efficiency_score is not None else None,
        "boost_clock_estimated": boost_estimated,
        "partial_data": partial_data,
        "partial_data_reason": partial_data_reason,
        "memory_bandwidth_derivable": memory_bandwidth_derivable,
    }


def build_gpu_rankings(gpus):
    ranked = []
    for record in gpus:
        scores = score_gpu(record)
        ranked.append({
            "external_id": record["external_id"],
            "name": record["name"],
            "vendor": record["vendor"],           # metadata only, never a coefficient
            "category": record["category"],
            "architecture": record["architecture"],  # metadata only, never a multiplier
            "release_date": record["release_date"],  # metadata only, never a multiplier
            "shaders": record["shaders"],
            "tdp_w": record["tdp_w"],
            "vram_gb": record["vram_gb"],          # reference only, never scored
            "memory_bus_bits": record["memory_bus_bits"],   # reference only, unscored
            "memory_clock_mhz": record["memory_clock_mhz"], # reference only, unscored
            "memory_type": record["memory_type"],           # reference only, unscored
            **scores,
        })

    def sort_key(r):
        score = r["compute_capability_score"]
        has_score = score is not None
        return (not has_score, -score if has_score else 0, r["external_id"])

    ranked_sorted = sorted(ranked, key=sort_key)
    rank = 0
    for r in ranked_sorted:
        if r["compute_capability_score"] is None:
            r["compute_capability_rank"] = None
            continue
        rank += 1
        r["compute_capability_rank"] = rank

    # category_score: validation/display-only relative standing within
    # Consumer / Professional / Integrated cohort. This is NOT part of
    # compute_capability_score and NOT used anywhere in scoring math -- it
    # is a separate, clearly-labeled percentile computed purely for display
    # / sanity-check purposes, consistent with the approved methodology
    # (percentile is permitted for validation/display, never for scoring).
    by_category = {}
    for r in ranked:
        by_category.setdefault(r["category"], []).append(r)

    for category, records in by_category.items():
        scored = [r for r in records if r["compute_capability_score"] is not None]
        scored_sorted = sorted(scored, key=lambda r: r["compute_capability_score"])
        n = len(scored_sorted)
        for idx, r in enumerate(scored_sorted):
            # Percentile rank within category, display-only.
            r["category_percentile"] = round(100.0 * (idx + 1) / n, 2) if n > 0 else None
        for r in records:
            if r["compute_capability_score"] is None:
                r["category_percentile"] = None

    return ranked  # preserve original source order in the output file itself


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def write_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")


def main():
    os.makedirs(RANKINGS_DIR, exist_ok=True)

    cpus = load_json(CPUS_PATH)
    gpus = load_json(GPUS_PATH)

    cpu_rankings = build_cpu_rankings(cpus)
    gpu_rankings = build_gpu_rankings(gpus)

    cpu_output = {
        "schema_version": "1.0",
        "methodology_version": "v3",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "record_count": len(cpu_rankings),
        "constants": {
            "SMT_FACTOR": SMT_FACTOR,
        },
        "records": cpu_rankings,
    }

    gpu_output = {
        "schema_version": "1.0",
        "methodology_version": "v3",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "record_count": len(gpu_rankings),
        "constants": {},
        "notes": (
            "compute_capability_score = shaders * clock_component. "
            "Memory bandwidth intentionally excluded -- see script docstring."
        ),
        "records": gpu_rankings,
    }

    write_json(CPU_OUTPUT_PATH, cpu_output)
    write_json(GPU_OUTPUT_PATH, gpu_output)

    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "methodology_version": "v3",
        "cpu_record_count": len(cpu_rankings),
        "gpu_record_count": len(gpu_rankings),
        "cpu_source": os.path.relpath(CPUS_PATH, BACKEND_DIR),
        "gpu_source": os.path.relpath(GPUS_PATH, BACKEND_DIR),
        "outputs": {
            "cpu_rankings": os.path.relpath(CPU_OUTPUT_PATH, BACKEND_DIR),
            "gpu_rankings": os.path.relpath(GPU_OUTPUT_PATH, BACKEND_DIR),
        },
    }
    write_json(MANIFEST_OUTPUT_PATH, manifest)

    print(f"CPU rankings written: {CPU_OUTPUT_PATH} ({len(cpu_rankings)} records)")
    print(f"GPU rankings written: {GPU_OUTPUT_PATH} ({len(gpu_rankings)} records)")
    print(f"Manifest written: {MANIFEST_OUTPUT_PATH}")


if __name__ == "__main__":
    main()
