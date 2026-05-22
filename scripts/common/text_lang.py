"""Language gating for news titles surfaced to Korean/English readers.

Used by collectors that aggregate global feeds (geopolitical, worldmonitor,
social_media) where untranslated foreign-language titles otherwise leak into
the rendered post. Single source of truth so the gating rules stay aligned.
"""

from __future__ import annotations

import re

_HANGUL_RE = re.compile(r"[가-힣]")
# CJK Unified Ideographs (Chinese/Japanese Kanji) — distinct from Hangul block.
_CJK_IDEOGRAPH_RE = re.compile(r"[一-鿿]")


def is_supported_language(title: str) -> bool:
    """Return True only when title is Korean or English.

    Script checks run first because langdetect mis-labels CJK ideograph
    titles as 'ko' (its Korean profile shares ngrams with Chinese). After
    the script gate, langdetect resolves Latin-script ambiguity (en vs
    id/tr/de/...) and we accept only 'en'.
    """
    title = title.strip()
    if not title:
        return False
    if _HANGUL_RE.search(title):
        return True
    if _CJK_IDEOGRAPH_RE.search(title):
        return False
    try:
        from langdetect import DetectorFactory, detect

        DetectorFactory.seed = 0
        return detect(title) == "en"
    except Exception:
        return True
