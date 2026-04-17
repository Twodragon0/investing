"""공통 콘텐츠 필터 모듈.

엔터테인먼트/스포츠 키워드 필터를 수집기 간 공유합니다.
각 수집기는 load_entertainment_keywords(collector_name)으로 1회 로딩 후
is_entertainment() / filter_entertainment()를 사용합니다.
"""

import logging
from typing import Any, Dict, List, Optional

from .collector_config import get_collector_config

_log = logging.getLogger(__name__)

# 모든 수집기 기본 키워드 합집합 (중복 제거)
_DEFAULT_ENTERTAINMENT_KEYWORDS: frozenset = frozenset(
    {
        # 북미 프로스포츠 리그
        "nba",
        "nfl",
        "mlb",
        "nhl",
        "mls",
        "ufc",
        # 국제 스포츠
        "fifa",
        "premier league",
        "champions league",
        "la liga",
        "bundesliga",
        "serie a",
        "ligue 1",
        "world cup soccer",
        "wimbledon",
        "grand prix",
        "formula 1",
        " f1 ",
        "olympics",
        "paralympics",
        # 주요 스포츠 이벤트
        "stanley cup",
        "super bowl",
        "world series",
        "nba finals",
        "nhl finals",
        "championship",
        "championships",
        "playoffs",
        "playoff",
        "mvp",
        "ballon d'or",
        "nfl draft",
        "nba draft",
        "mlb playoffs",
        "masters tournament",
        "us open tennis",
        "french open",
        "australian open",
        # 스포츠 행위/기록
        "touchdown",
        "home run",
        "slam dunk",
        "penalty kick",
        "hat trick",
        "mvp award",
        "draft pick",
        "trade deadline nba",
        "trade deadline nhl",
        "trade deadline nfl",
        "free agency nba",
        "free agency nfl",
        "signing bonus nfl",
        "signing bonus nba",
        # NBA 팀명
        "lakers",
        "celtics",
        "knicks",
        "warriors",
        "spurs",
        "clippers",
        "heat",
        "bulls",
        "nets",
        "pacers",
        "cavaliers",
        "nuggets",
        "timberwolves",
        "thunder",
        "suns",
        "mavericks",
        "rockets",
        "grizzlies",
        "pelicans",
        "hawks",
        "hornets",
        "magic",
        "wizards",
        "bucks",
        "raptors",
        "sixers",
        "pistons",
        # MLB/NFL 팀명
        "yankees",
        "dodgers",
        "patriots",
        "cowboys",
        # 시상식 / 연예 행사
        "oscar",
        "grammy",
        "emmy",
        "golden globe",
        "bafta",
        "cannes",
        "bachelor",
        "bachelorette",
        "survivor",
        # 미디어 / 팝컬처
        "netflix",
        "spotify",
        "disney+",
        "hulu",
        "hbo",
        "movie",
        "album",
        "box office",
        "billboard",
        "celebrity",
        "reality tv",
        "tv show",
        "season finale",
        "movie release",
        "album release",
        "billboard chart",
        "netflix show",
        "celebrity gossip",
        "celebrity drama",
        "taylor swift concert",
        "met gala",
        # 게임 (crypto-gaming 맥락 아닌 순수 게임 출시/이슈)
        "gta vi",
        "gta 6",
        "gta v",
        "esport",
        "e-sport",
        "video game",
        "game release",
        # 기타
        "grand prix winner",
        "champions league final",
        "championship game",
    }
)


def load_entertainment_keywords(collector_name: str) -> frozenset:
    """collectors.yml에서 {collector_name}.keywords.entertainment_keywords를 로딩합니다.

    로드 실패 또는 섹션 누락 시 _DEFAULT_ENTERTAINMENT_KEYWORDS로 fallback합니다.

    Args:
        collector_name: collectors.yml 섹션 키 (예: "geopolitical", "crypto_news")
    Returns:
        frozenset — 소문자 엔터테인먼트 키워드 집합
    """
    try:
        cfg = get_collector_config(collector_name)
    except Exception as exc:
        _log.debug("collectors.yml 로드 실패 (%s), 기본값 사용: %s", collector_name, exc)
        return _DEFAULT_ENTERTAINMENT_KEYWORDS

    kw_cfg = cfg.get("keywords", {})
    if not isinstance(kw_cfg, dict):
        _log.debug("collectors.yml: %s.keywords 섹션 없음, 기본값 사용", collector_name)
        return _DEFAULT_ENTERTAINMENT_KEYWORDS

    ent_raw = kw_cfg.get("entertainment_keywords")
    if isinstance(ent_raw, list) and ent_raw:
        _log.debug("collectors.yml에서 %s.entertainment_keywords %d개 로드", collector_name, len(ent_raw))
        return frozenset(ent_raw)

    _log.debug("collectors.yml: %s.entertainment_keywords 누락 또는 빈 값, 기본값 사용", collector_name)
    return _DEFAULT_ENTERTAINMENT_KEYWORDS


def is_entertainment(item: Dict[str, Any], keywords: Optional[frozenset] = None) -> bool:
    """title + description에 엔터테인먼트/스포츠 키워드가 포함되면 True를 반환합니다.

    Args:
        item: title, description 키를 가진 뉴스 아이템 dict
        keywords: 사용할 키워드 집합. None이면 _DEFAULT_ENTERTAINMENT_KEYWORDS 사용
    Returns:
        True이면 필터 대상 (엔터테인먼트/스포츠 콘텐츠)
    """
    kws = keywords if keywords is not None else _DEFAULT_ENTERTAINMENT_KEYWORDS
    text = (item.get("title", "") + " " + item.get("description", "")).lower()
    return any(kw in text for kw in kws)


def filter_entertainment(
    items: List[Dict[str, Any]],
    keywords: Optional[frozenset] = None,
    logger: Optional[Any] = None,
) -> List[Dict[str, Any]]:
    """엔터테인먼트/스포츠 아이템을 목록에서 제거합니다.

    Args:
        items: 뉴스 아이템 목록
        keywords: 사용할 키워드 집합. None이면 _DEFAULT_ENTERTAINMENT_KEYWORDS 사용
        logger: 필터링 건수를 기록할 logger. None이면 모듈 로거 사용
    Returns:
        필터링된 아이템 목록
    """
    _logger = logger or _log
    filtered = [item for item in items if not is_entertainment(item, keywords)]
    removed = len(items) - len(filtered)
    if removed:
        _logger.debug("엔터테인먼트 필터: %d건 제거 (전체 %d건)", removed, len(items))
    return filtered
