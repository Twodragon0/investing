"""수집기 설정 로더 테스트 (test_collector_config.py).

tests:
- YAML 로드 정상 동작
- global 설정 반환
- 수집기별 설정과 global 병합
- YAML 없을 때 폴백(빈 dict) 동작
- 잘못된 YAML 처리
- get_url / get_limit / get_threshold 헬퍼
- reload_config로 캐시 초기화

참고: common/__init__.py가 Python 3.9 미지원 심볼을 사용하므로
      `import common.collector_config` 대신 sys.modules를 직접 제어합니다.
"""

import importlib
import importlib.util
import os
import sys
import tempfile
from typing import Any, Dict
from unittest.mock import patch

import pytest

# ---------------------------------------------------------------------------
# collector_config 모듈을 __init__.py 없이 직접 로드
# ---------------------------------------------------------------------------

_SCRIPTS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "scripts"))
_CC_PATH = os.path.join(_SCRIPTS_DIR, "common", "collector_config.py")


def _load_collector_config():
    """common/__init__.py 없이 collector_config.py를 직접 임포트합니다."""
    spec = importlib.util.spec_from_file_location("common.collector_config", _CC_PATH)
    mod = importlib.util.module_from_spec(spec)
    # common 패키지 플레이스홀더가 없으면 추가
    if "common" not in sys.modules:
        import types

        sys.modules["common"] = types.ModuleType("common")
    sys.modules["common.collector_config"] = mod
    spec.loader.exec_module(mod)
    return mod


# 테스트 시작 시 한 번만 로드
cc = _load_collector_config()

# ---------------------------------------------------------------------------
# 픽스처: 임시 YAML 파일 생성 헬퍼
# ---------------------------------------------------------------------------

_SAMPLE_YAML = """
global:
  request_timeout: 15
  fuzzy_match_threshold: 80

coinmarketcap:
  urls:
    cmc_listings: "https://pro-api.coinmarketcap.com/v1/cryptocurrency/listings/latest"
    cmc_site: "https://coinmarketcap.com/"
  limits:
    top_coins: 30
    trending_coins: 10
  request_timeout: 20
  state_file: "coinmarketcap_posts.json"

defi_llama:
  urls:
    base: "https://api.llama.fi"
  limits:
    top_protocols: 20
    top_chains: 15
  thresholds:
    tvl_stale_days: 3
  state_file: "defi_llama_posts.json"
"""

_MALFORMED_YAML = "key: [unclosed list"

_NON_DICT_YAML = "- item1\n- item2\n"


@pytest.fixture(autouse=True)
def reset_cache():
    """각 테스트 전후로 싱글톤 캐시를 초기화합니다."""
    cc.reload_config()
    yield
    cc.reload_config()


# ---------------------------------------------------------------------------
# 헬퍼: YAML 파일 경로를 패치하여 테스트
# ---------------------------------------------------------------------------


def _yaml_tmp(content: str):
    """임시 YAML 파일 컨텍스트 매니저."""
    return tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False, encoding="utf-8")


# ---------------------------------------------------------------------------
# YAML 로드 테스트
# ---------------------------------------------------------------------------


def test_load_yaml_success():
    """정상적인 YAML 파일 로드."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False, encoding="utf-8") as f:
        f.write(_SAMPLE_YAML)
        tmp_path = f.name

    try:
        with patch.object(cc, "_COLLECTORS_YAML", tmp_path):
            cc.reload_config()
            cfg = cc._get_full_config()
        assert cfg is not None
        assert "global" in cfg
        assert "coinmarketcap" in cfg
        assert "defi_llama" in cfg
    finally:
        os.unlink(tmp_path)


def test_load_yaml_file_missing():
    """YAML 파일이 없으면 None 반환 (폴백 동작)."""
    with patch.object(cc, "_COLLECTORS_YAML", "/nonexistent/path/collectors.yml"):
        cc.reload_config()
        cfg = cc._get_full_config()
    assert cfg is None


def test_load_yaml_malformed():
    """손상된 YAML은 None 반환."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False, encoding="utf-8") as f:
        f.write(_MALFORMED_YAML)
        tmp_path = f.name

    try:
        with patch.object(cc, "_COLLECTORS_YAML", tmp_path):
            cc.reload_config()
            cfg = cc._get_full_config()
        assert cfg is None
    finally:
        os.unlink(tmp_path)


