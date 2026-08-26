"""
Validation/regression tests for the Potato ecosystem RESEARCH pass
(see docs/potato_research_matrix.md for the full matrix and method).

These are NOT synthetic figures -- every requirement string below is
each game's real, officially published Steam minimum/recommended
spec, gathered and cross-checked via web search against Steam store
pages / official requirement announcements. They exist to VALIDATE
the existing generalized, ratio-based classifier
(services/hardware/potato_classifier.py) against a wider, real-world
sample -- nothing in that module was changed to make these pass, and
no game name appears anywhere in the classifier itself.

Covers the deliverable's required regression list:
  🥔 Friendly:  Portal 2, GTA V
  🔧 Tweaks:    (Watch Dogs already covered in test_potato_classifier.py)
  💀 Extreme:   Dark Souls III, Dragon Age: Inquisition
                (Dying Light / Fallout 4 / Skyrim SE already covered)
  ❌ Excluded:  The Witcher 3, Cyberpunk 2077, Red Dead Redemption 2
                (Just Cause 3 already covered)

Plus two real model-limitation findings surfaced by this research pass
(see module docstrings below and the matrix doc) -- Stardew Valley and
Left 4 Dead 2 both correctly stay excluded today, for two DIFFERENT
"never guess" reasons. These are asserted as regression tests so a
future change to the classifier can't silently start guessing.

Run with:
    python -m pytest backend/tests/test_potato_ecosystem_research.py -v
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.hardware.potato_classifier import classify_potato_tier  # noqa: E402


def _reqs(min_cpu="", min_gpu="", min_ram="", rec_cpu="", rec_gpu="", rec_ram=""):
    return {
        "minimum": {"cpu": min_cpu, "gpu": min_gpu, "ram": min_ram},
        "recommended": {"cpu": rec_cpu, "gpu": rec_gpu, "ram": rec_ram},
    }


class TestRealFriendlyCandidates(unittest.TestCase):
    """Real, officially published minimum specs that land in 🥔 Friendly."""

    def test_portal_2_real_spec_is_friendly(self):
        """Portal 2's official minimum spec explicitly lists Intel HD
        Graphics 2000 as an acceptable GPU alongside period Nvidia/ATI
        cards -- that Intel iGPU floor resolves well below the potato
        GPU's (HD 4400) score, landing cleanly in Friendly."""
        reqs = _reqs(
            min_cpu="3.0 GHz P4, Dual Core 2.0 or AMD64X2",
            min_gpu="Intel HD Graphics 2000",
            min_ram="2 GB RAM",
        )
        self.assertEqual(classify_potato_tier(reqs), "friendly")

    def test_gta_v_real_spec_is_friendly(self):
        """GTA V's official minimum GPU (NVIDIA 9800 GT) is well below
        the potato GPU's score -- confirms a genuinely low-end-capable
        modern-ish AAA title lands in Friendly without any special
        case, matching its real-world reputation as scaling down well.
        (Its recommended GPU, GTX 660, is a much steeper ~5.4x jump --
        but the 'engine undersells its minimum' promotion rule only
        applies to games that start in the Tweaks band; a game already
        at Friendly on its own minimum is not moved by how much higher
        the recommended spec climbs. See the research matrix doc for
        why that's judged correct here rather than a gap to close.)"""
        reqs = _reqs(
            min_cpu="Intel Core 2 Quad CPU Q6600", min_gpu="NVIDIA 9800 GT", min_ram="4 GB RAM",
            rec_cpu="Intel Core i5 3470", rec_gpu="NVIDIA GTX 660", rec_ram="8 GB RAM",
        )
        self.assertEqual(classify_potato_tier(reqs), "friendly")


class TestRealExtremeCandidates(unittest.TestCase):
    """Real, officially published specs that land in 💀 Extreme --
    validation cases beyond the three already covered in
    test_potato_classifier.py (Dying Light, Skyrim SE, Fallout 4)."""

    def test_dark_souls_iii_real_spec_is_extreme(self):
        """Dark Souls III's official minimum GPU (GTX 750 Ti, ~3.77x
        the potato GPU score) sits directly in the Extreme band on its
        own -- no promotion rule needed -- and its recommended GPU
        (GTX 970, ~10.7x) escalates even further, consistent with its
        real-world reputation as one of the more demanding From
        Software ports on integrated graphics."""
        reqs = _reqs(
            min_cpu="Intel Core i3-2100", min_gpu="NVIDIA GeForce GTX 750 Ti", min_ram="4 GB RAM",
            rec_cpu="Intel Core i7-3770", rec_gpu="NVIDIA GeForce GTX 970", rec_ram="8 GB RAM",
        )
        self.assertEqual(classify_potato_tier(reqs), "extreme")

    def test_dragon_age_inquisition_real_spec_is_extreme(self):
        """Interesting real-world case: Dragon Age: Inquisition's
        minimum GPU (an 8800 GT-class card) is actually AT Friendly
        level on its own (~0.37x), but its minimum CPU requirement
        (quad-core, ~1.19x the potato CPU score) pushes the overall
        level to Tweaks -- and from there, the same steep min-to-
        recommended GPU climb (~5.4x) that promotes Dying Light-shaped
        games promotes this one too. Confirms the 'engine undersells
        its minimum' rule generalizes even when the level-1 trigger
        comes from the CPU axis rather than GPU, matching Frostbite's
        real-world reputation for being CPU-heavy and punishing on
        integrated graphics despite a deceptively old official
        minimum GPU.

        Bioware's own spec text names the CPU only generically
        ("Intel quad-core CPU @ 2.0 GHz" / "@ 3.0 GHz"), which doesn't
        resolve to a specific catalog model -- so, as the requirement-
        matching module already does elsewhere in this codebase for
        generic requirement text, a concrete same-era quad-core stand-
        in (i5-750 min / i5-4670 rec) is used here to get a real ratio
        rather than leaving cpu_min_ratio unresolved and understating
        the case."""
        reqs = _reqs(
            min_cpu="Intel Core i5-750", min_gpu="NVIDIA GeForce 8800 GT", min_ram="4 GB RAM",
            rec_cpu="Intel Core i5-4670", rec_gpu="NVIDIA GeForce GTX 660", rec_ram="8 GB RAM",
        )
        self.assertEqual(classify_potato_tier(reqs), "extreme")


