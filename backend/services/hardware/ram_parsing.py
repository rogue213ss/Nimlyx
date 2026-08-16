"""
RAM requirement parsing.

Steam's `ram` requirement field (already isolated by
services/game/requirements.py's label mapping -- "Memory"/"RAM" only,
never VRAM or storage) is still free text, e.g. "8 GB RAM", "16 GB",
"8GB System Memory". This extracts a single GB value from it, or
returns None when no reliable value can be found.

Because parse_requirements() already segregates RAM into its own
field (separate from the gpu/storage fields, which is where VRAM and
disk-space numbers actually live), this module does not need any
logic to distinguish RAM from VRAM/storage -- that separation already
happened upstream. This module's only job is turning whatever text
landed in the ram field into a number, honestly.
"""

import re

# Matches the first "<number> GB" or "<number> MB" in the text.
# Requires an explicit unit -- a bare number with no GB/MB is never
# guessed at, per the "don't fabricate data" principle used throughout
# this codebase.
_GB_RE = re.compile(r"(\d+(?:\.\d+)?)\s*GB\b", re.IGNORECASE)
_MB_RE = re.compile(r"(\d+(?:\.\d+)?)\s*MB\b", re.IGNORECASE)


def parse_ram_gb(text):
    """Returns a float GB value, or None if the text doesn't contain
    a reliably parseable RAM amount. Never raises.

    Prefers a GB match over an MB match if both somehow appear (GB is
    the overwhelmingly common unit for system RAM in Steam listings;
    an MB-only value is still honored, converted to GB, only when no
    GB value is present at all).
    """
    if not text or not isinstance(text, str):
        return None

    try:
        gb_match = _GB_RE.search(text)
        if gb_match:
            return float(gb_match.group(1))

        mb_match = _MB_RE.search(text)
        if mb_match:
            return float(mb_match.group(1)) / 1024.0

        return None
    except Exception:
        return None