def test_load_yaml_non_dict():
    """YAML 최상위가 dict가 아니면 None 반환."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False, encoding="utf-8") as f:
        f.write(_NON_DICT_YAML)
        tmp_path = f.name

    try:
        with patch.object(cc, "_COLLECTORS_YAML", tmp_path):
            cc.reload_config()
            cfg = cc._get_full_config()
        assert cfg is None
    finally:
        os.unlink(tmp_path)


# ---------------------------------------------------------------------------
# get_global_config 테스트
# ---------------------------------------------------------------------------


def test_get_global_config_with_yaml():
    """YAML이 있을 때 global 섹션 반환."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False, encoding="utf-8") as f:
        f.write(_SAMPLE_YAML)
        tmp_path = f.name

    try:
        with patch.object(cc, "_COLLECTORS_YAML", tmp_path):
            cc.reload_config()
            global_cfg = cc.get_global_config()
        assert global_cfg["request_timeout"] == 15
        assert global_cfg["fuzzy_match_threshold"] == 80
    finally:
        os.unlink(tmp_path)


def test_get_global_config_no_yaml():
    """YAML 없을 때 빈 dict 반환 (폴백)."""
    with patch.object(cc, "_COLLECTORS_YAML", "/nonexistent/collectors.yml"):
        cc.reload_config()
        global_cfg = cc.get_global_config()
    assert global_cfg == {}


# ---------------------------------------------------------------------------
# get_collector_config 병합 테스트
# ---------------------------------------------------------------------------


def test_get_collector_config_merges_global():
    """수집기별 설정이 global 기본값과 병합되는지 확인."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False, encoding="utf-8") as f:
        f.write(_SAMPLE_YAML)
        tmp_path = f.name

    try:
        with patch.object(cc, "_COLLECTORS_YAML", tmp_path):
            cc.reload_config()
            cfg = cc.get_collector_config("coinmarketcap")
        # global에서 상속
        assert cfg["fuzzy_match_threshold"] == 80
        # 수집기별 오버라이드
        assert cfg["request_timeout"] == 20
        assert cfg["state_file"] == "coinmarketcap_posts.json"
        assert cfg["limits"]["top_coins"] == 30
    finally:
        os.unlink(tmp_path)


def test_get_collector_config_unknown_collector():
    """존재하지 않는 수집기 이름이면 global 설정만 반환."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False, encoding="utf-8") as f:
        f.write(_SAMPLE_YAML)
        tmp_path = f.name

    try:
        with patch.object(cc, "_COLLECTORS_YAML", tmp_path):
            cc.reload_config()
            cfg = cc.get_collector_config("nonexistent_collector")
        # global 설정만 반환
        assert cfg["request_timeout"] == 15
        assert "urls" not in cfg
    finally:
        os.unlink(tmp_path)


def test_get_collector_config_no_yaml():
    """YAML 없을 때 빈 dict 반환."""
    with patch.object(cc, "_COLLECTORS_YAML", "/nonexistent/collectors.yml"):
        cc.reload_config()
        cfg = cc.get_collector_config("coinmarketcap")
    assert cfg == {}


# ---------------------------------------------------------------------------
# 폴백 동작 테스트
# ---------------------------------------------------------------------------


def test_get_url_fallback():
    """YAML 없을 때 get_url이 default 반환."""
    with patch.object(cc, "_COLLECTORS_YAML", "/nonexistent/collectors.yml"):
        cc.reload_config()
        url = cc.get_url("coinmarketcap", "cmc_listings", "https://fallback.example.com")
    assert url == "https://fallback.example.com"


def test_get_limit_fallback():
    """YAML 없을 때 get_limit이 default 반환."""
    with patch.object(cc, "_COLLECTORS_YAML", "/nonexistent/collectors.yml"):
        cc.reload_config()
        limit = cc.get_limit("defi_llama", "top_protocols", 99)
    assert limit == 99


def test_get_threshold_fallback():
    """YAML 없을 때 get_threshold가 default 반환."""
    with patch.object(cc, "_COLLECTORS_YAML", "/nonexistent/collectors.yml"):
        cc.reload_config()
        threshold = cc.get_threshold("geopolitical", "polymarket_min_volume", 5000.0)
    assert threshold == 5000.0


