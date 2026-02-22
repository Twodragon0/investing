from typing import Tuple

IMPACT_RANK = {
    "높음": 0,
    "중간~높음": 1,
    "중간": 2,
    "낮음~중간": 3,
}

THEME_RANK = {
    "지정학/안보": 0,
    "에너지": 1,
    "금융시장": 1,
    "정책/법률": 2,
    "사회/기타": 3,
}


def worldmonitor_sort_key(impact: str, theme: str) -> Tuple[int, int]:
    return (IMPACT_RANK.get(impact, 9), THEME_RANK.get(theme, 9))
