from services.hero.builder import build_hero_lineup

selected, all_candidates = build_hero_lineup(cc="US")

print(f"=== SELECTED ({len(selected)}) ===")
for c in selected:
    print(f"{c.name} | {c.category} | confidence={c.confidence}")
    print(f"  {c.insight}")
    print(f"  why: {c.why_it_matters}")
    print()

from collections import Counter
cat_counts = Counter(c.category for c in selected)
print("Category distribution:", dict(cat_counts))
print()

print(f"--- {len(all_candidates) - len(selected)} rejected ---")
for c in all_candidates:
    if c.selected is False:
        print(f"{c.name} | {c.category} | {c.confidence} | {c.rejected_reason}")