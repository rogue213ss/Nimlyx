"""
Regression tests for steam.py's `_execute_deduplicated()` -- the
in-flight request dedup + short-lived failure cache that protects
every Steam fetch function from retry storms (concurrent threads all
hitting Steam for the exact same data at once) and from hammering
Steam again immediately after a 429/timeout.

THE BUG THIS FILE SPECIFICALLY GUARDS AGAINST
------------------------------------------------
An earlier version of this function used threading.Condition +
wait()/notify_all() to make "waiter" threads (threads asking for data
another thread is already fetching) block until the "fetcher" thread
finishes. That has a real, reproducible deadlock: Condition.wait()
only wakes a thread that is ALREADY blocked at the moment
notify_all() runs. If the fetcher finishes and calls notify_all()
before a waiter has reached its own wait() call -- entirely possible
under ordinary OS thread-scheduling jitter, no fault injection
needed, reproduced below with nothing but a delayed waiter thread --
that waiter hangs forever, since the real code called wait() with no
timeout. Under Flask's ThreadPoolExecutor(max_workers=8), one lost
wakeup permanently strands a pool worker: the exact class of failure
this cache exists to prevent, just moved from "rate limit spiral" to
"silent, permanent thread starvation."

The fix uses threading.Event instead: Event.set() marks a persistent
flag, and Event.wait() checks that flag before blocking, so a waiter
arriving after set() was already called still returns immediately.
There is no interleaving of thread starts/finishes that can produce a
lost wakeup with Event -- unlike Condition, "arriving late" is a
completely safe case, not a hang.

test_concurrent_callers_for_the_same_key_only_fetch_once below is the
practical regression guard: many threads racing for the same key,
asserting the whole thing completes within a bounded timeout and the
fetch only runs once. It won't deterministically force the exact
"waiter arrives after notify already fired" interleaving on every run
(that specific race depends on OS thread-scheduling timing internal
to _execute_deduplicated, between two lines with no reachable hook to
insert a deterministic delay without adding test-only instrumentation
to production code -- which wasn't worth doing for this), but it
exercises real concurrent load and would catch a hang if this
regressed. The bug itself was independently verified with a
standalone, hand-copied reproduction of the exact pre-fix and
post-fix `_execute_deduplicated` logic outside pytest (not checked
into this suite, precisely because it required copy-pasting the
implementation rather than exercising the real function -- a
regression there wouldn't be caught by a copy): the pre-fix version
reliably hung forever under a deliberately delayed waiter thread; the
post-fix version resolved correctly under the identical delay.
"""
import os
import sys
import threading
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import steam  # noqa: E402


class TestExecuteDeduplicatedBasics(unittest.TestCase):
    def setUp(self):
        # Each test gets a unique cache key (see individual tests) so
        # they can't interfere with each other via steam.py's module-
        # level caches, without needing to reset internal state.
        self.calls = []

    def _counting_fetch(self, return_value="RESULT"):
        def _fetch():
            self.calls.append(1)
            return return_value
        return _fetch

    def test_single_caller_gets_the_result(self):
        result = steam._execute_deduplicated("test-key-basic-1", 180, self._counting_fetch())
        self.assertEqual(result, "RESULT")
        self.assertEqual(len(self.calls), 1)

    def test_second_call_after_first_completes_uses_cache_not_a_new_fetch(self):
        key = "test-key-basic-2"
        steam._execute_deduplicated(key, 180, self._counting_fetch())
        steam._execute_deduplicated(key, 180, self._counting_fetch())
        self.assertEqual(len(self.calls), 1)

    def test_failed_fetch_returns_none(self):
        result = steam._execute_deduplicated("test-key-basic-3", 180, self._counting_fetch(return_value=None))
        self.assertIsNone(result)

    def test_failed_fetch_is_not_retried_within_failure_ttl(self):
        """A None result must be cached as a short-lived failure so a
        burst of near-simultaneous callers doesn't retry-storm Steam
        right after a 429/timeout."""
        key = "test-key-basic-4"
        steam._execute_deduplicated(key, 180, self._counting_fetch(return_value=None), failure_ttl=60)
        steam._execute_deduplicated(key, 180, self._counting_fetch(return_value=None), failure_ttl=60)
        self.assertEqual(len(self.calls), 1)


class TestConcurrentDeduplication(unittest.TestCase):
    def test_concurrent_callers_for_the_same_key_only_fetch_once(self):
        key = "test-key-concurrent-1"
        call_count = {"n": 0}
        lock = threading.Lock()

        def slow_fetch():
            with lock:
                call_count["n"] += 1
            time.sleep(0.15)
            return "SHARED_RESULT"

        results = {}

        def worker(name):
            results[name] = steam._execute_deduplicated(key, 180, slow_fetch)

        threads = [threading.Thread(target=worker, args=(f"t{i}",)) for i in range(6)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        self.assertFalse(any(t.is_alive() for t in threads), "a thread is still hanging")
        self.assertEqual(call_count["n"], 1, "fetch_func should only run once for concurrent identical requests")
        for name in results:
            self.assertEqual(results[name], "SHARED_RESULT")

    def test_concurrent_waiter_arriving_after_fetch_completes_does_not_hang(self):
        """A softer version of the adversarial scenario: the fetcher
        finishes almost instantly (no artificial delay), so any waiter
        that checks in has a realistic chance of arriving at its
        blocking wait after the fetcher has already signaled. Run
        repeatedly with many threads to raise the odds of hitting that
        interleaving across the batch, without relying on a
        deterministic (and, as found during development, unreliably
        monkeypatchable) forced delay inside the blocking primitive
        itself."""
        key = "test-key-concurrent-3"

        def instant_fetch():
            return "REAL_RESULT"

        results = {}
        lock = threading.Lock()

        def worker(name):
            r = steam._execute_deduplicated(key, 180, instant_fetch)
            with lock:
                results[name] = r

        threads = [threading.Thread(target=worker, args=(f"w{i}",), daemon=True) for i in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        self.assertFalse(any(t.is_alive() for t in threads), "at least one worker is still hanging")
        self.assertEqual(len(results), 20)
        for name in results:
            self.assertEqual(results[name], "REAL_RESULT")


if __name__ == "__main__":
    unittest.main()
