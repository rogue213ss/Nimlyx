"""
Hardware Ranking Loader
========================

Makes the generated CPU/GPU ranking scores
(backend/data/hardware/rankings/{cpu,gpu}_rankings.json) available to the
rest of the backend by joining them onto the normalized hardware databases
(backend/data/hardware/normalized/{cpus,gpus}.json) by `external_id`.

WHY A SEPARATE LOADER, NOT THE EXISTING services/hardware/db.py TABLE:

This codebase already has a `HardwareDevice` SQLAlchemy table
(services/hardware/models.py) that is part of a DIFFERENT, pre-existing
initiative: the Sprint 5/6 TechPowerUp-sourced compatibility-engine track
(services/hardware/import_seed.py, tier_scoring.py, coverage.py,
compatibility.py). That table uses its own curated device scope, its own
external_id namespace (TechPowerUp's IDs), and its own 0-100 `tier_score`
scale intended for game-requirement matching. It is a separate concern from
this ranking system, which covers the full normalized catalog (2,627 GPUs /
418 CPUs) with a different, spec-derived scoring methodology
(single_thread_score / multi_thread_score / performance_score /
efficiency_score for CPU; compute_capability_score / efficiency_score /
category_percentile for GPU).

Merging the two would conflate two different scoring systems with two
different purposes and risk corrupting the compatibility-engine track this
codebase is already mid-build on. Per the current task's explicit scope
("do not begin compatibility-engine implementation yet"), this loader stays
fully isolated: it is pure in-memory Python, touches no database, writes
nothing, and is not wired into any Flask route or blueprint. It's a plain
importable module other backend code can call when it's ready to consume
ranking data.

WHAT THIS MODULE DOES:
  - Loads the normalized hardware databases and the ranking outputs from
    disk (read-only).
  - Joins each ranking record onto its normalized hardware record by
    `external_id`.
  - Exposes only the approved fields per record (see FIELD lists below) --
    everything else from the ranking file (raw shaders, clocks, etc.) is
    already available on the normalized record itself and is not
    duplicated here.
  - Runs integrity validation (see `validate_rankings()`) confirming every
    ranking external_id maps to exactly one hardware record, no orphaned
    ranking rows, no duplicate ranking ids, and that loading rankings never
    mutates the normalized hardware data in memory or on disk.

WHAT THIS MODULE DELIBERATELY DOES NOT DO:
  - It does not modify normalized/cpus.json, normalized/gpus.json,
    source/all-gpus.json, or any CPU batch file.
  - It does not recompute or alter any ranking formula/value.
  - It does not touch services/hardware/db.py, models.py, import_seed.py,
    or any part of the compatibility-engine track.
  - It does not register a Flask route. Any future route/blueprint that
    wants to expose rankings over HTTP can import and call the functions
    below.
"""

import json
import os

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.dirname(os.path.dirname(SCRIPT_DIR))  # services/hardware -> services -> backend
HARDWARE_DIR = os.path.join(BACKEND_DIR, "data", "hardware")
NORMALIZED_DIR = os.path.join(HARDWARE_DIR, "normalized")
RANKINGS_DIR = os.path.join(HARDWARE_DIR, "rankings")

CPUS_PATH = os.path.join(NORMALIZED_DIR, "cpus.json")
GPUS_PATH = os.path.join(NORMALIZED_DIR, "gpus.json")
CPU_RANKINGS_PATH = os.path.join(RANKINGS_DIR, "cpu_rankings.json")
GPU_RANKINGS_PATH = os.path.join(RANKINGS_DIR, "gpu_rankings.json")

# Fields exposed from the ranking record for each hardware type, per the
# approved integration scope. Note `rank` is the public name for the
# ranking file's `performance_rank` (CPU) / `compute_capability_rank` (GPU)
# fields -- the underlying rank concept, renamed at the loader boundary
# only, for a consistent public field name across CPU and GPU. The
# underlying ranking JSON files themselves are left exactly as generated.
CPU_RANKING_FIELDS = (
    "single_thread_score",
    "multi_thread_score",
    "performance_score",
    "efficiency_score",
)
GPU_RANKING_FIELDS = (
    "compute_capability_score",
    "efficiency_score",
    "category_percentile",
)


def _load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _index_by_external_id(records):
    """Builds a dict keyed by external_id. Does not deduplicate -- callers
    that need to know about duplicates should use `validate_rankings()`,
    which reports them explicitly rather than silently keeping "last one
    wins" behavior here."""
    index = {}
    for record in records:
        index.setdefault(record["external_id"], []).append(record)
    return index


