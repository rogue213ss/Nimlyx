"""
Test suite for backend/services/hardware/potato_classifier.py.

Covers:
  - genuinely easy Potato games returning None here (they should have
    already been caught by the strict Potato Friendly check upstream,
    so this module correctly has nothing to add for them)
  - reasonable "sensible tweaks" games landing in the Tweaks tier
  - the Dying Light regression/validation case landing in Extreme
    Tweaks via the engine-undersells-its-minimum rule
  - a genuinely-too-demanding game (The Witcher 3-shaped requirement)
    being excluded from the Potato ecosystem entirely
  - a game with no resolvable GPU signal being excluded rather than
    guessed into a tier
  - old Intel HD 4400-era CPU/GPU requirement text resolving cleanly
    against the potato reference profile

Run with:
    python -m pytest backend/tests/test_potato_classifier.py -v
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.hardware.potato_classifier import (  # noqa: E402
    classify_potato_tier,
    POTATO_CPU_SCORE,
    POTATO_GPU_SCORE,
)


def _reqs(min_cpu="", min_gpu="", min_ram="", rec_cpu="", rec_gpu="", rec_ram=""):
    return {
        "minimum": {"cpu": min_cpu, "gpu": min_gpu, "ram": min_ram},
        "recommended": {"cpu": rec_cpu, "gpu": rec_gpu, "ram": rec_ram},
    }


class TestReferenceProfileResolves(unittest.TestCase):
    """The potato reference scores must actually resolve from the
    ranking catalog -- if these are None, every other test in this
    file would pass for the wrong reason (silently short-circuiting to
    None everywhere)."""

    def test_potato_gpu_score_resolves(self):
        self.assertIsNotNone(POTATO_GPU_SCORE)
        self.assertGreater(POTATO_GPU_SCORE, 0)

    def test_potato_cpu_score_resolves(self):
        self.assertIsNotNone(POTATO_CPU_SCORE)
        self.assertGreater(POTATO_CPU_SCORE, 0)


class TestEasyPotatoGamesLandInFriendly(unittest.TestCase):
    """A requirement already at/below the potato GPU/CPU/RAM level
    should classify as 🥔 Friendly -- this module is now the single
    source of truth for all three tiers, including Friendly."""

    def test_gpu_requirement_at_or_below_potato_level(self):
        # NVIDIA 9800 GT is well below the HD 4400's compute score,
        # and the CPU/RAM ask here is also comfortably at potato level.
        reqs = _reqs(min_cpu="Intel Core i3-4130", min_gpu="NVIDIA 9800 GT", min_ram="4 GB RAM")
        self.assertEqual(classify_potato_tier(reqs), "friendly")


class TestSensibleTweaksTier(unittest.TestCase):
    """A moderate GPU gap (roughly 1x-1.6x the potato GPU score), with
    a minimum->recommended climb that ISN'T dramatic, should land in
    Potato + Tweaks -- the 'sensible settings reduction' band. Uses
    Watch Dogs (2014)'s real, verified minimum/recommended spec: GTX
    460 minimum (~1.23x the potato GPU score) escalating only to a
    GTX 560 Ti recommended (~1.72x) -- a mild, not steep, climb."""

    def test_watch_dogs_2014_lands_in_tweaks(self):
        reqs = _reqs(
            min_cpu="Intel Core 2 Quad Q8400", min_gpu="NVIDIA GeForce GTX 460", min_ram="6 GB RAM",
            rec_cpu="Intel Core i7-3770", rec_gpu="NVIDIA GeForce GTX 560 Ti", rec_ram="8 GB RAM",
        )
        self.assertEqual(classify_potato_tier(reqs), "tweaks")


class TestDyingLightValidationCase(unittest.TestCase):
    """Explicit regression case per the task: Dying Light's real
    minimum/recommended requirement text must land in Extreme Tweaks,
    not be silently excluded and not be mistaken for a comfortable
    Potato + Tweaks title. This is the 'official minimum says no, but
    real low-end testing says it actually works' case the Extreme tier
    exists to capture."""

    def test_dying_light_lands_in_extreme_tweaks(self):
        reqs = _reqs(
            min_cpu="Intel Core i5-2500", min_gpu="NVIDIA GeForce GTX 460", min_ram="4 GB RAM",
            rec_cpu="Intel Core i7-3770", rec_gpu="NVIDIA GeForce GTX 670", rec_ram="8 GB RAM",
        )
        self.assertEqual(classify_potato_tier(reqs), "extreme")

    def test_skyrim_special_edition_lands_in_extreme_tweaks(self):
        """Second real-world validation case for the same
        engine-undersells-its-minimum pattern: Skyrim Special
        Edition's official minimum GPU (GTX 470, ~1.48x) is Tweaks-
        range on its own, but its recommended GPU (GTX 780, ~11.3x)
        escalates so steeply that it's promoted to Extreme."""
        reqs = _reqs(
            min_cpu="Intel Core i5-750", min_gpu="NVIDIA GeForce GTX 470", min_ram="8 GB RAM",
            rec_cpu="Intel Core i5-2400", rec_gpu="NVIDIA GeForce GTX 780", rec_ram="8 GB RAM",
        )
        self.assertEqual(classify_potato_tier(reqs), "extreme")

    def test_fallout_4_lands_in_extreme_tweaks(self):
        """Third real-world validation case: Fallout 4's minimum GPU
        (GTX 550 Ti) is actually AT potato level (~0.94x -- would be
        Friendly on GPU alone), but its recommended GPU (GTX 780,
        ~11.3x) escalates so steeply it's still promoted to Extreme --
        matches Fallout 4's real-world reputation for punishing
        low-end iGPUs despite a deceptively modest official minimum."""
        reqs = _reqs(
            min_cpu="Intel Core i5-2300", min_gpu="NVIDIA GeForce GTX 550 Ti", min_ram="8 GB RAM",
            rec_cpu="Intel Core i7-4790", rec_gpu="NVIDIA GeForce GTX 780", rec_ram="8 GB RAM",
        )
        self.assertEqual(classify_potato_tier(reqs), "extreme")


