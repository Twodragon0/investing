"""수집기 ``description_ko`` 헤드라인이 영어로 새지 않는지 검증.

``collect_political_trades`` / ``collect_crypto_news`` 는 ``description_ko`` 앞머리에
최상위 항목의 헤드라인을 붙인다. 기존 호출부는 ``title_ko or title_translated or
title`` 을 각자 적어두었고, 번역본이 없으면 원문 영어 제목으로 조용히 폴백했다.
언어가 바뀐 사실을 아무도 확인하지 않아 ``scripts/check_description_quality.py`` 의
"ASCII 과다 desc" 로 이어졌다.

각 호출부마다 세 가지를 확인한다.

1. 영어 전용 최상위 항목은 영어 헤드라인 리드 없이 기존의 "건수/테마" 분기로 떨어진다.
2. 한국어 최상위 항목은 헤드라인 리드를 유지한다.
3. 결과 ``description_ko`` 가 ``is_ascii_heavy`` 기준을 넘지 않는다.

``common.headline.translate_to_korean`` 은 항상 패치한다. 실서비스 번역기는
fail-open(실패 시 원문 반환)이므로, 번역 불가 상황은 ``side_effect=lambda t: t`` 로
재현한다.
"""

import importlib
from unittest.mock import patch

from common.summary_quality import is_ascii_heavy

# 번역본이 없는 영어 원문 제목 — 폴백이 그대로 노출하던 값.
_ENGLISH_TITLE = "Pelosi discloses fresh Nvidia call options ahead of earnings"
_ENGLISH_MARKER = "Pelosi"

_ENGLISH_CRYPTO_TITLE = "Bitcoin spot ETF inflows extend for a third straight session"
_ENGLISH_CRYPTO_MARKER = "Bitcoin spot ETF"

_ENGLISH_SECURITY_TITLE = "Curve Finance bridge exploit drains user deposits"
_ENGLISH_SECURITY_MARKER = "Curve Finance bridge exploit"

_KOREAN_TITLE = "펠로시 의원, 실적 발표 앞두고 엔비디아 콜옵션 추가 공시"
_KOREAN_CRYPTO_TITLE = "비트코인 현물 ETF 순유입 3거래일 연속 확대"
_KOREAN_SECURITY_TITLE = "커브 파이낸스 브리지 해킹으로 예치금 유출"


def _no_translation(text: str) -> str:
    """실패한 번역기를 재현한다 — 입력을 그대로 돌려준다(fail-open)."""
    return text


# ---------------------------------------------------------------------------
# Site 1 — collect_political_trades.run(): _desc_ko
# ---------------------------------------------------------------------------


def _political_desc(items):
    """``run()`` 을 구동해 front matter 의 ``description_ko`` 를 돌려준다."""
    mod = importlib.import_module("collect_political_trades")
    collector = mod.PoliticalTradesCollector()
    captured = {}

    def _capture(**kwargs):
        captured.update(kwargs)
        return "created-political-post.md"  # 진위만 쓰이는 sentinel — 파일을 만들지 않는다

    with (
        patch.object(collector, "fetch", return_value=items),
        patch.object(collector, "process", return_value=items),
        patch.object(collector, "is_duplicate_exact", return_value=False),
        patch.object(collector, "_build_full_content", return_value="본문"),
        patch.object(collector, "create_post", side_effect=_capture),
        patch.object(collector, "mark_seen"),
        patch.object(collector, "save_state"),
        patch.object(collector, "log_summary"),
        patch("common.image_generator.generate_news_briefing_card", return_value=""),
        patch("common.headline.translate_to_korean", side_effect=_no_translation),
    ):
        collector.run()

    return captured["extra_frontmatter"]["description_ko"]


def test_political_english_top_item_drops_headline_lead():
    """번역본 없는 영어 제목은 리드로 쓰이지 않고 건수 분기로 떨어진다."""
    items = [
        {"title": _ENGLISH_TITLE, "tags": ["congress"], "ticker": "NVDA", "source": "capitoltrades"},
        {"title": "Senate aide files late disclosure", "tags": ["senate"], "source": "capitoltrades"},
    ]
    desc = _political_desc(items)

    assert _ENGLISH_MARKER not in desc
    # 헤드라인 없는 기존 분기가 그대로 살아 있어야 한다.
    assert desc.startswith("정치인 거래·정책 동향 2건 수집.")
    assert "최다 거래 종목: NVDA." in desc


def test_political_korean_top_item_keeps_headline_lead():
    items = [
        {"title_ko": _KOREAN_TITLE, "title": _ENGLISH_TITLE, "tags": ["congress"], "ticker": "NVDA"},
    ]
    desc = _political_desc(items)

    assert desc.startswith(_KOREAN_TITLE)
    assert _ENGLISH_MARKER not in desc


def test_political_desc_is_not_ascii_heavy():
    english_only = [
        {"title": _ENGLISH_TITLE, "tags": ["congress"], "ticker": "NVDA"},
    ]
    korean = [
        {"title_ko": _KOREAN_TITLE, "title": _ENGLISH_TITLE, "tags": ["congress"], "ticker": "NVDA"},
    ]

    assert is_ascii_heavy(_political_desc(english_only)) is False
    assert is_ascii_heavy(_political_desc(korean)) is False