def _join(hardware_records, ranking_records, ranking_fields, rank_source_field):
    """Joins ranking_records onto hardware_records by external_id.
    Returns a NEW list of dicts (hardware_records themselves are never
    mutated) containing every field from the original normalized hardware
    record plus the approved ranking fields under `ranking: {...}`.

    A hardware record whose external_id has no matching ranking record
    gets `ranking: None` rather than a dict of nulls -- this distinguishes
    "not ranked at all" (e.g. a future hardware addition ranking hasn't
    been regenerated for yet) from "ranked, but this particular score is
    null due to missing source data" (e.g. GPU shaders null), which is
    represented as an explicit `None` on that specific field inside the
    ranking dict.
    """
    ranking_index = _index_by_external_id(ranking_records)
    joined = []

    for hw in hardware_records:
        ext_id = hw["external_id"]
        matches = ranking_index.get(ext_id)

        ranking_out = None
        if matches:
            # validate_rankings() is the place duplicates get reported;
            # here we deterministically take the first match so this
            # function itself never raises on data it should instead be
            # reporting through validation.
            match = matches[0]
            ranking_out = {field: match.get(field) for field in ranking_fields}
            ranking_out["rank"] = match.get(rank_source_field)

        joined.append({
            **hw,  # original normalized hardware record, completely unchanged
            "ranking": ranking_out,
        })

    return joined


def get_cpus_with_rankings():
    """Returns every normalized CPU record with its ranking scores joined
    on under a `ranking` key. Read-only; does not touch cpus.json on disk.
    """
    cpus = _load_json(CPUS_PATH)
    cpu_rankings = _load_json(CPU_RANKINGS_PATH)["records"]
    return _join(cpus, cpu_rankings, CPU_RANKING_FIELDS, "performance_rank")


def get_gpus_with_rankings():
    """Returns every normalized GPU record with its ranking scores joined
    on under a `ranking` key. Read-only; does not touch gpus.json on disk.
    category_percentile is included as-is inside `ranking` -- it is
    explicitly NOT part of compute_capability_score and callers should not
    treat it as a scoring input, only as display/context data (matching
    how it was defined in the ranking methodology).
    """
    gpus = _load_json(GPUS_PATH)
    gpu_rankings = _load_json(GPU_RANKINGS_PATH)["records"]
    return _join(gpus, gpu_rankings, GPU_RANKING_FIELDS, "compute_capability_rank")


def get_cpu_ranking_by_id(external_id):
    """Convenience single-record lookup. Returns the joined record or None
    if external_id doesn't exist in the normalized CPU database."""
    for record in get_cpus_with_rankings():
        if record["external_id"] == external_id:
            return record
    return None


def get_gpu_ranking_by_id(external_id):
    """Convenience single-record lookup. Returns the joined record or None
    if external_id doesn't exist in the normalized GPU database."""
    for record in get_gpus_with_rankings():
        if record["external_id"] == external_id:
            return record
    return None


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

class RankingValidationResult:
    """Plain result object -- explicit counts and issue lists rather than
    a bare pass/fail, so a caller (or a human reading a printed report) can
    see exactly what was checked and what, if anything, failed."""

    def __init__(self):
        self.ok = True
        self.issues = []
        self.summary = {}

    def add_issue(self, message):
        self.ok = False
        self.issues.append(message)

    def __repr__(self):
        status = "OK" if self.ok else "FAILED"
        return f"RankingValidationResult({status}, issues={len(self.issues)}, summary={self.summary})"


