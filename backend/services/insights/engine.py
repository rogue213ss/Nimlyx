"""
INSIGHT ENGINE — runs every registered Insight Provider against every
game in the candidate pool and collects the results as HeroCandidate
objects. Deliberately dumb: this file doesn't rank, select, or
enforce diversity — that's selector.py's job.

Adding a new provider means adding one line to PROVIDERS below —
nothing else in this file changes.
"""

from services.hero.candidate import HeroCandidate
from services.insights import critic_gap, fresh_release, discount, hidden_gem, mixed_contrarian

PROVIDERS = [
    critic_gap,
    fresh_release,
    discount,
    hidden_gem,
    mixed_contrarian,
]


def generate_candidates(pool):
    candidates = []

    for game in pool:
        for provider in PROVIDERS:
            try:
                result = provider.generate(game)
            except Exception:
                result = None

            if result is None:
                continue

            candidates.append(HeroCandidate(
                game=game,
                category=result["category"],
                confidence=result["confidence"],
                insight=result["insight"],
                why_it_matters=result["why_it_matters"],
            ))

    return candidates