# ---------------------------------------------------------------------------
# get_url / get_limit / get_threshold 정상 동작 테스트
# ---------------------------------------------------------------------------


def test_get_url_with_yaml():
    """YAML에서 URL을 올바르게 읽는지 확인."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False, encoding="utf-8") as f:
        f.write(_SAMPLE_YAML)
        tmp_path = f.name

    try:
        with patch.object(cc, "_COLLECTORS_YAML", tmp_path):
            cc.reload_config()
            url = cc.get_url("coinmarketcap", "cmc_listings", "fallback")
        assert url == "https://pro-api.coinmarketcap.com/v1/cryptocurrency/listings/latest"
    finally:
        os.unlink(tmp_path)


def test_get_limit_with_yaml():
    """YAML에서 limit 값을 올바르게 읽는지 확인."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False, encoding="utf-8") as f:
        f.write(_SAMPLE_YAML)
        tmp_path = f.name

    try:
        with patch.object(cc, "_COLLECTORS_YAML", tmp_path):
            cc.reload_config()
            limit = cc.get_limit("defi_llama", "top_protocols", 99)
        assert limit == 20
    finally:
        os.unlink(tmp_path)


def test_get_threshold_with_yaml():
    """YAML에서 threshold 값을 올바르게 읽는지 확인."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False, encoding="utf-8") as f:
        f.write(_SAMPLE_YAML)
        tmp_path = f.name

    try:
        with patch.object(cc, "_COLLECTORS_YAML", tmp_path):
            cc.reload_config()
            threshold = cc.get_threshold("defi_llama", "tvl_stale_days", 0.0)
        assert threshold == 3.0
    finally:
        os.unlink(tmp_path)


# ---------------------------------------------------------------------------
# 싱글톤 캐시 테스트
# ---------------------------------------------------------------------------


def test_singleton_cache():
    """YAML을 두 번 호출해도 한 번만 로드되는지 확인 (캐싱)."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False, encoding="utf-8") as f:
        f.write(_SAMPLE_YAML)
        tmp_path = f.name

    try:
        with patch.object(cc, "_COLLECTORS_YAML", tmp_path):
            cc.reload_config()
            cfg1 = cc._get_full_config()
            cfg2 = cc._get_full_config()
        # 동일한 객체를 반환해야 함
        assert cfg1 is cfg2
    finally:
        os.unlink(tmp_path)


def test_reload_config_clears_cache():
    """reload_config() 후 다시 로드되는지 확인."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False, encoding="utf-8") as f:
        f.write(_SAMPLE_YAML)
        tmp_path = f.name

    try:
        with patch.object(cc, "_COLLECTORS_YAML", tmp_path):
            cc.reload_config()
            cfg1 = cc._get_full_config()
            cc.reload_config()
            cfg2 = cc._get_full_config()
        assert cfg1 is not None
        assert cfg2 is not None
        # 내용은 동일해야 함
        assert cfg1 == cfg2
    finally:
        os.unlink(tmp_path)


# ---------------------------------------------------------------------------
# deep_merge 유닛 테스트
# ---------------------------------------------------------------------------


def test_deep_merge_basic():
    """기본 deep_merge: override 키가 우선."""
    base: Dict[str, Any] = {"a": 1, "b": 2}
    override: Dict[str, Any] = {"b": 99, "c": 3}
    result = cc._deep_merge(base, override)
    assert result == {"a": 1, "b": 99, "c": 3}


def test_deep_merge_nested():
    """중첩 dict도 재귀 병합."""
    base: Dict[str, Any] = {"urls": {"a": "http://a", "b": "http://b"}}
    override: Dict[str, Any] = {"urls": {"b": "http://b2", "c": "http://c"}}
    result = cc._deep_merge(base, override)
    assert result["urls"] == {"a": "http://a", "b": "http://b2", "c": "http://c"}


def test_deep_merge_override_scalar_with_dict():
    """기존 scalar 위에 dict가 오면 dict로 교체."""
    base: Dict[str, Any] = {"key": "scalar"}
    override: Dict[str, Any] = {"key": {"nested": 1}}
    result = cc._deep_merge(base, override)
    assert result["key"] == {"nested": 1}