def validate_rankings():
    """Runs the integrity checks required before this loader is trusted by
    any caller:

      - every ranking external_id maps to exactly one existing hardware
        record (no orphaned ranking rows)
      - no duplicate external_ids within a ranking file
      - no duplicate external_ids within a normalized hardware file
        (re-verifies what the original inspection/validation pass already
        confirmed -- cheap to re-check here rather than assume it still
        holds)
      - loading rankings does not mutate the normalized hardware records on
        disk (hash comparison before/after a full load-and-join cycle)

    Deterministic ranking output itself (identical scores across repeated
    runs) was already established by the ranking generator's own validation
    pass (backend/scripts/generate_hardware_rankings.py +
    the separate validate_rankings.py script run against it) and is not
    re-verified here -- this function's job is specifically the INTEGRATION
    join, not the ranking generation math.

    Returns a RankingValidationResult. Never raises for data problems --
    those are reported as issues so a caller can decide how to handle them
    (e.g. log and continue with `ranking: None` on affected records, which
    is already this loader's behavior for unmatched hardware records).
    """
    import hashlib

    result = RankingValidationResult()

    def file_hash(path):
        with open(path, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()

    # Hash every source file this loader reads, before touching anything,
    # so we can prove afterward that loading + joining did not write to or
    # otherwise alter them.
    watched_paths = [CPUS_PATH, GPUS_PATH, CPU_RANKINGS_PATH, GPU_RANKINGS_PATH]
    hashes_before = {p: file_hash(p) for p in watched_paths}

    cpus = _load_json(CPUS_PATH)
    gpus = _load_json(GPUS_PATH)
    cpu_rankings = _load_json(CPU_RANKINGS_PATH)["records"]
    gpu_rankings = _load_json(GPU_RANKINGS_PATH)["records"]

    # --- duplicate-ID checks (source files) ---
    cpu_ids = [c["external_id"] for c in cpus]
    gpu_ids = [g["external_id"] for g in gpus]
    if len(cpu_ids) != len(set(cpu_ids)):
        result.add_issue(f"Duplicate external_id found in normalized cpus.json ({len(cpu_ids) - len(set(cpu_ids))} extra)")
    if len(gpu_ids) != len(set(gpu_ids)):
        result.add_issue(f"Duplicate external_id found in normalized gpus.json ({len(gpu_ids) - len(set(gpu_ids))} extra)")

    # --- duplicate-ID checks (ranking files) ---
    cpu_rank_ids = [r["external_id"] for r in cpu_rankings]
    gpu_rank_ids = [r["external_id"] for r in gpu_rankings]
    if len(cpu_rank_ids) != len(set(cpu_rank_ids)):
        result.add_issue(f"Duplicate external_id found in cpu_rankings.json ({len(cpu_rank_ids) - len(set(cpu_rank_ids))} extra)")
    if len(gpu_rank_ids) != len(set(gpu_rank_ids)):
        result.add_issue(f"Duplicate external_id found in gpu_rankings.json ({len(gpu_rank_ids) - len(set(gpu_rank_ids))} extra)")

    # --- orphan checks: every ranking external_id must exist in the
    # corresponding normalized hardware file ---
    cpu_id_set = set(cpu_ids)
    gpu_id_set = set(gpu_ids)
    orphaned_cpu_rankings = [rid for rid in cpu_rank_ids if rid not in cpu_id_set]
    orphaned_gpu_rankings = [rid for rid in gpu_rank_ids if rid not in gpu_id_set]
    if orphaned_cpu_rankings:
        result.add_issue(f"{len(orphaned_cpu_rankings)} CPU ranking external_id(s) have no matching hardware record: {orphaned_cpu_rankings[:5]}{'...' if len(orphaned_cpu_rankings) > 5 else ''}")
    if orphaned_gpu_rankings:
        result.add_issue(f"{len(orphaned_gpu_rankings)} GPU ranking external_id(s) have no matching hardware record: {orphaned_gpu_rankings[:5]}{'...' if len(orphaned_gpu_rankings) > 5 else ''}")

    # --- coverage: every hardware record should have a ranking entry
    # (informational, not a failure -- rankings not yet regenerated for a
    # newly-added hardware record would show up here without being a data
    # integrity bug) ---
    unranked_cpus = [cid for cid in cpu_ids if cid not in set(cpu_rank_ids)]
    unranked_gpus = [gid for gid in gpu_ids if gid not in set(gpu_rank_ids)]

    # --- run the actual join and confirm it doesn't mutate source data ---
    joined_cpus = get_cpus_with_rankings()
    joined_gpus = get_gpus_with_rankings()

    hashes_after = {p: file_hash(p) for p in watched_paths}
    for p in watched_paths:
        if hashes_before[p] != hashes_after[p]:
            result.add_issue(f"Source file changed during load/join: {p}")

    # Every hardware field on every joined record must still match the
    # original normalized record exactly (join must be additive-only).
    cpu_by_id = {c["external_id"]: c for c in cpus}
    for joined in joined_cpus:
        original = cpu_by_id[joined["external_id"]]
        for key, value in original.items():
            if joined.get(key) != value:
                result.add_issue(f"CPU record {joined['external_id']} field '{key}' altered during join")
                break

    gpu_by_id = {g["external_id"]: g for g in gpus}
    for joined in joined_gpus:
        original = gpu_by_id[joined["external_id"]]
        for key, value in original.items():
            if joined.get(key) != value:
                result.add_issue(f"GPU record {joined['external_id']} field '{key}' altered during join")
                break

    result.summary = {
        "cpu_hardware_records": len(cpus),
        "gpu_hardware_records": len(gpus),
        "cpu_ranking_records": len(cpu_rankings),
        "gpu_ranking_records": len(gpu_rankings),
        "cpu_records_with_ranking": len(cpu_ids) - len(unranked_cpus),
        "gpu_records_with_ranking": len(gpu_ids) - len(unranked_gpus),
        "cpu_unranked_count": len(unranked_cpus),
        "gpu_unranked_count": len(unranked_gpus),
        "orphaned_cpu_rankings": len(orphaned_cpu_rankings),
        "orphaned_gpu_rankings": len(orphaned_gpu_rankings),
    }

    return result


if __name__ == "__main__":
    # Manual, read-only check: `python -m services.hardware.rankings_loader`
    validation = validate_rankings()
    print(validation)
    for issue in validation.issues:
        print(f"  - {issue}")
