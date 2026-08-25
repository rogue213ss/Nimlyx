"""
NIMLYX MEMORY STORE — the single in-memory data layer the homepage
(and anything else that used to make live Steam calls inline) reads
from, instead of making Steam part of the request path at all.

WHY THIS EXISTS
----------------
Before this: routes/pages.py had five near-identical hand-rolled
caches (_HERO_CACHE, _POTATO_CACHE, _CURATED_SEED_CACHE,
_NEW_RELEASES_CACHE, _TOP_SELLERS_CACHE), each with its own dict,
lock, TTL constant, and "_BUILD_IN_PROGRESS" set, and
services/hardware/verified_potato_pool.py had a sixth, structurally
identical one. Same pattern, copy-pasted six times. This module is
that pattern, written once, as a class every dataset registers with.

Nothing about the ACTUAL fetch/enrichment logic changes — every
builder function passed to register() is the exact same
build_hero_lineup() / build_potato_candidate_pool() / etc. call as
before, still going through steam.py's existing request
deduplication and failure caching. This only replaces the
boilerplate around "how is the result cached, and when does it
refresh" with one implementation.

GUARANTEES (same three the individual caches already had, now
enforced in one place instead of six):

1. STALE-BUT-AVAILABLE, NEVER EMPTY-ON-FAILURE
   A dataset's `data` is only ever replaced by a SUCCESSFUL build.
   If a rebuild raises (Steam timeout, 429, parse error, anything),
   the exception is logged and the existing `data` — even if old —
   stays exactly as it was. The only way `get()` returns the "empty"
   value is a true cold start: this key has never once built
   successfully since the process started.

2. ATOMIC SWAP
   A rebuild constructs its full result in a local variable first;
   only a fully-finished, successful build is assigned into the
   store, in one dict write. A reader never sees a half-updated
   dataset — either the old complete value or the new complete
   value, never a mix.

3. AT MOST ONE REBUILD IN FLIGHT PER (key, region)
   Mirrors every `_BUILD_IN_PROGRESS` set from before: if a
   background rebuild for (key, cc) is already running, a second
   caller asking for stale/missing data does NOT start a duplicate
   thread — it just gets the current (possibly stale, possibly
   empty) value back immediately.

TWO WAYS A REBUILD GETS TRIGGERED
-----------------------------------
- REQUEST-TRIGGERED (unchanged behavior): get() notices the entry is
  stale or missing and kicks off a background thread, exactly like
  every cache in this codebase already did.
- TIME-TRIGGERED (new): start_periodic_refresh() runs one long-lived
  background loop that wakes up periodically and refreshes any
  registered dataset whose TTL has elapsed, for every region it has
  ever seen a request for -- independent of whether anyone happens
  to be browsing at that exact moment. This is what makes "refresh
  every ~5h" a real guarantee instead of "refreshes the next time
  someone's unlucky enough to hit a stale entry."

This module intentionally still stores everything in plain
process-memory dicts, not a persistent database (see Anthropic
chat/plan: in-memory first, on a keep-alive-pinged Render free
instance that rarely restarts; swap in a persistence layer later
without redesigning the homepage, if deploy-triggered resets ever
become an actual problem in practice).
"""
import logging
import threading
import time

logger = logging.getLogger(__name__)


class _DatasetEntry:
    """One (key, region)'s cached state. Matches the shape asked for:
    data / last_updated / ttl / refreshing."""

    __slots__ = ("data", "last_updated", "refreshing")

    def __init__(self):
        self.data = None
        self.last_updated = None
        self.refreshing = False


