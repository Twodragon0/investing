"""News severity classification keywords and helper.

Used by ThemeSummarizer to tag news items as high/medium/low severity for
ranking and visual rendering (badge HTML). No external state — pure functions
and static data, safe to import anywhere.
"""

_SEVERITY_HIGH_KW = [
    "crash",
    "surge",
    "record",
    "halt",
    "warn",
    "폭락",
    "급등",
    "급락",
    "사상최",
    "최고치",
    "최저치",
    "긴급",
    "속보",
    "전쟁",
    "war",
    "bomb",
    "attack",
    "sanction",
    "ban",
    "default",
    "bankruptcy",
    "파산",
    "fraud",
    "sec ",
    "fda ",
    "fed ",
    "fomc",
    "금리",
    "인상",
    "인하",
    "breaking",
    "crisis",
    "위기",
]

_SEVERITY_LOW_KW = [
    "opinion",
    "column",
    "editorial",
    "인터뷰",
    "리뷰",
    "review",
    "guide",
    "가이드",
    "tip",
    "팁",
    "예정",
    "계획",
]


def _classify_news_severity(title: str, description: str = "") -> str:
    """Classify news severity as high/medium/low based on keywords."""
    text = (title + " " + description).lower()
    if any(kw in text for kw in _SEVERITY_HIGH_KW):
        return "high"
    if any(kw in text for kw in _SEVERITY_LOW_KW):
        return "low"
    return "medium"


_SEV_BADGE_HTML = {
    "high": '<span class="news-severity news-severity-high">HIGH</span>',
    "medium": '<span class="news-severity news-severity-med">MED</span>',
    "low": '<span class="news-severity news-severity-low">LOW</span>',
}
