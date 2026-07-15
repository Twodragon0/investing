"""Unit tests for scripts/common/og_compose.py (표준 OG 이미지 합성).

`generate_og_image` 는 matplotlib 로 1200x630 OG 이미지를 렌더한 뒤 저장하고,
포맷 변환([[og_image_formats]])과 R2 미러링([[asset_storage]])을 호출한다.
테스트는 실제 Agg 백엔드로 렌더하되, 디스크 밖 부수효과(포맷 변환·미러링)는
patch 로 고정한다 (MEMORY `feedback_golden_master_hermetic` 교훈 — 파일시스템/외부
probe 의존을 제거해 결정적·격리 상태로 검증).

`_draw_data_chips` 는 렌더 경로 내부에서만 호출되므로, 메트릭이 담긴 description
을 넘겨 `generate_og_image` 를 통해 커버한다.
"""

import os
import sys
from unittest.mock import patch

import pytest

# scripts/ 를 경로에 추가 (conftest 와 동일하게 `from common.X` 임포트 지원)
_SCRIPTS_DIR = os.path.join(os.path.dirname(__file__), "..", "scripts")
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, os.path.abspath(_SCRIPTS_DIR))

try:
    import matplotlib

    matplotlib.use("Agg")  # headless 렌더 백엔드 (CI 안전)

    from common import og_compose as c

    _IMPORT_OK = True
except Exception:  # pragma: no cover - 의존성 부재 시 스킵
    c = None  # type: ignore
    _IMPORT_OK = False

pytestmark = pytest.mark.skipif(not _IMPORT_OK, reason="matplotlib/og_compose unavailable")


# ---------------------------------------------------------------------------
# 순수 헬퍼: safe_text / wrap_text
# ---------------------------------------------------------------------------


def test_safe_text_escapes_dollar():
    assert c.safe_text("BTC $100") == r"BTC \$100"


def test_safe_text_no_dollar_unchanged():
    assert c.safe_text("plain text") == "plain text"


def test_wrap_text_short_not_wrapped():
    assert c.wrap_text("hello", max_width=20, max_lines=2) == ["hello"]


def test_wrap_text_truncates_long_last_line_with_ellipsis():
    # 마지막 라인이 (max_width-3) 보다 길면 자른 뒤 "..." 부착
    text = "abcdefghij klmnopqrst uvwxyz1234"
    lines = c.wrap_text(text, max_width=10, max_lines=1)
    assert len(lines) == 1
    assert lines[0].endswith("...")


def test_wrap_text_short_last_line_gets_ellipsis_only():
    # max_lines 초과 + 마지막 라인이 짧음 → else 분기(rstrip + "...")
    text = "aaaa bb cccccccc"
    lines = c.wrap_text(text, max_width=10, max_lines=1)
    assert lines == ["aaaa bb..."]


# ---------------------------------------------------------------------------
# _extract_metrics — description 파싱
# ---------------------------------------------------------------------------


def test_extract_metrics_empty():
    assert c._extract_metrics("") == []


def test_extract_metrics_caps_at_three():
    desc = "BTC $50,000 공포탐욕: 40/100 KOSPI 2,500 (+1.2%) VIX 30 달러지수 104"
    metrics = c._extract_metrics(desc)
    assert len(metrics) == 3
    assert all(len(m) == 3 for m in metrics)


def test_extract_metrics_news_count():
    # "N건 수집" 패턴 → NEWS 메트릭
    metrics = c._extract_metrics("오늘 총 12건 수집 완료")
    assert ("NEWS", "12건", "#8b5cf6") in metrics


# ---------------------------------------------------------------------------
# generate_og_image — 전체 렌더 경로 (I/O patch 로 격리)
# ---------------------------------------------------------------------------


@pytest.fixture
def patched_io():
    """포맷 변환·R2 미러링을 no-op 으로 고정 (디스크/네트워크 격리)."""
    with (
        patch.object(c, "_convert_formats_parallel") as m_conv,
        patch.object(c.asset_storage, "mirror_generated_variants") as m_mirror,
    ):
        yield m_conv, m_mirror