def test_political_translated_title_is_used_as_lead():
    """``title_translated`` 만 있는 항목도 리드를 잃지 않는다."""
    items = [{"title_translated": _KOREAN_TITLE, "title": _ENGLISH_TITLE, "tags": ["congress"]}]
    desc = _political_desc(items)

    assert desc.startswith(_KOREAN_TITLE)


# ---------------------------------------------------------------------------
# Site 2 — collect_crypto_news._build_security_description(): _desc_ko_b
# ---------------------------------------------------------------------------


def _security_desc(google_items, rekt_items=None):
    mod = importlib.import_module("collect_crypto_news")
    with patch("common.headline.translate_to_korean", side_effect=_no_translation):
        return mod._build_security_description(rekt_items or [], google_items)


def test_security_english_top_item_drops_headline_lead():
    google_items = [
        {"title": _ENGLISH_SECURITY_TITLE, "description": "no funds metadata"},
        {"title": "Another advisory", "description": ""},
    ]
    desc = _security_desc(google_items)

    assert _ENGLISH_SECURITY_MARKER not in desc
    # 헤드라인이 없으면 건수 문장만 남아야 하고, 빈 리드로 ". " 가 앞에 붙으면 안 된다.
    assert desc == "블록체인 보안 뉴스 2건 분석."
    assert not desc.startswith(".")


def test_security_korean_top_item_keeps_headline_lead():
    google_items = [{"title_ko": _KOREAN_SECURITY_TITLE, "title": _ENGLISH_SECURITY_TITLE, "description": ""}]
    desc = _security_desc(google_items)

    assert desc.startswith(_KOREAN_SECURITY_TITLE)
    assert _ENGLISH_SECURITY_MARKER not in desc


def test_security_desc_is_not_ascii_heavy():
    english_only = [{"title": _ENGLISH_SECURITY_TITLE, "description": ""}]
    korean = [{"title_ko": _KOREAN_SECURITY_TITLE, "title": _ENGLISH_SECURITY_TITLE, "description": ""}]

    assert is_ascii_heavy(_security_desc(english_only)) is False
    assert is_ascii_heavy(_security_desc(korean)) is False


def test_security_rekt_funds_branch_is_unchanged():
    """Funds Lost 메타데이터가 있는 rekt 항목은 기존 동작을 유지한다."""
    rekt_items = [{"title": "[Security] Curve", "description": "Funds Lost: $40M | Date: 2026-08-01"}]
    desc = _security_desc([], rekt_items)

    assert desc.startswith("Curve $40M 피해 발생")


# ---------------------------------------------------------------------------
# Site 3 — collect_crypto_news.run(): _desc_ko_a
# ---------------------------------------------------------------------------


def _crypto_desc(items):
    mod = importlib.import_module("collect_crypto_news")
    collector = mod.CryptoNewsCollector()
    captured = {}

    def _capture(**kwargs):
        captured.update(kwargs)
        return "created-crypto-post.md"  # 진위만 쓰이는 sentinel — 파일을 만들지 않는다

    with (
        patch.object(collector, "fetch", return_value=items),
        patch.object(collector, "process", side_effect=lambda x: x),
        # 보안 항목을 비워 Post B 분기를 건드리지 않는다.
        patch.object(collector, "fetch_security", return_value=([], [])),
        patch.object(collector, "is_duplicate_exact", return_value=False),
        patch.object(collector, "_build_crypto_content", return_value=("본문", "")),
        patch.object(collector, "create_post", side_effect=_capture),
        patch.object(collector, "mark_seen"),
        patch.object(collector, "save_state"),
        patch("common.headline.translate_to_korean", side_effect=_no_translation),
    ):
        collector.run()

    return captured["extra_frontmatter"]["description_ko"]


def test_crypto_english_top_item_drops_headline_lead():
    items = [
        {"title": _ENGLISH_CRYPTO_TITLE, "source": "CoinDesk"},
        {"title": "Ether staking yields slip", "source": "The Block"},
    ]
    desc = _crypto_desc(items)

    assert _ENGLISH_CRYPTO_MARKER not in desc
    assert desc.startswith("크립토 뉴스 2건 수집. 주요 출처:")


def test_crypto_korean_top_item_keeps_headline_lead():
    items = [
        {"title_ko": _KOREAN_CRYPTO_TITLE, "title": _ENGLISH_CRYPTO_TITLE, "source": "CoinDesk"},
    ]
    desc = _crypto_desc(items)

    assert desc.startswith(_KOREAN_CRYPTO_TITLE)
    assert _ENGLISH_CRYPTO_MARKER not in desc


def test_crypto_desc_is_not_ascii_heavy():
    english_only = [{"title": _ENGLISH_CRYPTO_TITLE, "source": "CoinDesk"}]
    korean = [{"title_ko": _KOREAN_CRYPTO_TITLE, "title": _ENGLISH_CRYPTO_TITLE, "source": "CoinDesk"}]

    assert is_ascii_heavy(_crypto_desc(english_only)) is False
    assert is_ascii_heavy(_crypto_desc(korean)) is False


def test_crypto_translated_title_is_used_as_lead():
    """``get_display_title`` 은 ``title_translated`` 를 읽지 않아 번역본을 잃었다."""
    items = [{"title_translated": _KOREAN_CRYPTO_TITLE, "title": _ENGLISH_CRYPTO_TITLE, "source": "CoinDesk"}]
    desc = _crypto_desc(items)

    assert desc.startswith(_KOREAN_CRYPTO_TITLE)
