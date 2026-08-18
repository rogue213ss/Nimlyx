"""
NIMLYX PICKS — select_worth_buying()

Turns the leftover HeroCandidates from a hero build (everything that
didn't win a hero slot) into the ordered list that powers the
Nimlyx Picks row. Per docs/homepage-engine.md: Picks is sourced from
leftover candidates from the SAME pipeline that built the heroes —
it is not a separate system, doesn't re-scrape or re-score anything,
and never repeats a game the hero row already featured (that's
already guaranteed upstream by selector.py's one-slot-per-game rule).

Two kinds of "not selected" get treated very differently here:

  1. Genuine leftovers — the single best candidate for a game that
     simply didn't win a hero slot (lost its category's pass-1 lock,
     or the build was already at MAX_HEROES by the time it came up
     in backfill). These are exactly what Picks wants: real insights
     that were good enough to survive selection, just not good enough
     to beat that day's five strongest stories.

  2. Redundant candidates — a WEAKER candidate for a game whose
     stronger candidate for the SAME game already got decided one
     way or the other (selector.py's "Same game already has a
     stronger candidate" rejection). Including these would either
     duplicate a game already in the hero row, or duplicate a game
     already leading Picks under a different, weaker insight.
     Always excluded.

Candidates rejected purely for falling below the publish confidence
floor are excluded too — that floor exists precisely so a provider
with nothing honest to say doesn't end up on the homepage anyway,
hero row or Picks row.
"""

MAX_PICKS = 12


def select_worth_buying(all_candidates, max_picks=MAX_PICKS):
    """all_candidates: the second return value of build_hero_lineup()
    / select_heroes() — every HeroCandidate considered, already
    annotated with .selected / .rejected_reason.

    Returns an ordered list of HeroCandidate (highest confidence
    first), diversified by category the same way the hero selector
    is — one winner per category first, then backfill by raw
    confidence — so Picks doesn't accidentally end up as five
    discounts just because discounts happened to have deep bench
    strength that day.

    Template usage: [c.to_pick_dict() for c in select_worth_buying(...)]
    """
    leftovers = [
        c for c in all_candidates
        if c.selected is False
        and c.rejected_reason
        and not c.rejected_reason.startswith("Same game")
        and not c.rejected_reason.startswith("Confidence")
    ]

    leftovers.sort(key=lambda c: c.confidence, reverse=True)

    picks = []
    used_categories = set()
    still_open = []

    # Pass 1 — one pick per category, highest confidence first.
    for c in leftovers:
        if len(picks) >= max_picks:
            return picks
        if c.category in used_categories:
            still_open.append(c)
            continue
        picks.append(c)
        used_categories.add(c.category)

    # Pass 2 — backfill remaining slots by raw confidence, category
    # locks no longer apply.
    for c in still_open:
        if len(picks) >= max_picks:
            break
        picks.append(c)

    return picks