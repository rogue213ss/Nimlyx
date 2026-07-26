"""
HERO CANDIDATE — the shared object every Insight Provider's output
gets wrapped into before it reaches the selector.

Keeping this as its own tiny module (rather than just passing raw
dicts around) is deliberate: it gives every candidate, winner or
loser, one consistent shape to inspect later — which is what makes
the eventual build manifest (Phase 4) possible. A candidate that
LOSES selection isn't discarded; it's kept with a `rejected_reason`
so a future "why wasn't Elden Ring featured?" question has an actual
answer instead of a shrug.

Serialization: to_hero_dict() and to_pick_dict() are the two contracts
the frontend actually consumes — Jinja never touches HeroCandidate
directly, and never sees `confidence`, `rejected_reason`, or
`category` as a raw string. Both share _build_base_dict() for the
common game fields (name, image, price, url) so that data isn't
duplicated between the two, but each adds only what its own section
of the page actually needs — changing the hero's fields later can't
accidentally break the Picks row, and vice versa.
"""

from formatters import format_price
from services.hero.badges import get_badge
from services.hero.curated_art import resolve_hero_image
from steam_images import build_image_candidates, default_header_image


class HeroCandidate:
    def __init__(self, game, category, confidence, insight, why_it_matters):
        self.game = game  # raw appdetails dict (+ review_summary, id, etc.)
        self.category = category
        self.confidence = confidence
        self.insight = insight
        self.why_it_matters = why_it_matters

        # Set by the selector, not at construction time. None means
        # "not yet decided"; True/False means the selector has ruled.
        self.selected = None
        self.rejected_reason = None

    @property
    def app_id(self):
        return self.game.get("steam_appid") or self.game.get("id")

    @property
    def name(self):
        return self.game.get("name", "Unknown")

    def reject(self, reason):
        self.selected = False
        self.rejected_reason = reason
        return self

    def accept(self):
        self.selected = True
        self.rejected_reason = None
        return self

    def _guaranteed_image(self):
        """The image every hero/pick card renders immediately.

        Previously this guessed capsule_616x353.jpg directly as the
        src for every candidate — plausible-sounding ("Valve
        generates it for essentially every app ID"), but "essentially"
        isn't "always", and a 404 there showed a blank/broken card.

        Now: appdetails' own header_image (already sitting on
        self.game from the live call that built this candidate) when
        present, else the CDN-convention header.jpg, which costs zero
        API calls and Steam serves for every listed app. Either way
        this never guesses an asset that might not exist.
        """
        return self.game.get("header_image") or default_header_image(self.app_id)

    def _image_candidates(self):
        """Unverified higher-res URLs (library hero, capsule, etc.).
        Never sent to an <img src> directly — the frontend probes
        each one with a real Image() load and only swaps it in on
        success. See static/js/image-upgrade.js."""
        return build_image_candidates(self.app_id)

    def _build_base_dict(self):
        """Common game fields shared by every frontend-facing
        serialization. Neither to_hero_dict() nor to_pick_dict() should
        rebuild this from scratch — extend it, don't duplicate it.
        """
        price_overview = self.game.get("price_overview") or {}
        if self.game.get("is_free"):
            price = "Free"
        else:
            price = price_overview.get("final_formatted") or format_price(
                price_overview.get("final")
            )

        return {
            "app_id": self.app_id,
            "name": self.name,
            "image": self._guaranteed_image(),
            "image_candidates": self._image_candidates(),
            "price": price,
            "url": f"/search?q={self.name}",
        }

    def to_manifest_dict(self):
        """Shape used by build manifests (Phase 4) — one line per
        candidate, winner or loser, with enough info to answer
        "why is/isn't this game here" without re-running anything.
        Deliberately NOT built on _build_base_dict() — this is an
        internal debugging artifact, not something Jinja ever sees,
        and it needs fields (confidence, rejected_reason) the
        frontend contracts must never expose.
        """
        return {
            "app_id": self.app_id,
            "name": self.name,
            "category": self.category,
            "confidence": self.confidence,
            "selected": self.selected,
            "rejected_reason": self.rejected_reason,
        }

    def to_hero_dict(self):
        """Shape used by the frontend for a published hero slide.

        Hero slides are the one place worth reaching past Steam's own
        artwork entirely -- see services/hero/curated_art.py. A
        curated/IGDB override still only replaces `image` (the
        immediately-rendered src); image_candidates stays untouched
        so the client-side upgrade path still has somewhere to fall
        back to if the override URL itself is unset.
        """
        base = self._build_base_dict()
        base["image"] = resolve_hero_image(self.app_id, base["image"])
        badge = get_badge(self.category)
        base.update({
            "badge_label": badge["label"],
            "badge_class": badge["class"],
            "badge_icon": badge["icon"],
            "insight": self.insight,
            "why_it_matters": self.why_it_matters,
        })
        return base

    def to_pick_dict(self):
        """Shape used by a Nimlyx Picks card. Template never sees
        `confidence`, `category` as a raw string, or provider internals
        — only the already-resolved badge_label/badge_class/badge_icon.
        """
        base = self._build_base_dict()
        badge = get_badge(self.category)
        base.update({
            "badge_label": badge["label"],
            "badge_class": badge["class"],
            "badge_icon": badge["icon"],
            "insight": self.insight,
            "why_it_matters": self.why_it_matters,
        })
        return base

    def __repr__(self):
        return f"<HeroCandidate {self.name!r} category={self.category} confidence={self.confidence} selected={self.selected}>"