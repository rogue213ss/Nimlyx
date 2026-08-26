"""
Regression tests for the GPU cross-vendor note-generation bug.

Bug: _evaluate_gpu() used to track cross_vendor_seen as a single global
flag across both the minimum and recommended tiers, and appended the
"treated as unknown" note whenever ANY cross-vendor alternative was
encountered -- even when a same-vendor alternative in that same tier
had already produced a definitive True/False result. That made the
note misleading for cases like Black Myth: Wukong, where the GPU
result is a genuine, definitive FAIL, not an unknown.

These tests exercise _evaluate_gpu() directly (unit level, no Flask/DB
required) by monkeypatching resolve_gpu_requirement so each case's
alternative set is fully controlled.

Run with:
    python -m unittest backend.tests.test_gpu_cross_vendor_notes -v
"""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.hardware.compatibility import _evaluate_gpu  # noqa: E402
from services.hardware.requirement_matching import ResolvedAlternative  # noqa: E402


def _amd(raw, score):
    return ResolvedAlternative(raw, resolved=True, external_id=raw, name=raw, vendor="AMD", score=score)


def _nvidia(raw, score):
    return ResolvedAlternative(raw, resolved=True, external_id=raw, name=raw, vendor="NVIDIA", score=score)


def _intel(raw, score):
    return ResolvedAlternative(raw, resolved=True, external_id=raw, name=raw, vendor="Intel", score=score)


def _user_gpu(vendor, score):
    return {"vendor": vendor, "ranking": {"compute_capability_score": score}}


def _has_cross_vendor_note(notes):
    return any("treated as unknown" in n for n in notes)


class TestCrossVendorNoteIsTierAware(unittest.TestCase):
    def test_cross_vendor_plus_same_vendor_fail_is_definitive_no_note(self):
        """Case 1: NVIDIA (cross-vendor, unjudgeable) + AMD (same-vendor,
        FAILS) -> meets_minimum=False, no misleading 'unknown' note."""
        min_alts = [_nvidia("GTX 1060 6GB", 50), _amd("RX 580 8GB", 50)]

        def fake_resolve(text):
            return min_alts if text == "MIN" else []

        with patch("services.hardware.requirement_matching.resolve_gpu_requirement", side_effect=fake_resolve):
            verdict, notes = _evaluate_gpu("MIN", "", _user_gpu("AMD", 10))

        self.assertFalse(verdict.meets_minimum)
        self.assertFalse(_has_cross_vendor_note(notes))

    def test_cross_vendor_plus_same_vendor_pass_is_definitive_no_note(self):
        """Case 2: NVIDIA (cross-vendor, unjudgeable) + AMD (same-vendor,
        PASSES) -> meets_minimum=True, no misleading 'unknown' note."""
        min_alts = [_nvidia("GTX 1060 6GB", 50), _amd("RX 580 8GB", 5)]

        def fake_resolve(text):
            return min_alts if text == "MIN" else []

        with patch("services.hardware.requirement_matching.resolve_gpu_requirement", side_effect=fake_resolve):
            verdict, notes = _evaluate_gpu("MIN", "", _user_gpu("AMD", 10))

        self.assertTrue(verdict.meets_minimum)
        self.assertFalse(_has_cross_vendor_note(notes))

    def test_only_cross_vendor_alternatives_is_genuinely_unknown_note_present(self):
        """Case 3: only NVIDIA alternatives, user has an Intel GPU -> no
        judgeable branch exists at all -> meets_minimum=None, and the
        cross-vendor note SHOULD appear (this is the legitimate case)."""
        min_alts = [_nvidia("GTX 1060 6GB", 50), _nvidia("RTX 2060", 60)]

        def fake_resolve(text):
            return min_alts if text == "MIN" else []

        with patch("services.hardware.requirement_matching.resolve_gpu_requirement", side_effect=fake_resolve):
            verdict, notes = _evaluate_gpu("MIN", "", _user_gpu("Intel", 10))

        self.assertIsNone(verdict.meets_minimum)
        self.assertTrue(_has_cross_vendor_note(notes))

    def test_minimum_and_recommended_tiers_are_independent(self):
        """Black Myth: Wukong shape: both tiers have a same-vendor FAIL
        alongside cross-vendor branches -> both tiers definitive False,
        note absent. Confirms the per-tier flags don't leak into each
        other or get OR'd together incorrectly."""
        min_alts = [_nvidia("GTX 1060 6GB", 50), _amd("RX 580 8GB", 50)]
        rec_alts = [_nvidia("RTX 2060", 60), _intel("Arc A750", 55), _amd("RX 5700 XT", 60)]

        def fake_resolve(text):
            if text == "MIN":
                return min_alts
            if text == "REC":
                return rec_alts
            return []

        with patch("services.hardware.requirement_matching.resolve_gpu_requirement", side_effect=fake_resolve):
            verdict, notes = _evaluate_gpu("MIN", "REC", _user_gpu("AMD", 10))

        self.assertFalse(verdict.meets_minimum)
        self.assertFalse(verdict.meets_recommended)
        self.assertFalse(_has_cross_vendor_note(notes))

    def test_recommended_unknown_while_minimum_definitive_still_notes_correctly(self):
        """Mixed case: minimum resolves definitively (same-vendor FAIL),
        recommended has ONLY cross-vendor alternatives (genuinely
        unknown) -> note should appear (driven by recommended tier),
        minimum stays False, recommended stays None."""
        min_alts = [_amd("RX 580 8GB", 50)]
        rec_alts = [_nvidia("RTX 2060", 60), _intel("Arc A750", 55)]

        def fake_resolve(text):
            if text == "MIN":
                return min_alts
            if text == "REC":
                return rec_alts
            return []

        with patch("services.hardware.requirement_matching.resolve_gpu_requirement", side_effect=fake_resolve):
            verdict, notes = _evaluate_gpu("MIN", "REC", _user_gpu("AMD", 10))

        self.assertFalse(verdict.meets_minimum)
        self.assertIsNone(verdict.meets_recommended)
        self.assertTrue(_has_cross_vendor_note(notes))


if __name__ == "__main__":
    unittest.main()
