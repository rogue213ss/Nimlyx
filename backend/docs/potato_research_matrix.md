# Potato Ecosystem — Research & Validation Matrix

**Scope of this pass:** validate and calibrate the existing generalized
classifier (`services/hardware/potato_classifier.py`) against a wider
real-world candidate pool. **No code changes were made to the
classifier, its thresholds, or the Potato reference hardware.** Every
result below comes from running each game's real, officially published
Steam minimum/recommended requirement text through the unchanged model.

Reference hardware (unchanged):
CPU `Intel Core i3-4130` · GPU `Intel HD Graphics 4400` · RAM `8 GB`

Bands (unchanged): Friendly = ratio ≤ 1.0 · Tweaks ≤ 1.6x (GPU/CPU) or
≤ 12 GB (RAM) · Extreme ≤ 4.0x (GPU) / 2.5x (CPU) / 16 GB (RAM), or
promoted from Tweaks when the recommended GPU escalates ≥ 3.0x past
minimum · beyond that → excluded.

## How this matrix was built

For each game: pulled the **official** Steam-page minimum/recommended
spec text (via web search of Steam community threads quoting the store
page, official requirement-announcement articles, or reseller pages
mirroring the Steam listing verbatim), then ran that exact text through
`classify_potato_tier()` unmodified — no hand-tuning per game. Where
useful, this doc also notes independent real-world low-end/iGPU
testing that corroborates or contextualizes the model's verdict, but
**the classification itself comes from the ratio model, not from
manually deciding "this looks Extreme."**

## Results

| Game | Official Min GPU | Min GPU ratio | Rec GPU ratio | Model Tier | Notes |
|---|---|---|---|---|---|
| Stardew Valley | *(none named — "256MB VRAM, shader model 3.0+")* | n/a | n/a | **Excluded** | No GPU model to resolve at all → "GPU evidence mandatory" rule excludes it, despite near-universal real-world consensus it runs on anything. Model limitation, documented as a regression test, not patched (see below). |
| Portal 2 | Intel HD Graphics 2000 (or GeForce 7600 / Radeon X800) | 0.26x | n/a | **🥔 Friendly** | Official spec explicitly names an old Intel iGPU as sufficient. |
| Left 4 Dead 2 | NVIDIA GeForce 6600 | unresolved (no score) | n/a | **Excluded** | Catalog recognizes the card by name but has no benchmark score old enough to attach — correctly treated as no-evidence rather than guessed. |
| GTA V | NVIDIA 9800 GT | 0.37x | 5.38x | **🥔 Friendly** | Min GPU well below potato level. Recommended escalates steeply, but the "engine undersells minimum" promotion only fires for games that start in the Tweaks band — a game already at Friendly isn't moved by it. Matches GTA V's real reputation for scaling down well. |
| Watch Dogs (2014) | GTX 460 | 1.23x | 1.72x (mild) | **🔧 Tweaks** | Already covered by an existing regression test; included here for matrix completeness. |
| Far Cry 4 | GTX 460 | 1.23x | 8.83x (steep) | **💀 Extreme** | Same minimum GPU as Watch Dogs, but the recommended spec escalates far more steeply (GTX 460 → GTX 680), triggering the same promotion rule validated on Dying Light. This resolves the ambiguity in the original candidate list (Far Cry 4 was listed under *both* Tweaks and Extreme) — the real spec puts it in Extreme. |
| Dying Light | GTX 460 | 1.23x | 7.2x | **💀 Extreme** | Already covered by an existing regression test. |
| Skyrim Special Edition | GTX 470 | 1.48x | 11.3x | **💀 Extreme** | Already covered. |
| Fallout 4 | GTX 550 Ti | 0.94x | 11.3x | **💀 Extreme** | Already covered — note min GPU alone is Friendly-range, promoted purely by the steep recommended climb. |
| Dark Souls III | GTX 750 Ti | 3.77x | 10.65x | **💀 Extreme** | Min GPU alone already sits in the Extreme band — no promotion rule needed. |
| Dragon Age: Inquisition | 8800 GT (CPU: generic quad-core 2.0GHz, treated as ~i5-750-equivalent) | 0.37x (GPU) / 1.19x (CPU) | 5.38x (GPU) | **💀 Extreme** | Interesting case: GPU alone would be Friendly, but the CPU requirement (quad-core) pushes the overall level to Tweaks, and from there the steep GPU min→rec climb promotes it to Extreme — same rule, triggered via a different axis. Matches Frostbite's real reputation as CPU-heavy. |
| Just Cause 3 | GTX 670 | 7.16x | 11.3x | **Excluded** | Already covered by an existing regression test. |
| The Witcher 3 | GTX 660 | 5.38x | 9.06x | **Excluded** | Past the Extreme ceiling on its own minimum. |
| Cyberpunk 2077 | GTX 780 | 11.29x | n/a | **Excluded** | Modern AAA, as expected. |
| Red Dead Redemption 2 | GTX 770 | 9.06x | n/a | **Excluded** | Modern AAA, as expected. |

