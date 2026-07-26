"""
SELECTOR — turns a flat list of HeroCandidate objects into the final
homepage hero lineup.

Algorithm:
  1. Sort all candidates by confidence, descending.
  2. Pick the highest-confidence candidate.
  3. Lock its category — no other candidate from that category can
     win a slot this round.
  4. Repeat from the remaining pool (categories not yet locked).
  5. BACKFILL, CAPPED: once every category has either won a slot or
     has no candidates left, fill remaining slots by raw confidence —
     but no single category may claim more than MAX_PER_CATEGORY
     slots total, hero row included. If a category hits its cap, its
     remaining candidates are skipped during backfill even if they
     have the highest confidence left in the pool.
  6. Cap at MAX_HEROES. Never force a slot — if nothing is left that
     both clears the confidence floor AND has room under its
     category cap, ship fewer heroes. Quality over quantity.

Why the cap: live testing showed fresh_release structurally produces
more high-confidence candidates than any other provider on an average
day (new releases happen constantly; discounts/hidden gems/mixed
splits are rarer). Uncapped backfill let it silently claim 3 of 5
hero slots on the first real run. The cap trades "always fill 5
slots" for "never let one signal type quietly become the whole
homepage" — consistent with the diversity-is-intentional principle.

Every candidate that didn't win a slot is kept, not discarded — each
gets a `rejected_reason` for the eventual build manifest.
"""

MAX_HEROES = 5
MIN_CONFIDENCE_TO_PUBLISH = 40
MAX_PER_CATEGORY = 2  # even during backfill — no category owns more than this


def select_heroes(candidates):
    """candidates: list of HeroCandidate (unselected).

    Returns (selected, all_candidates).
    """
    if not candidates:
        return [], []

    eligible = []
    for c in candidates:
        if c.confidence < MIN_CONFIDENCE_TO_PUBLISH:
            c.reject(f"Confidence {c.confidence} below publish threshold ({MIN_CONFIDENCE_TO_PUBLISH}).")
        else:
            eligible.append(c)

    # One slot per GAME max — keep only each game's strongest candidate.
    best_per_game = {}
    for c in eligible:
        existing = best_per_game.get(c.app_id)
        if existing is None or c.confidence > existing.confidence:
            if existing is not None:
                existing.reject(
                    f"Same game already has a stronger candidate "
                    f"({existing.category}, confidence {existing.confidence})."
                )
            best_per_game[c.app_id] = c
        else:
            c.reject(
                f"Same game already has a stronger candidate "
                f"({existing.category}, confidence {existing.confidence})."
            )

    remaining = sorted(best_per_game.values(), key=lambda c: c.confidence, reverse=True)

    selected = []
    category_counts = {}

    def category_has_room(category):
        return category_counts.get(category, 0) < MAX_PER_CATEGORY

    # Pass 1 — one winner per category, highest confidence first.
    still_open = []
    used_categories = set()
    for c in remaining:
        if len(selected) >= MAX_HEROES:
            still_open.append(c)
            continue
        if c.category in used_categories:
            still_open.append(c)
            continue
        c.accept()
        selected.append(c)
        used_categories.add(c.category)
        category_counts[c.category] = category_counts.get(c.category, 0) + 1

    # Pass 2 — capped backfill. Category locks from pass 1 no longer
    # apply, but MAX_PER_CATEGORY still does — a category that already
    # has 2 slots is skipped even if it has the next-highest confidence
    # candidate remaining.
    for c in still_open:
        if len(selected) >= MAX_HEROES:
            c.reject("Homepage already at max heroes for this build.")
            continue
        if not category_has_room(c.category):
            c.reject(
                f"Category '{c.category}' already has {MAX_PER_CATEGORY} heroes "
                f"this build — capped to preserve diversity."
            )
            continue
        c.accept()
        selected.append(c)
        category_counts[c.category] = category_counts.get(c.category, 0) + 1

    return selected, candidates