class TestExtremeOutlierWithoutEngineMismatch(unittest.TestCase):
    """A game that lands directly in the Extreme GPU band (1.6x-4.0x)
    on its own minimum spec, without needing the engine-undersells
    rule, should still classify as Extreme. (Synthetic figures here --
    picked to land cleanly inside the band -- rather than a specific
    researched title, to isolate this path from the promotion rule.)"""

    def test_gpu_gap_in_extreme_band_without_recommended_escalation(self):
        # GTX 560 (~1.48x) alone would be Tweaks, so use a GPU whose
        # minimum score itself sits past the Tweaks ceiling but still
        # under the Extreme ceiling: GTX 750 Ti (~3.77x).
        reqs = _reqs(
            min_cpu="Intel Core i3-4130", min_gpu="NVIDIA GeForce GTX 750 Ti", min_ram="8 GB RAM",
            rec_cpu="Intel Core i5-4460", rec_gpu="NVIDIA GeForce GTX 750 Ti", rec_ram="8 GB RAM",
        )
        self.assertEqual(classify_potato_tier(reqs), "extreme")


class TestGenuinelyImpossibleGamesAreExcluded(unittest.TestCase):
    """A Witcher-3-shaped requirement (minimum GPU roughly 5.4x the
    potato GPU score) sits past the Extreme ceiling and must be
    excluded from the Potato ecosystem entirely -- not stretched into
    Extreme Tweaks just because it has SOME headroom."""

    def test_gpu_gap_past_extreme_ceiling_is_excluded(self):
        reqs = _reqs(
            min_cpu="Intel Core i5-2500K", min_gpu="NVIDIA GeForce GTX 660", min_ram="6 GB RAM",
            rec_cpu="Intel Core i7-3770", rec_gpu="NVIDIA GeForce GTX 770", rec_ram="8 GB RAM",
        )
        self.assertIsNone(classify_potato_tier(reqs))

    def test_just_cause_3_real_spec_is_excluded(self):
        """Just Cause 3's real, verified minimum GPU (GTX 670, ~7.2x
        the potato GPU score) is well past the Extreme ceiling on its
        own -- confirms a demanding-but-real AAA title isn't stretched
        into Extreme just because Dying Light-style outliers exist."""
        reqs = _reqs(
            min_cpu="Intel Core i5-2500K", min_gpu="NVIDIA GeForce GTX 670", min_ram="6 GB RAM",
            rec_cpu="Intel Core i7-3770", rec_gpu="NVIDIA GeForce GTX 780", rec_ram="8 GB RAM",
        )
        self.assertIsNone(classify_potato_tier(reqs))

    def test_excessive_ram_requirement_excludes_even_with_ok_gpu(self):
        reqs = _reqs(
            min_cpu="Intel Core i3-4130", min_gpu="NVIDIA GeForce GTX 750 Ti", min_ram="32 GB RAM",
        )
        self.assertIsNone(classify_potato_tier(reqs))

    def test_excessive_cpu_requirement_excludes_even_with_ok_gpu(self):
        # Extreme CPU ceiling is 2.5x potato CPU score (~5,376) -- an
        # 8-core/16-thread high-end CPU comfortably clears that.
        reqs = _reqs(
            min_cpu="Intel Core i9-9900K", min_gpu="NVIDIA GeForce GTX 750 Ti", min_ram="8 GB RAM",
        )
        self.assertIsNone(classify_potato_tier(reqs))


