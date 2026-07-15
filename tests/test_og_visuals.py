"""Unit tests for scripts/common/og_visuals.py drawing helpers.

각 `_draw_visual_*` 함수는 matplotlib Axes 에 카테고리 고유의 배경 일러스트를
그리는 순수 드로잉 헬퍼다. 외부 부수효과가 없고, numpy 시드가 함수 내부에서
고정되므로 결정적이다. 테스트는 실제 Agg 백엔드 Axes 를 넘겨 호출한 뒤
아티스트(patches/lines/texts)가 실제로 추가됐는지 검증한다.

MEMORY `feedback_golden_master_hermetic` 교훈: 이 모듈은 `_render_generated_image`
디스크 probe 나 파일시스템에 의존하지 않으므로 골든마스터/디스크 patch 가 불필요하다.
"""

import os
import sys

import pytest

# scripts/ 를 경로에 추가 (conftest 와 동일하게 `from common.X` 임포트 지원)
_SCRIPTS_DIR = os.path.join(os.path.dirname(__file__), "..", "scripts")
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, os.path.abspath(_SCRIPTS_DIR))

try:
    import matplotlib

    matplotlib.use("Agg")  # headless 렌더 백엔드 (CI 안전)
    import matplotlib.pyplot as plt

    from common import og_visuals as v

    _IMPORT_OK = True
except Exception:  # pragma: no cover - 의존성 부재 시 스킵
    plt = None  # type: ignore
    v = None  # type: ignore
    _IMPORT_OK = False

pytestmark = pytest.mark.skipif(not _IMPORT_OK, reason="matplotlib/og_visuals unavailable")

_ACCENT = "#58a6ff"


@pytest.fixture
def ax():
    """headless Agg Axes fixture — 각 테스트 후 figure 를 닫아 자원 누수 방지."""
    fig, _ax = plt.subplots(figsize=(12, 6.3), dpi=100)
    yield _ax
    plt.close(fig)


def _artist_count(_ax) -> int:
    """Axes 에 추가된 드로잉 아티스트(patch/line/text) 총합."""
    return len(_ax.patches) + len(_ax.lines) + len(_ax.texts)


# ---------------------------------------------------------------------------
# 1. accent-only 시그니처 함수 — 파라미터라이즈로 일괄 커버
# ---------------------------------------------------------------------------

_ACCENT_ONLY_FUNCS = [
    "_draw_visual_crypto",
    "_draw_visual_regulatory",
    "_draw_visual_social",
    "_draw_visual_defi",
    "_draw_visual_political",
    "_draw_visual_world",
    "_draw_visual_security",
    "_draw_visual_blockchain",
    "_draw_visual_economic_calendar",
    "_draw_visual_default",
    "_draw_visual_geopolitical",
]


@pytest.mark.parametrize("func_name", _ACCENT_ONLY_FUNCS)
def test_accent_only_visual_draws_artists(ax, func_name):
    func = getattr(v, func_name)
    before = _artist_count(ax)
    func(ax, _ACCENT)
    after = _artist_count(ax)
    assert after > before, f"{func_name} 이 아티스트를 추가하지 않음"


@pytest.mark.parametrize("func_name", _ACCENT_ONLY_FUNCS)
def test_accent_only_visual_is_deterministic(ax, func_name):
    """numpy 시드가 내부 고정이므로 두 번 호출 시 동일 개수의 아티스트를 추가."""
    func = getattr(v, func_name)
    fig1, ax1 = plt.subplots()
    fig2, ax2 = plt.subplots()
    try:
        func(ax1, _ACCENT)
        func(ax2, _ACCENT)
        assert len(ax1.patches) == len(ax2.patches)
        assert len(ax1.lines) == len(ax2.lines)
        assert len(ax1.texts) == len(ax2.texts)
    finally:
        plt.close(fig1)
        plt.close(fig2)


# ---------------------------------------------------------------------------
# 2. _draw_visual_stock — data(kospi) 분기
# ---------------------------------------------------------------------------


def test_stock_without_data(ax):
    v._draw_visual_stock(ax, _ACCENT)
    assert _artist_count(ax) > 0
    # data 없으면 기본 "KOSPI" 라벨
    labels = [t.get_text() for t in ax.texts]
    assert "KOSPI" in labels


def test_stock_with_kospi_data(ax):
    v._draw_visual_stock(ax, _ACCENT, {"kospi": "2,500"})
    labels = [t.get_text() for t in ax.texts]
    assert "KOSPI 2,500" in labels


def test_stock_with_empty_data_falls_back(ax):
    # kospi 키 없는 dict → 기본 라벨 유지
    v._draw_visual_stock(ax, _ACCENT, {"other": 1})
    labels = [t.get_text() for t in ax.texts]
    assert "KOSPI" in labels


# ---------------------------------------------------------------------------
# 3. _draw_visual_analysis — data(fear_greed) 게이지 분기
# ---------------------------------------------------------------------------


def test_analysis_without_data_uses_default_score(ax):
    v._draw_visual_analysis(ax, _ACCENT)
    labels = [t.get_text() for t in ax.texts]
    # 기본 fear_greed 62 → "62" 텍스트
    assert "62" in labels


def test_analysis_with_fear_greed_data(ax):
    v._draw_visual_analysis(ax, _ACCENT, {"fear_greed": 30.0})
    labels = [t.get_text() for t in ax.texts]
    assert "30" in labels


@pytest.mark.parametrize("score", [0.0, 50.0, 100.0])
def test_analysis_fear_greed_boundary_scores(ax, score):
    v._draw_visual_analysis(ax, _ACCENT, {"fear_greed": score})
    labels = [t.get_text() for t in ax.texts]
    assert str(int(score)) in labels


# ---------------------------------------------------------------------------
# 4. 레지스트리 정합성 — _CATEGORY_VISUALS 의 모든 값이 호출 가능
# ---------------------------------------------------------------------------


def test_category_registry_all_callable(ax):
    from common.og_compose import _CATEGORY_VISUALS

    for category, func in _CATEGORY_VISUALS.items():
        fig, a = plt.subplots()
        try:
            func(a, _ACCENT)
            assert _artist_count(a) > 0, f"{category} 비주얼이 비어 있음"
        finally:
            plt.close(fig)
