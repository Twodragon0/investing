"""Korean-headline selection for generated post descriptions.

Collectors lead ``description_ko`` with the top item's headline so the summary
reads concretely instead of "…관련 소식이 주목됩니다". Every call site spelled
that lookup out as ``title_ko or title_translated or title``, which silently
falls back to the untranslated English title. Nothing checked that the fallback
changed language, so English headlines shipped into Korean descriptions and
surfaced as the "ASCII-heavy desc" class in
``scripts/check_description_quality.py``.

This module is the single place that answers "what Korean headline, if any,
should lead this description?". Returning ``""`` is a normal answer: each caller
already has a headline-free branch that states counts and themes instead.
"""

from __future__ import annotations

import re
from typing import Any, Mapping, Optional

from common.summary_quality import is_ascii_dominant
from common.translator import translate_to_korean

__all__ = ["select_korean_headline"]

# Checked in order. ``common.translator.get_display_title`` reads only
# ``title_ko``/``title``, so items carrying a translation under
# ``title_translated`` lost it there; this order covers both conventions.
_TITLE_KEYS = ("title_ko", "title_translated", "title")

# A single uppercase token — an acronym or ticker such as ``CPI``, ``FOMC``,
# ``GDP``, ``AAPL``. These are not English prose: Korean readers use them
# verbatim, machine translation leaves them unchanged, and dropping them costs
# the summary its only concrete token. Multi-word Title Case ("Nonfarm
# Payrolls", "Treasury Sec Bessent Speaks") is prose and stays subject to the
# translate-or-drop rule.
_ACRONYM_RE = re.compile(r"^[A-Z0-9][A-Z0-9.&^-]{0,7}$")


def select_korean_headline(item: Mapping[str, Any]) -> str:
    """Return a Korean headline for ``item``, or ``""`` when none is available.

    Translation is attempted for an English candidate, but
    ``translate_to_korean`` is fail-open — it returns its input unchanged when
    the service is disabled or errors (``common/translator.py``). The result is
    therefore re-checked rather than trusted, so a failed translation yields
    ``""`` instead of leaking the English original.
    """
    candidate = _first_title(item)
    if not candidate:
        return ""
    if not is_ascii_dominant(candidate) or _ACRONYM_RE.match(candidate):
        return candidate

    translated = (translate_to_korean(candidate) or "").strip()
    if translated and not is_ascii_dominant(translated):
        return translated
    return ""


def _first_title(item: Mapping[str, Any]) -> str:
    for key in _TITLE_KEYS:
        value: Optional[Any] = item.get(key)
        if value:
            text = str(value).strip()
            if text:
                return text
    return ""
