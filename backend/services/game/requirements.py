"""System Requirements parser — Sprint 5.

Steam's appdetails response carries `pc_requirements` as a blob of raw
HTML, not structured fields:

    {
      "minimum": "<strong>Minimum:</strong><br><ul class=\"bb_ul\">"
                 "<li><strong>OS:</strong> Windows 10<br></li>"
                 "<li><strong>Processor:</strong> Intel i5<br></li>...",
      "recommended": "..."
    }

This is parsed ONCE here, in build_game_detail(), off the SAME
appdetails response every game page already fetches — no extra Steam
call. The frontend never touches raw HTML; it only ever sees the
normalized shape below.

Nimlyx Tradition — Steam's pc_requirements is inconsistent across the
catalog, not just across games:
  - Most titles: dict with both "minimum" and "recommended" keys, each
    a <ul><li><strong>Label:</strong> value<br></li></ul> blob.
  - Some titles: only "minimum" present ("recommended" key absent).
  - Older/delisted or barely-listed titles: pc_requirements is an
    empty list `[]` instead of a dict (Steam's placeholder for "no
    data"), never a dict with empty strings.
  - A handful of titles: a requirements string with NO <strong> label
    tags at all -- just a paragraph of freeform text.

parse_requirements() treats the last case honestly: if a tier's HTML
has no recognizable Label: value pairs, that tier's fields stay empty
rather than guessing which sentence maps to CPU vs GPU. An empty
field is correct behavior here, not a bug -- same principle as every
other "don't fabricate" rule in this codebase.

This ALWAYS returns the same shape, regardless of input:

    {
      "minimum":     {"os": "", "cpu": "", "gpu": "", "ram": "", "storage": ""},
      "recommended": {"os": "", "cpu": "", "gpu": "", "ram": "", "storage": ""},
    }

Never raises. Any unexpected shape from Steam (None, wrong type,
malformed HTML) degrades to empty fields for that tier -- this must
never be the thing that breaks a game detail page.
"""

import re

_EMPTY_TIER = {"os": "", "cpu": "", "gpu": "", "ram": "", "storage": ""}

# Steam's own requirement labels, normalized (lowercased, colon
# stripped) -> our schema key. Steam varies "Processor"/"CPU" and
# "Graphics"/"Graphics Card" across titles, so a few aliases are
# mapped per field rather than assuming one exact label string.
_LABEL_MAP = {
    "os": "os",
    "operating system": "os",
    "processor": "cpu",
    "cpu": "cpu",
    "memory": "ram",
    "ram": "ram",
    "graphics": "gpu",
    "graphics card": "gpu",
    "video card": "gpu",
    "storage": "storage",
    "hard drive": "storage",
    "hard disk space": "storage",
}

# Matches a single "<strong>Label:</strong> value" pair, tolerant of
# whatever's between </strong> and the next tag/end -- covers Steam's
# real markup (<li><strong>OS:</strong> Windows 10<br></li>) without
# depending on <li>/<ul> being present at all, since some titles omit
# the list wrapper and just chain <strong>...</strong> pairs directly.
_LABEL_VALUE_RE = re.compile(
    r"<strong>\s*([^<:]+?)\s*:?\s*</strong>\s*(.*?)(?=<strong>|</li>|<br\s*/?>|$)",
    re.IGNORECASE | re.DOTALL,
)

_TAG_RE = re.compile(r"<[^>]+>")


def _strip_tags(text):
    return _TAG_RE.sub("", text).strip()


def _parse_tier(raw_html):
    """One tier ('minimum' or 'recommended') -> a filled-in copy of
    _EMPTY_TIER. Returns _EMPTY_TIER unchanged if raw_html isn't a
    non-empty string or has no recognizable Label: value pairs."""
    tier = dict(_EMPTY_TIER)

    if not raw_html or not isinstance(raw_html, str):
        return tier

    matches = _LABEL_VALUE_RE.findall(raw_html)
    if not matches:
        # Case 3 -- raw text with no <strong> labels at all. Nothing
        # here can be honestly assigned to a specific field, so this
        # tier stays empty rather than guessing.
        return tier

    for raw_label, raw_value in matches:
        key = _LABEL_MAP.get(raw_label.strip().lower())
        if not key:
            continue  # unrecognized label (e.g. "DirectX", "Sound Card") -- not in our schema, skip
        value = _strip_tags(raw_value)
        if value and not tier[key]:
            # First match wins if a label somehow repeats -- Steam's
            # markup doesn't normally do this, but never overwrite a
            # real value with a later, likely-malformed duplicate.
            tier[key] = value

    return tier


def parse_requirements(pc_requirements):
    """Entry point. `pc_requirements` is whatever raw appdetails'
    `pc_requirements` field contains for this game -- a dict, an
    empty list, None, or anything else. Always returns the fixed
    {"minimum": {...}, "recommended": {...}} shape; never raises."""
    try:
        if not isinstance(pc_requirements, dict):
            # Steam's own "no data" shape is `[]`; anything else
            # unexpected (None, str, etc.) is treated the same way --
            # no requirements to show, not an error.
            return {"minimum": dict(_EMPTY_TIER), "recommended": dict(_EMPTY_TIER)}

        return {
            "minimum": _parse_tier(pc_requirements.get("minimum")),
            "recommended": _parse_tier(pc_requirements.get("recommended")),
        }
    except Exception:
        # Parsing must never be the reason a game detail page fails.
        # Any unexpected error here degrades to the same honest empty
        # shape rather than propagating up into build_game_detail().
        return {"minimum": dict(_EMPTY_TIER), "recommended": dict(_EMPTY_TIER)}