class _Dataset:
    """One registered dataset (e.g. "hero", "potato_pool") — the
    builder function, its TTL, and one _DatasetEntry per region seen
    so far. `empty_value` is what get() returns on a true cold start
    (before any successful build for that region has ever happened),
    matching each dataset's existing "honest empty" shape (None,None
    for hero, [] for lists)."""

    __slots__ = ("key", "builder_fn", "ttl_seconds", "empty_value", "entries", "lock")

    def __init__(self, key, builder_fn, ttl_seconds, empty_value):
        self.key = key
        self.builder_fn = builder_fn
        self.ttl_seconds = ttl_seconds
        self.empty_value = empty_value
        self.entries = {}  # cc -> _DatasetEntry
        self.lock = threading.Lock()

    def _entry_for(self, cc):
        entry = self.entries.get(cc)
        if entry is None:
            entry = _DatasetEntry()
            self.entries[cc] = entry
        return entry

    def _is_stale(self, entry):
        if entry.last_updated is None:
            return True
        return (time.time() - entry.last_updated) >= self.ttl_seconds

    def _rebuild(self, cc):
        """Runs in a background thread. Builds the full new value
        BEFORE touching the store (atomic swap, guarantee #2 above);
        any exception leaves the existing entry.data untouched
        (guarantee #1)."""
        try:
            new_data = self.builder_fn(cc)
            with self.lock:
                entry = self._entry_for(cc)
                entry.data = new_data
                entry.last_updated = time.time()
        except Exception:
            logger.exception(
                "NimlyxMemoryStore: background rebuild failed for dataset=%r region=%s -- keeping existing data.",
                self.key, cc,
            )
        finally:
            with self.lock:
                self._entry_for(cc).refreshing = False

    def _maybe_start_rebuild(self, cc, entry):
        if entry.refreshing:
            return
        entry.refreshing = True
        threading.Thread(target=self._rebuild, args=(cc,), daemon=True).start()

    def get(self, cc):
        with self.lock:
            entry = self._entry_for(cc)
            has_data = entry.data is not None
            stale = self._is_stale(entry)
            if stale:
                self._maybe_start_rebuild(cc, entry)
            if has_data:
                return entry.data
        return self.empty_value

    def is_refreshing(self, cc):
        with self.lock:
            return self._entry_for(cc).refreshing

    def last_updated(self, cc):
        with self.lock:
            return self._entry_for(cc).last_updated

    def known_regions(self):
        with self.lock:
            return list(self.entries.keys())

    def refresh_now_if_stale(self, cc):
        """Used by the periodic loop -- same staleness check as get(),
        but never reads/returns data, purely triggers a rebuild if
        one's due and not already running."""
        with self.lock:
            entry = self._entry_for(cc)
            if self._is_stale(entry):
                self._maybe_start_rebuild(cc, entry)


class NimlyxMemoryStore:
    """The single store instance every route imports. One store per
    process (per gunicorn worker) -- see routes/pages.py's
    `_ensure_store_warmed()` for why datasets are registered at
    import time but builds themselves only ever start post-fork,
    inside a real request."""

    def __init__(self):
        self._datasets = {}
        self._periodic_thread_started = False
        self._periodic_lock = threading.Lock()

    def register(self, key, builder_fn, ttl_seconds, empty_value=None):
        """Call once per dataset, typically at module import time.
        `builder_fn(cc) -> data` is the existing fetch/enrich function,
        completely unchanged -- this module never calls Steam itself."""
        if key in self._datasets:
            raise ValueError(f"NimlyxMemoryStore: dataset {key!r} already registered.")
        self._datasets[key] = _Dataset(key, builder_fn, ttl_seconds, empty_value)

    def get(self, key, cc):
        return self._datasets[key].get(cc)

    def is_refreshing(self, key, cc):
        return self._datasets[key].is_refreshing(cc)

    def last_updated(self, key, cc):
        return self._datasets[key].last_updated(cc)

    def warm(self, cc):
        """Kick off an initial build for every registered dataset for
        this region, if it doesn't have one yet. Safe to call many
        times (e.g. once per incoming request) -- a dataset that
        already has data or is already refreshing is a no-op."""
        for dataset in self._datasets.values():
            dataset.get(cc)

    def start_periodic_refresh(self, interval_seconds=3600):
        """Starts ONE long-lived background thread (idempotent -- a
        second call is a no-op) that wakes up every `interval_seconds`
        and refreshes any (dataset, region) pair whose own TTL has
        elapsed, for every region this store has ever seen a request
        for. This is what makes the ~5h refresh independent of
        traffic, per the architecture doc: a dataset with a 24h TTL
        won't actually rebuild every time this loop wakes up (its own
        refresh_now_if_stale() no-ops until it's actually due) -- this
        loop is just the heartbeat, not a fixed "rebuild everything"
        cadence. Deliberately started from inside a request (see
        routes/pages.py), same post-fork-only reasoning as warm()."""
        with self._periodic_lock:
            if self._periodic_thread_started:
                return
            self._periodic_thread_started = True

        def _loop():
            while True:
                time.sleep(interval_seconds)
                for dataset in self._datasets.values():
                    for cc in dataset.known_regions():
                        dataset.refresh_now_if_stale(cc)

        threading.Thread(target=_loop, daemon=True).start()


# One store per process. Datasets register themselves here (see
# routes/pages.py and services/hardware/verified_potato_pool.py);
# nothing in this module calls Steam or knows what any dataset key
# actually means.
store = NimlyxMemoryStore()