class TestCrossVendorGpuIsNotWavedThroughOnCpuRamAlone(unittest.TestCase):
    """Regression case for the bug a cross-vendor validation matrix
    exposed: a game whose minimum GPU is AMD/Nvidia (cross-vendor to
    the potato profile's Intel iGPU) must NOT reach 🥔 Friendly purely
    because its CPU/RAM numbers look fine. Before the unified model,
    `evaluate_compatibility()`'s cross-vendor GPU result of `None`
    (unknown) was treated as "no evidence against it" and a game
    requiring a GPU ~5x more powerful than the potato GPU could slip
    through on CPU+RAM alone."""

    def test_far_stronger_cross_vendor_gpu_is_not_friendly(self):
        # Radeon R7 260X: compute_capability_score ~5.4x the potato
        # GPU's -- comfortably reasonable CPU/RAM should NOT be enough
        # to call this Friendly.
        reqs = _reqs(min_cpu="Intel Core i3-3220", min_gpu="AMD Radeon R7 260X", min_ram="4 GB RAM")
        self.assertNotEqual(classify_potato_tier(reqs), "friendly")


class TestNoResolvableGpuSignalIsExcludedNotGuessed(unittest.TestCase):
    """A requirement whose GPU text doesn't resolve against the
    catalog at all must be excluded, never defaulted into a tier --
    matches the 'never guess' contract the rest of this codebase
    already follows."""

    def test_unresolvable_gpu_text_returns_none(self):
        reqs = _reqs(min_cpu="Intel Core i5-2500", min_gpu="Some Totally Made Up GPU 9999", min_ram="4 GB RAM")
        self.assertIsNone(classify_potato_tier(reqs))

    def test_missing_gpu_requirement_returns_none(self):
        reqs = _reqs(min_cpu="Intel Core i5-2500", min_gpu="", min_ram="4 GB RAM")
        self.assertIsNone(classify_potato_tier(reqs))


class TestOldIntelIntegratedHardwareResolves(unittest.TestCase):
    """Sanity check that genuinely old Intel HD 4400-era requirement
    text (a game explicitly listing an old integrated GPU as its own
    minimum) resolves cleanly and doesn't crash the ratio math -- such
    a requirement is exactly at potato level (ratio == 1.0), which
    should land in 🥔 Friendly."""

    def test_hd_4400_as_the_games_own_minimum_gpu(self):
        reqs = _reqs(min_cpu="Intel Core i3-4130", min_gpu="Intel HD Graphics 4400", min_ram="4 GB RAM")
        self.assertEqual(classify_potato_tier(reqs), "friendly")


if __name__ == "__main__":
    unittest.main()
