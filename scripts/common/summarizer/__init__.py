"""Summarizer package facade.

This package will eventually host the decomposed ``ThemeSummarizer`` and
its helpers (see ``.omc/plans/split-summarizer.md``). During the refactor
this ``__init__`` re-exports the existing public API from
``scripts/common/summarizer_legacy.py`` so that all call sites remain
unchanged while the underlying module tree is rebuilt incrementally.

Do **not** add new code directly to this file. New modules go in one of
the siblings (``constants.py``, ``text_utils.py``, ``descriptions.py``,
``scoring.py``, ``briefings.py``, ``narrative.py``, ``sentiment.py``,
``theme_summarizer.py``). When a symbol is ready to move, update its
explicit re-export below to point at the new module.
"""

from ..summarizer_legacy import (
    _NOISE_TITLE_RE,
    PRIORITY_KEYWORDS,
    THEMES,
    ThemeSummarizer,
    _classify_news_severity,
    _generate_title_based_desc,
    _is_boilerplate_desc,
    _is_generic_desc,
    _truncate_sentence,
)

__all__ = [
    "PRIORITY_KEYWORDS",
    "THEMES",
    "ThemeSummarizer",
    "_NOISE_TITLE_RE",
    "_classify_news_severity",
    "_generate_title_based_desc",
    "_is_boilerplate_desc",
    "_is_generic_desc",
    "_truncate_sentence",
]