## Regression test coverage added this pass

`backend/tests/test_potato_ecosystem_research.py` (new):
- 🥔 Friendly: Portal 2, GTA V (real specs)
- 💀 Extreme: Dark Souls III, Dragon Age: Inquisition, Far Cry 4 (real specs)
- ❌ Excluded: The Witcher 3, Cyberpunk 2077, Red Dead Redemption 2 (real specs)
- 2 model-limitation regression tests (see below)

Already covered by the pre-existing `test_potato_classifier.py` and
left untouched: Watch Dogs (Tweaks), Dying Light / Skyrim SE / Fallout 4
(Extreme, via the escalation rule), Just Cause 3 (Excluded).

## Model limitations found (not fixed — documented + regression-tested)

1. **Stardew Valley** — and any game whose official minimum spec never
   names a GPU model at all — is excluded rather than classified,
   because there's nothing for `resolve_gpu_requirement()` to match.
   This is the correct behavior under the module's existing "GPU
   evidence is mandatory, never guess" rule; changing it would mean
   inferring a tier from the *absence* of a requirement, which is a
   new, deliberate rule change, not a threshold tweak, and is
   explicitly out of scope for this pass (see the "do not weaken
   thresholds" constraint). Flagged here for a possible future,
   separate decision.
2. **Left 4 Dead 2** — its official minimum GPU (GeForce 6600) *is*
   recognized by the hardware catalog's alias matching, but that
   catalog entry has no attached `compute_capability_score` (too old
   for the current benchmark dataset), so it's treated the same as
   "unresolved" rather than guessing a score. Same underlying "never
   guess" contract, different failure path (present-but-scoreless vs.
   absent-entirely) — worth knowing they're two distinct gaps if the
   hardware catalog is ever extended to older GPU generations.

Neither of these needed a threshold change to explain — they're both
missing-evidence cases the model already handles safely by excluding
rather than guessing, exactly as the "never fabricate a tier" design
intends.

## Follow-up: candidate SOURCING gap found and fixed

The matrix above validates the *classifier*, but a follow-up check
against the live homepage found that almost none of the validated
💀 Extreme candidates (Dark Souls III, Dragon Age: Inquisition, The
Witcher 3, Skyrim Special Edition) could ever actually appear on the
site — not a classifier problem, a candidate-**sourcing** problem.

`services/hero/potato_pool.py` only scraped Steam's catalog under a
**$10 / $20 permanent price ceiling**. That reliably filters out
today's trending titles (good), but it also filters out almost every
older AAA back-catalog title that's the whole point of the Extreme
tier — Dark Souls III ($59.99), The Witcher 3 (~$39.99), Dragon Age:
Inquisition (~$39.99), and Skyrim Special Edition (~$39.99) all
permanently retail well above $20; only a temporary sale would ever
bring them under that ceiling.

**Fix:** added a third sweep band at **$40**, reusing Discover's own
already-verified `"under-40"` tier from `steam.py`'s
`BUDGET_MAX_PRICE_CENTS` (it existed but potato_pool.py wasn't using
it) — no new price cutoff was invented. `BUDGET_BANDS_CENTS` is now
`(1000, 2000, 4000)`. This does not change the classifier, its
thresholds, or the Potato reference hardware — it only widens which
games are eligible to be evaluated by the unchanged classifier.

Regression coverage: `backend/tests/test_potato_pool_sourcing.py` (6
tests) — confirms all three bands are swept and labeled, a
$40-only game (simulating a Dark Souls III-priced title) is still
included, one band failing doesn't drop the others, and cross-band
dedup still works correctly.

Note: current full-price new releases (>$40, e.g. Cyberpunk 2077 at
$59.99) remain out of this sweep by design — those are correctly
`Excluded` by the classifier anyway (see matrix above) and are the
hero pool's territory, not the budget-leaning Potato pool's.

## Candidates investigated but not included as regression tests

The original candidate pool (~80 games across all four
Friendly/Tweaks/Extreme/Exclusion lists) was reviewed for plausibility
against the validated pattern above, but only the games with a
confidently-sourced *official* Steam minimum/recommended spec were run
through the classifier and turned into regression tests. Games whose
spec text couldn't be confidently pinned down from search results in
this pass (older or console-ported titles with inconsistent Steam-page
mirrors) were left out rather than guessed at, consistent with the
model's own "never fabricate" principle. The homepage's existing
Potato/Tweaks/Extreme rows are driven by the live hero + potato
candidate pools (real Steam catalog scrapes) run through this same
unchanged classifier — so this validation pass increases confidence in
the classifier's calibration across genres/vendors without needing any
game hardcoded into it.
