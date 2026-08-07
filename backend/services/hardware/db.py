"""Hardware DB engine/session setup -- Sprint 5 foundation only.

This is a SEPARATE, self-contained SQLAlchemy setup, not a general
app-wide database layer. Nimlyx has no database today (see app.py --
Flask + Blueprints only, every other feature is stateless/Steam-
sourced or in-memory cached). The hardware tier system is the first
piece of Nimlyx that has a genuine reason to need one: GPU/CPU tier
data is Nimlyx's own data, not something Steam provides, and per the
Phase 2 planning decision it belongs in a real table (not a Python
dict) so new hardware can be added without a redeploy.

Nothing in this module runs automatically. `init_db()` must be called
explicitly (a Sprint 6 seeding script will do this) -- importing this
module, or importing services.hardware generally, has zero side
effects and creates no tables, no connection, nothing. This keeps
Sprint 5 honest to its own scope: schema direction, not a live
database.

Connection target:
  - DATABASE_URL env var if set (this is what Sprint 6 will point at
    a real Postgres instance on Render -- matches the same
    environment-variable pattern Render deployments already expect).
  - Falls back to a local SQLite file (hardware.db, in this
    directory) for local development when DATABASE_URL isn't set.

SQLAlchemy is the only new dependency this introduces. It's added
specifically because Sprint 5's own decision was "table approach, not
Python dictionaries" -- this is that decision's plumbing, not an
unrelated new dependency.
"""

import os

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

_DEFAULT_SQLITE_PATH = os.path.join(os.path.dirname(__file__), "hardware.db")
DATABASE_URL = os.environ.get("DATABASE_URL", f"sqlite:///{_DEFAULT_SQLITE_PATH}")

# echo=False -- this stays quiet by default; flip locally if you need
# to see generated SQL while building Sprint 6's seeding script.
engine = create_engine(DATABASE_URL, echo=False, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)

Base = declarative_base()


def init_db():
    """Creates every table declared in models.py against `engine`, if
    they don't already exist. Not called anywhere in this codebase
    yet -- Sprint 6's seeding script is the intended caller. Safe to
    call repeatedly (create_all is a no-op for tables that already
    exist)."""
    from services.hardware import models  # noqa: F401 -- import registers models on Base.metadata
    Base.metadata.create_all(bind=engine)


def get_session():
    """Returns a new Session bound to the hardware engine. Callers are
    responsible for closing it (use as a context manager or call
    .close() when done). Not used anywhere yet -- provided now so
    Sprint 6's seeding script and, later, the compatibility engine
    both have one obvious, shared way to talk to this database
    instead of each rolling their own connection handling."""
    return SessionLocal()