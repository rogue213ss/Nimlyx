"""
Focused test suite for backend/services/hardware/requirement_matching.py.

Covers the specific naming-variant / abbreviation cases raised in the
"compatibility matching bug" report: clock-speed suffixes, VRAM
suffixes, slash-separated alternatives, vendor/brand abbreviations
(GTX <-> GeForce GTX, RX480 <-> Radeon RX 480, etc.), and -- just as
important -- confirms genuinely ambiguous or genuinely-absent-from-
the-catalog inputs are NOT force-matched. The matcher's core contract
is "never guess"; roughly half of this file exists to prove that
contract still holds after the normalization improvements, not just
that the improvements work.

Run with:
    python -m unittest backend.tests.test_requirement_matching -v
(from the repo root, with the backend's normal dependencies
installed) or via pytest if it's available -- no pytest-only features
are used, so either runner works.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.hardware.requirement_matching import (  # noqa: E402
    clear_catalog_cache,
    resolve_cpu_requirement,
    resolve_gpu_requirement,
    split_alternatives,
)


def _names(alts):
    return [a.name for a in alts]


def _all_resolved(alts):
    return all(a.resolved for a in alts)


def _any_resolved(alts):
    return any(a.resolved for a in alts)


class RequirementMatchingTestCase(unittest.TestCase):
    def setUp(self):
        # Each test gets a clean catalog-index cache so nothing
        # leaks state between cases.
        clear_catalog_cache()


class TestCpuNamingVariants(RequirementMatchingTestCase):
    """CPUs that ARE present in the catalog, phrased the way Steam's
    free-text requirements actually phrase them (clock-speed suffix,
    comma-separated alternatives)."""

    def test_i5_2400s_with_clock_suffix(self):
        alts = resolve_cpu_requirement("Intel Core i5-2400S @ 2.5 GHz")
        self.assertTrue(_any_resolved(alts))
        self.assertIn("Intel Core i5-2400S", _names(alts))

    def test_i7_3770_with_clock_suffix_resolves(self):
        alts = resolve_cpu_requirement("Intel Core i7-3770 @ 3.5 GHz")
        self.assertTrue(_any_resolved(alts))
        self.assertIn("Intel Core i7-3770", _names(alts))

    def test_fx_4320_resolves(self):
        alts = resolve_cpu_requirement("AMD FX-4320 @ 4 GHz")
        self.assertTrue(_any_resolved(alts))
        self.assertIn("AMD FX-4320", _names(alts))

    def test_fx_8350_resolves(self):
        alts = resolve_cpu_requirement("AMD FX-8350 @ 4 GHz")
        self.assertTrue(_any_resolved(alts))
        self.assertIn("AMD FX-8350", _names(alts))

    def test_comma_separated_cpu_alternatives_both_evaluated(self):
        # "X @ N GHz, Y @ N GHz" -- comma is an alternative
        # separator here, not a mid-name character. Both sides of
        # this particular pair are now in the catalog (see
        # test_fx_8350_resolves above), so this now confirms both
        # resolve independently rather than "one resolves, one
        # doesn't" -- the actually-important thing this test is
        # guarding (the comma is correctly parsed as a separator,
        # not swallowed into either CPU's name) still holds either
        # way.
        alts = resolve_cpu_requirement(
            "Intel Core i7-3770 @ 3.5 GHz, AMD FX-8350 @ 4 GHz"
        )
        self.assertEqual(len(alts), 2)
        self.assertTrue(alts[0].resolved)
        self.assertEqual(alts[0].name, "Intel Core i7-3770")
        self.assertTrue(alts[1].resolved)
        self.assertEqual(alts[1].name, "AMD FX-8350")


class TestGpuNamingVariants(RequirementMatchingTestCase):
    def test_gtx_660_with_vram_suffix(self):
        alts = resolve_gpu_requirement("NVIDIA GeForce GTX 660 2GB")
        self.assertTrue(_any_resolved(alts))
        self.assertIn("GeForce GTX 660", _names(alts))

    def test_gtx_970_bare(self):
        alts = resolve_gpu_requirement("NVIDIA GeForce GTX 970")
        self.assertTrue(_any_resolved(alts))

    def test_r9_390_company_name_only(self):
        # Catalog stores this as "Radeon R9 390" -- "AMD R9 390" must
        # still match despite using the company name instead of the
        # brand name.
        alts = resolve_gpu_requirement("AMD R9 390")
        self.assertTrue(_any_resolved(alts))
        self.assertIn("Radeon R9 390", _names(alts))

    def test_rx480_no_space_no_brand(self):
        alts = resolve_gpu_requirement("RX480")
        self.assertTrue(_any_resolved(alts))
        self.assertIn("Radeon RX 480", _names(alts))

    def test_amd_rx480_company_name_no_space(self):
        alts = resolve_gpu_requirement("AMD RX480")
        self.assertTrue(_any_resolved(alts))
        self.assertIn("Radeon RX 480", _names(alts))

    def test_rx_5600_xt_with_spaces(self):
        alts = resolve_gpu_requirement("RX 5600 XT")
        self.assertTrue(_any_resolved(alts))
        self.assertIn("Radeon RX 5600 XT", _names(alts))

    def test_rx5600xt_no_spaces(self):
        alts = resolve_gpu_requirement("RX5600XT")
        self.assertTrue(_any_resolved(alts))
        self.assertIn("Radeon RX 5600 XT", _names(alts))

    def test_rtx_5050_bare(self):
        alts = resolve_gpu_requirement("RTX 5050")
        self.assertTrue(_any_resolved(alts))
        self.assertIn("GeForce RTX 5050", _names(alts))

    def test_rtx5050_no_space(self):
        alts = resolve_gpu_requirement("RTX5050")
        self.assertTrue(_any_resolved(alts))
        self.assertIn("GeForce RTX 5050", _names(alts))

    def test_r9_270x_desktop_absent_from_catalog(self):
        # The catalog only has "Radeon R9 M270X" (a MOBILE chip --
        # genuinely different silicon, not a naming variant of the
        # desktop R9 270X). Must NOT collapse "M270X" and "270X"
        # together; that would be exactly the kind of "close enough"
        # guess principle #5 forbids.
        alts = resolve_gpu_requirement("AMD Radeon R9 270X 2GB")
        self.assertFalse(_any_resolved(alts))

    def test_hd_graphics_630_intel_prefix(self):
        alts = resolve_gpu_requirement("Intel HD Graphics 630")
        self.assertTrue(_any_resolved(alts))
        self.assertIn("HD Graphics 630", _names(alts))

    def test_uhd_graphics_630_distinct_from_hd(self):
        # HD Graphics 630 and UHD Graphics 630 are different chips,
        # not formatting variants of one another -- confirms the
        # matcher keeps them separate.
        alts = resolve_gpu_requirement("Intel UHD Graphics 630")
        self.assertTrue(_any_resolved(alts))
        self.assertIn("UHD Graphics 630", _names(alts))
        self.assertNotIn("HD Graphics 630", _names(alts))


class TestSlashAndComplexSplitting(RequirementMatchingTestCase):
    def test_slash_separated_nvidia_pair(self):
        parts = split_alternatives("NVIDIA GeForce GTX 970/GTX 1060")
        self.assertEqual(parts, ["NVIDIA GeForce GTX 970", "GTX 1060"])

    def test_slash_separated_amd_pair_no_space(self):
        parts = split_alternatives("AMD R9 390/RX480")
        self.assertEqual(parts, ["AMD R9 390", "RX480"])

    def test_full_recommended_gpu_string(self):
        # The exact string from the bug report -- comma AND slash AND
        # a parenthetical spec annotation together.
        text = "NVIDIA GeForce GTX 970/GTX 1060, AMD R9 390/RX480 (4GB VRAM with Shader Model 5.0, better)"
        parts = split_alternatives(text)
        self.assertEqual(
            parts,
            ["NVIDIA GeForce GTX 970", "GTX 1060", "AMD R9 390", "RX480"],
        )
        alts = resolve_gpu_requirement(text)
        resolved_names = {a.name for a in alts if a.resolved}
        self.assertEqual(
            resolved_names, {"GeForce GTX 970", "Radeon R9 390", "Radeon RX 480"}
        )
        # GTX 1060 alone is genuinely ambiguous in the catalog (10
        # distinct VRAM/revision SKUs) and must stay unresolved.
        gtx_1060_alt = next(a for a in alts if a.raw_text == "GTX 1060")
        self.assertFalse(gtx_1060_alt.resolved)


class TestAmbiguousAndInvalidInputsNeverGuess(RequirementMatchingTestCase):
    """Principle 5/6: never select a 'close enough' different model,
    never fuzzy-match a bare number. These MUST all fail to resolve."""

    def test_bare_number_5050_does_not_resolve(self):
        alts = resolve_gpu_requirement("5050")
        self.assertFalse(_any_resolved(alts))

    def test_bare_number_5600_does_not_resolve(self):
        alts = resolve_gpu_requirement("5600")
        self.assertFalse(_any_resolved(alts))

    def test_bare_brand_word_rtx_does_not_resolve(self):
        alts = resolve_gpu_requirement("RTX")
        self.assertFalse(_any_resolved(alts))

    def test_bare_brand_word_radeon_does_not_resolve(self):
        alts = resolve_gpu_requirement("Radeon")
        self.assertFalse(_any_resolved(alts))

    def test_incomplete_cpu_family_does_not_resolve(self):
        alts = resolve_cpu_requirement("Intel Core i5")
        self.assertFalse(_any_resolved(alts))

    def test_nonexistent_hardware_does_not_resolve(self):
        alts = resolve_gpu_requirement("Nimlyx Fictional GPU 9999")
        self.assertFalse(_any_resolved(alts))
        alts_cpu = resolve_cpu_requirement("Totally Made Up CPU X1")
        self.assertFalse(_any_resolved(alts_cpu))

    def test_ambiguous_gtx_1060_never_guesses_a_sku(self):
        # 10 distinct catalog SKUs (3GB/5GB/6GB/Mobile/Max-Q/revisions)
        # collapse to the same normalized key -- must return
        # unresolved, not an arbitrary pick.
        for query in ("GTX 1060", "GTX1060", "NVIDIA GeForce GTX 1060"):
            alts = resolve_gpu_requirement(query)
            self.assertFalse(
                _any_resolved(alts), f"{query!r} should NOT resolve (genuinely ambiguous)"
            )


class TestNeverInventOrEmptyInput(RequirementMatchingTestCase):
    def test_empty_string(self):
        self.assertEqual(split_alternatives(""), [])
        self.assertEqual(resolve_cpu_requirement(""), [])
        self.assertEqual(resolve_gpu_requirement(""), [])

    def test_none_input(self):
        self.assertEqual(split_alternatives(None), [])


if __name__ == "__main__":
    unittest.main()