def test_generate_og_image_success(tmp_path, patched_io):
    m_conv, m_mirror = patched_io
    out = str(tmp_path / "crypto-news.png")
    ok = c.generate_og_image(
        title="비트코인 급등 소식",
        date_str="2026-07-15",
        category="crypto-news",
        description="BTC $50,000 수집 12건",
        output_path=out,
    )
    assert ok is True
    assert os.path.exists(out)
    m_conv.assert_called_once()
    m_mirror.assert_called_once()


def test_generate_og_image_with_metrics_draws_chips(tmp_path, patched_io):
    # 메트릭이 담긴 description → _draw_data_chips 경로 커버
    out = str(tmp_path / "market-analysis.png")
    ok = c.generate_og_image(
        title="시장 분석",
        date_str="2026-07-15",
        category="market-analysis",
        description="공포탐욕: 25/100 KOSPI 2,600 (+0.5%) BTC $48,000",
        output_path=out,
    )
    assert ok is True
    assert os.path.exists(out)


def test_generate_og_image_empty_description(tmp_path, patched_io):
    # description 없음 → desc_lines/visual_data 빈 분기
    out = str(tmp_path / "stock-news.png")
    ok = c.generate_og_image(
        title="주식 뉴스",
        date_str="2026-07-15",
        category="stock-news",
        description="",
        output_path=out,
    )
    assert ok is True


def test_generate_og_image_unknown_category_uses_default(tmp_path, patched_io):
    # 미등록 카테고리 → DEFAULT_ACCENT + _draw_visual_default
    out = str(tmp_path / "unknown-thing.png")
    ok = c.generate_og_image(
        title="Unknown",
        date_str="2026-07-15",
        category="not-a-real-category",
        description="",
        output_path=out,
    )
    assert ok is True


def test_generate_og_image_slug_override(tmp_path, patched_io):
    # 파일명 slug 가 override 키를 포함 → 전용 visual 함수 선택 분기
    out = str(tmp_path / "2026-07-15-fmp-economic-calendar.png")
    ok = c.generate_og_image(
        title="경제 캘린더",
        date_str="2026-07-15",
        category="market-analysis",
        description="",
        output_path=out,
    )
    assert ok is True


def test_generate_og_image_long_title_multiline(tmp_path, patched_io):
    # 긴 제목 → title_lines 2줄 분기 + 긴 description 2줄 분기
    out = str(tmp_path / "worldmonitor.png")
    ok = c.generate_og_image(
        title="아주 긴 제목입니다 " * 5,
        date_str="2026-07-15",
        category="worldmonitor",
        description="아주 긴 설명입니다 " * 8,
        output_path=out,
    )
    assert ok is True


def test_generate_og_image_returns_false_when_mpl_unavailable(tmp_path, monkeypatch):
    # matplotlib 부재 시 즉시 False (렌더 시도 안 함)
    monkeypatch.setattr(c, "_MPL_AVAILABLE", False)
    out = str(tmp_path / "crypto-news.png")
    ok = c.generate_og_image(
        title="x",
        date_str="2026-07-15",
        category="crypto-news",
        description="",
        output_path=out,
    )
    assert ok is False
    assert not os.path.exists(out)


def test_generate_og_image_returns_false_on_save_error(tmp_path, patched_io):
    # output_path 가 디렉터리 → savefig 가 OSError(IsADirectoryError) → False
    target_dir = tmp_path / "isdir.png"
    target_dir.mkdir()
    ok = c.generate_og_image(
        title="x",
        date_str="2026-07-15",
        category="crypto-news",
        description="",
        output_path=str(target_dir),
    )
    assert ok is False


# ---------------------------------------------------------------------------
# 레지스트리 정합성 — 색/라벨 매핑이 카테고리별로 존재
# ---------------------------------------------------------------------------


def test_category_colors_and_labels_aligned():
    # 모든 색 키는 라벨 키에도 존재해야 함 (렌더 시 KeyError 방지)
    assert set(c.CATEGORY_COLORS).issubset(set(c.CATEGORY_LABELS))
