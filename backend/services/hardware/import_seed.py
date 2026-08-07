"""Sprint 6 hardware seed/import pipeline -- run ONCE (and re-run
whenever the source data should be refreshed), never at request time.

    TechPowerUp API (techpowerup_client.py)
        |
        v
    coverage filter (coverage.py) -- Sprint 6's explicit GPU/CPU scope
        |
        v
    tier_score computed (tier_scoring.py) -- import-time only, per spec
        |
        v
    aliases generated + merged with hardware_aliases.json (alias_rules.py)
        |
        v
    idempotent upsert into hardware_devices (models.py / db.py)

The runtime app NEVER calls anything in this file, techpowerup_client,
coverage, tier_scoring, or alias_rules -- it only ever reads the
already-populated hardware_devices table. That separation is the
whole point of doing this as a seed script rather than a live
integration.

import_devices() is the core, fully-testable entry point: it takes an
already-fetched list of normalized device dicts (see
techpowerup_client.NORMALIZED_DEVICE_SHAPE) and does everything from
filtering through upsert. This means the entire pipeline -- coverage
filtering, scoring, alias merging, idempotent upsert -- is real,
runnable, and verifiable with synthetic data today, independent of
whether techpowerup_client's live fetch is wired up yet.

main() is the actual one-time-run entry point once the API adapter is
complete: fetches real data for "gpu" and "cpu" via
techpowerup_client.fetch_and_normalize() and feeds it to
import_devices().
"""

import os

from services.hardware.coverage import is_in_scope
from services.hardware.tier_scoring import score_device
from services.hardware.alias_rules import generate_aliases, merge_aliases
from services.hardware.db import get_session, init_db
from services.hardware.models import HardwareDevice


class ImportSummary:
    """Plain result object -- no magic, just counts + reasons, so a
    person running this script (or a future automated job) can see
    exactly what happened without reading logs line by line."""

    def __init__(self):
        self.inserted = 0
        self.updated = 0
        self.skipped_out_of_scope = 0
        self.skipped_unscored = 0
        self.skipped_invalid = 0

    def __repr__(self):
        return (
            f"ImportSummary(inserted={self.inserted}, updated={self.updated}, "
            f"skipped_out_of_scope={self.skipped_out_of_scope}, "
            f"skipped_unscored={self.skipped_unscored}, "
            f"skipped_invalid={self.skipped_invalid})"
        )


def _find_existing(session, device):
    """Match order per spec: stable external_id first (when the
    device has one AND some existing row already carries it), else
    fall back to (type, manufacturer, model_name) -- the DB-level
    unique constraint on that triple (see models.py) backs this up
    even if this lookup were ever bypassed."""
    external_id = device.get("external_id")
    if external_id:
        existing = (
            session.query(HardwareDevice)
            .filter_by(type=device["type"], external_id=external_id)
            .first()
        )
        if existing:
            return existing

    return (
        session.query(HardwareDevice)
        .filter_by(
            type=device["type"],
            manufacturer=device["manufacturer"],
            model_name=device["model_name"],
        )
        .first()
    )


def import_devices(devices):
    """devices: list of dicts matching
    techpowerup_client.NORMALIZED_DEVICE_SHAPE. Returns an
    ImportSummary. Safe to call with the same devices list repeated
    runs in a row -- idempotent, never duplicates (requirement #5).
    """
    summary = ImportSummary()
    init_db()  # no-op if tables already exist
    session = get_session()

    try:
        for device in devices or []:
            device_type = device.get("type")
            model_name = device.get("model_name")
            manufacturer = device.get("manufacturer")

            if device_type not in ("gpu", "cpu") or not model_name or not manufacturer:
                summary.skipped_invalid += 1
                continue

            if not is_in_scope(device_type, model_name):
                summary.skipped_out_of_scope += 1
                continue

            tier_score = score_device(device_type, model_name, vram_mb=device.get("vram_mb"))
            if tier_score is None:
                # Coverage said "in scope" but scoring couldn't
                # confidently place it -- rather than store a
                # fabricated tier_score (nullable=False on that
                # column specifically to prevent an unscored row from
                # ever silently existing), skip and count it. Worth
                # checking these afterward -- likely a coverage/
                # scoring regex mismatch worth tightening.
                summary.skipped_unscored += 1
                continue

            generated = generate_aliases(model_name)
            aliases = merge_aliases(model_name, generated)

            existing = _find_existing(session, device)
            if existing:
                existing.tier_score = tier_score
                existing.vram = device.get("vram_mb")
                existing.release_year = device.get("release_year")
                existing.aliases = ",".join(aliases) if aliases else None
                if device.get("external_id"):
                    existing.external_id = device["external_id"]
                summary.updated += 1
            else:
                session.add(HardwareDevice(
                    type=device_type,
                    manufacturer=manufacturer,
                    model_name=model_name,
                    external_id=device.get("external_id"),
                    tier_score=tier_score,
                    vram=device.get("vram_mb"),
                    release_year=device.get("release_year"),
                    aliases=",".join(aliases) if aliases else None,
                ))
                summary.inserted += 1

        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

    return summary


def _load_target_devices():
    """Reads target_devices.json (sibling file) -- the curated list of
    specific model names to search TechPowerUp for, per device type.
    Format: {"gpu": ["RTX 4090", "RX 6600 XT", ...], "cpu": [...]}.
    You fill this in; nothing else needs to change to pick up edits --
    same "separate data file, no importer changes needed" pattern as
    hardware_aliases.json. Returns {"gpu": [], "cpu": []} (not an
    error) if the file is missing/empty/malformed.
    """
    import json
    path = os.path.join(os.path.dirname(__file__), "target_devices.json")
    try:
        if not os.path.exists(path):
            return {"gpu": [], "cpu": []}
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return {
            "gpu": list(data.get("gpu", [])) if isinstance(data, dict) else [],
            "cpu": list(data.get("cpu", [])) if isinstance(data, dict) else [],
        }
    except Exception:
        return {"gpu": [], "cpu": []}


def main():
    """The real one-time-run entry point. Reads target_devices.json
    for the list of specific model names to search for (see that
    file's own comment -- the free tier gates broad/unfiltered
    queries, so this searches by name, once per device), fetches each
    via TechPowerUp, and imports the results.

    Not called anywhere automatically; run explicitly:
        python -m services.hardware.import_seed
    """
    from services.hardware.techpowerup_client import fetch_many_by_name, CPU_ENDPOINT

    targets = _load_target_devices()
    all_devices = []

    if targets["gpu"]:
        print(f"Fetching {len(targets['gpu'])} GPU(s) from TechPowerUp...")
        all_devices.extend(fetch_many_by_name("gpu", targets["gpu"]))
    else:
        print("No GPU names in target_devices.json -- skipping GPU fetch.")

    if targets["cpu"]:
        if CPU_ENDPOINT:
            print(f"Fetching {len(targets['cpu'])} CPU(s) from TechPowerUp...")
            all_devices.extend(fetch_many_by_name("cpu", targets["cpu"]))
        else:
            print(f"CPU endpoint not yet confirmed -- skipping {len(targets['cpu'])} CPU name(s) in target_devices.json.")
    else:
        print("No CPU names in target_devices.json -- skipping CPU fetch.")

    summary = import_devices(all_devices)
    print(summary)
    return summary


if __name__ == "__main__":
    main()