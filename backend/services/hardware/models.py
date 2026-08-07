"""HardwareDevice -- the schema for Nimlyx's own GPU/CPU tier table.

One row = one real hardware model (a specific GPU or CPU), matching
the shape agreed in Phase 2 planning:

    id             INTEGER   primary key
    type           TEXT      "gpu" or "cpu"
    manufacturer   TEXT      "NVIDIA" / "AMD" / "Intel"
    model_name     TEXT      canonical display name, e.g. "RX 590"
    tier_score     INTEGER   Nimlyx's own relative performance tier
                              (see tiers.py for the scale this sits on)
    vram           INTEGER   VRAM in MB; NULL for CPUs
    release_year   INTEGER
    aliases        TEXT      comma-separated alternate names Steam's
                              own requirement text uses for this same
                              part, e.g. "Radeon RX590,RX 590 Series"
                              for one RX 590 row -- this is what will
                              let the future compatibility engine match
                              a game's free-text requirement string
                              back to a specific tier row.

Sprint 6 addition -- `external_id`: TechPowerUp's own stable per-
device identifier, when their API provides one, so re-running the
importer months later (after they've added/corrected entries) can
match existing rows by a real stable ID instead of by name alone.
Nullable because it's populated by the importer, not guessed --  a
device seeded before this field was wired up, or from a source that
has no such ID, simply has NULL here and falls back to the
(type, manufacturer, model_name) unique constraint below.
"""

from sqlalchemy import Column, Integer, String, UniqueConstraint

from services.hardware.db import Base


class HardwareDevice(Base):
    __tablename__ = "hardware_devices"
    __table_args__ = (
        # The importer's fallback match key (see
        # services/hardware/import_seed.py) when external_id isn't
        # available for a device. Also just good data hygiene -- two
        # rows for "NVIDIA GeForce RTX 3060" (gpu) should never exist.
        UniqueConstraint("type", "manufacturer", "model_name", name="uq_hardware_device_identity"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)

    # "gpu" or "cpu" -- kept as a plain string rather than a SQL enum
    # so adding a future type (e.g. "apu" for integrated graphics that
    # need distinct handling) never requires a schema migration, just
    # a new accepted value.
    type = Column(String(8), nullable=False, index=True)

    manufacturer = Column(String(32), nullable=False)
    model_name = Column(String(128), nullable=False, index=True)

    # TechPowerUp's own stable device ID, when the source API provides
    # one. Preferred match key for idempotent re-imports; falls back
    # to (type, manufacturer, model_name) when NULL. Not unique-
    # enforced at the DB level (NULLs would break that on most
    # backends anyway) -- the importer enforces "stable ID if present,
    # else name" match logic itself. See import_seed.py.
    external_id = Column(String(64), nullable=True, index=True)

    # See tiers.py for what this number means and its valid range.
    tier_score = Column(Integer, nullable=False, index=True)

    vram = Column(Integer, nullable=True)  # MB; NULL for CPUs
    release_year = Column(Integer, nullable=True)

    # Comma-separated -- see module docstring above for why.
    aliases = Column(String(512), nullable=True)

    def __repr__(self):
        return f"<HardwareDevice {self.type}:{self.model_name} tier={self.tier_score}>"