class TestRealExclusionBoundaryCandidates(unittest.TestCase):
    """Real, officially published specs that must be excluded entirely
    -- these establish where Extreme ends, per the task's exclusion-
    boundary requirement. Just Cause 3 is already covered in
    test_potato_classifier.py; these three extend that boundary."""

    def test_the_witcher_3_real_spec_is_excluded(self):
        reqs = _reqs(
            min_cpu="Intel Core i5-2500K", min_gpu="NVIDIA GeForce GTX 660", min_ram="6 GB RAM",
            rec_cpu="Intel Core i7-3770", rec_gpu="NVIDIA GeForce GTX 770", rec_ram="8 GB RAM",
        )
        self.assertIsNone(classify_potato_tier(reqs))

    def test_cyberpunk_2077_real_spec_is_excluded(self):
        reqs = _reqs(
            min_cpu="Intel Core i5-3570K", min_gpu="NVIDIA GeForce GTX 780", min_ram="8 GB RAM",
            rec_cpu="Intel Core i7-4790", rec_gpu="NVIDIA GeForce GTX 1060", rec_ram="12 GB RAM",
        )
        self.assertIsNone(classify_potato_tier(reqs))

    def test_red_dead_redemption_2_real_spec_is_excluded(self):
        reqs = _reqs(
            min_cpu="Intel Core i5-2500K", min_gpu="NVIDIA GeForce GTX 770", min_ram="8 GB RAM",
            rec_cpu="Intel Core i7-4770K", rec_gpu="NVIDIA GeForce GTX 1060", rec_ram="12 GB RAM",
        )
        self.assertIsNone(classify_potato_tier(reqs))


class TestFarCry4RealSpecEscalatesToExtremeNotTweaks(unittest.TestCase):
    """Far Cry 4 was on both the 'Tweaks' and 'Extreme' research lists
    for this pass -- its real, published spec resolves that ambiguity
    rather than a person guessing. Minimum GPU (GTX 460, ~1.23x) alone
    would be Tweaks -- identical to Watch Dogs (2014)'s real minimum
    -- but Far Cry 4's recommended GPU (GTX 680, ~8.8x) escalates far
    more steeply than Watch Dogs' mild GTX 460 -> GTX 560 Ti climb,
    triggering the same 'engine undersells its minimum' promotion rule
    validated on Dying Light/Skyrim SE/Fallout 4. This is presented as
    a finding, not a threshold change: the existing rule already
    produces the evidence-backed answer without modification."""

    def test_far_cry_4_real_spec_is_extreme_not_tweaks(self):
        reqs = _reqs(
            min_cpu="Intel Core i5-750", min_gpu="NVIDIA GeForce GTX 460", min_ram="4 GB RAM",
            rec_cpu="Intel Core i5-2400S", rec_gpu="NVIDIA GeForce GTX 680", rec_ram="8 GB RAM",
        )
        self.assertEqual(classify_potato_tier(reqs), "extreme")


class TestModelLimitationsFoundDuringResearch(unittest.TestCase):
    """Two real candidates from the research pool that stay excluded
    today for two DIFFERENT 'never guess' reasons -- documented here
    as regression tests (not bugs to fix) so a future change can't
    silently start guessing at either kind of missing evidence. See
    docs/potato_research_matrix.md for the full writeup."""

    def test_stardew_valley_has_no_gpu_model_to_resolve(self):
        """Stardew Valley's official minimum spec never names a GPU at
        all ('256 MB video memory, shader model 3.0+') -- there is no
        card name for resolve_gpu_requirement() to match against, so
        gpu_min_ratio is None and the game is excluded, even though
        real-world consensus is that it runs on essentially anything.
        This is the correct behavior given the module's 'GPU evidence
        is mandatory' contract -- the alternative would be guessing a
        tier for a game with zero real GPU signal, which is exactly
        what this module exists to avoid. A future improvement could
        treat a GPU-less minimum spec as an explicit Friendly signal
        (very low requirements historically don't bother naming a
        card), but that would be a new, deliberate rule -- not a
        threshold tweak -- and is out of scope for this research pass."""
        reqs = _reqs(min_cpu="2 GHz", min_gpu="", min_ram="2 GB RAM")
        self.assertIsNone(classify_potato_tier(reqs))

    def test_left_4_dead_2_gpu_resolves_without_a_usable_score(self):
        """Left 4 Dead 2's official minimum GPU (NVIDIA GeForce 6600)
        IS recognized by the hardware catalog's alias matching, but
        that catalog entry has no compute_capability_score attached
        (too old to carry a modern benchmark figure) -- so it's
        correctly treated the same as 'unresolved' for ratio purposes
        rather than silently defaulting to some assumed score. Same
        'never guess' contract as the Stardew Valley case above, via a
        different path (present-but-scoreless vs. absent-entirely)."""
        reqs = _reqs(min_cpu="Pentium 4 3.0GHz", min_gpu="NVIDIA GeForce 6600", min_ram="2 GB RAM")
        self.assertIsNone(classify_potato_tier(reqs))


if __name__ == "__main__":
    unittest.main()
