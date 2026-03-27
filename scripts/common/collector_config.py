"""수집기 설정 로더 (collector_config.py).

scripts/config/collectors.yml 파일을 한 번만 로드하고 캐싱합니다.
각 수집기는 get_collector_config(name)으로 해당 설정을 가져옵니다.
global 기본값과 수집기별 설정을 병합하여 반환합니다.
"""

import logging
import os
from typing import Any, Dict, Optional, Union

logger = logging.getLogger(__name__)

# 설정 파일 경로 (scripts/config/collectors.yml)
_CONFIG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config")
_COLLECTORS_YAML = os.path.join(_CONFIG_DIR, "collectors.yml")

# 싱글톤 캐시: None이면 아직 로드 안 됨, False면 로드 실패
_config_cache: Optional[Union[Dict[str, Any], bool]] = None


def _load_yaml() -> Optional[Dict[str, Any]]:
    """YAML 파일을 로드하여 dict로 반환합니다. 실패 시 None 반환."""
    try:
        import yaml  # PyYAML (선택 의존성)
    except ImportError:
        logger.debug("PyYAML이 설치되지 않아 collectors.yml 로드를 건너뜁니다.")
        return None

    if not os.path.exists(_COLLECTORS_YAML):
        logger.debug("collectors.yml 파일이 없습니다: %s", _COLLECTORS_YAML)
        return None

    try:
        with open(_COLLECTORS_YAML, encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
        if not isinstance(data, dict):
            logger.warning("collectors.yml 형식 오류: 최상위 레벨이 dict여야 합니다.")
            return None
        logger.debug("collectors.yml 로드 완료")
        return data
    except Exception as exc:  # noqa: BLE001
        logger.warning("collectors.yml 로드 실패: %s", exc)
        return None


def _get_full_config() -> Optional[Dict[str, Any]]:
    """YAML 전체를 반환합니다 (싱글톤 캐시 사용)."""
    global _config_cache  # noqa: PLW0603
    if _config_cache is None:
        loaded = _load_yaml()
        # 로드 실패 시 False로 표시하여 재시도 방지
        _config_cache = loaded if loaded is not None else False
    return _config_cache if _config_cache is not False else None  # type: ignore[return-value]


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    """base에 override를 깊이 병합하여 새 dict 반환.

    override의 값이 우선합니다. 양쪽 모두 dict인 경우 재귀 병합합니다.
    """
    result = dict(base)
    for key, val in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(val, dict):
            result[key] = _deep_merge(result[key], val)
        else:
            result[key] = val
    return result


def get_global_config() -> Dict[str, Any]:
    """global 섹션 설정을 반환합니다.

    YAML이 없거나 로드 실패 시 빈 dict 반환 (하드코딩 기본값으로 폴백).
    """
    full = _get_full_config()
    if full is None:
        return {}
    return dict(full.get("global", {}))


def get_collector_config(name: str) -> Dict[str, Any]:
    """수집기별 설정을 반환합니다 (global 기본값 병합 포함).

    Args:
        name: 수집기 이름 (예: "coinmarketcap", "defi_llama", "crypto_news")

    Returns:
        global 설정 위에 수집기별 설정을 덮어씌운 dict.
        YAML이 없거나 해당 수집기 섹션이 없으면 global 설정만 반환합니다.
    """
    full = _get_full_config()
    if full is None:
        return {}

    global_cfg = dict(full.get("global", {}))
    collector_cfg = full.get(name, {})

    if not isinstance(collector_cfg, dict):
        logger.warning("collectors.yml: '%s' 섹션이 dict가 아닙니다.", name)
        return global_cfg

    return _deep_merge(global_cfg, collector_cfg)


def get_url(collector: str, key: str, default: str = "") -> str:
    """수집기의 특정 URL을 반환합니다.

    Args:
        collector: 수집기 이름
        key: urls 섹션 내 키 이름
        default: YAML에 값이 없을 때 반환할 기본값

    Returns:
        URL 문자열. 없으면 default 반환.
    """
    cfg = get_collector_config(collector)
    return cfg.get("urls", {}).get(key, default)


def get_limit(collector: str, key: str, default: int = 20) -> int:
    """수집기의 특정 limit 값을 반환합니다.

    Args:
        collector: 수집기 이름
        key: limits 섹션 내 키 이름
        default: YAML에 값이 없을 때 반환할 기본값

    Returns:
        int 값. 없거나 타입이 맞지 않으면 default 반환.
    """
    cfg = get_collector_config(collector)
    val = cfg.get("limits", {}).get(key, default)
    try:
        return int(val)
    except (TypeError, ValueError):
        logger.warning("collectors.yml: %s.limits.%s 값이 정수가 아닙니다: %r", collector, key, val)
        return default


def get_threshold(collector: str, key: str, default: float = 0.0) -> float:
    """수집기의 특정 threshold 값을 반환합니다.

    Args:
        collector: 수집기 이름
        key: thresholds 섹션 내 키 이름
        default: YAML에 값이 없을 때 반환할 기본값

    Returns:
        float 값. 없거나 타입이 맞지 않으면 default 반환.
    """
    cfg = get_collector_config(collector)
    val = cfg.get("thresholds", {}).get(key, default)
    try:
        return float(val)
    except (TypeError, ValueError):
        logger.warning("collectors.yml: %s.thresholds.%s 값이 숫자가 아닙니다: %r", collector, key, val)
        return default


def reload_config() -> None:
    """캐시를 초기화하여 다음 접근 시 YAML을 다시 로드합니다.

    테스트나 설정 갱신 시 유용합니다.
    """
    global _config_cache  # noqa: PLW0603
    _config_cache = None
