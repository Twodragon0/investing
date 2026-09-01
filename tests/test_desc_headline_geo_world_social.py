"""`description_ko` 헤드라인이 영어로 새지 않는지 검증한다 (geo / worldmonitor / social).

세 수집기는 `description_ko` 앞머리에 최상위 아이템의 헤드라인을 붙인다. 그 조회가
각각 `title_ko or title_translated or title` 로 적혀 있어서, 번역본이 없으면 원문
**영어** 제목으로 조용히 폴백했다. 언어가 바뀐 사실을 아무도 확인하지 않았고, 그게
`scripts/check_description_quality.py` 의 "ASCII 과다 desc" 로 나타났다.

`common.headline.select_korean_headline` 이 그 조회의 단일 창구다. 한국어를 못 얻으면
`""` 를 돌려주고, 각 호출부에 이미 있는 "헤드라인 없음" 분기가 대신 실행된다.

## 왜 `run()` 을 통째로 도는가

헤드라인 조립은 `run()` 안에 인라인으로 있어서 직접 부를 수 있는 함수가 없다. 손으로
만든 입력을 헬퍼에 바로 먹이면 수집기가 실제로 그 헬퍼를 **쓰는지** 는 증명되지 않는다
(호출부를 되돌려도 초록으로 남는다). 그래서 fetch 계층만 대체하고 `run()` 이 계산한
`description_ko` 를 관측한다.

## 네트워크 / 디스크

fetch 함수를 모듈 네임스페이스에서 대체해 HTTP 계층에 닿기 전에 끊는다
(`tests/conftest.py` 의 `HTTPAdapter.send` 차단은 최후 방어선). `translate_to_korean`
은 `common.headline` 네임스페이스에서 대체한다 — 번역 실패(fail-open, 원문 반환)가
이 버그의 방아쇠이므로 그 동작을 명시적으로 재현한다.

포스트는 `post_generator.POSTS_DIR` 을 tmp 로 돌려서 쓰고, 브리핑 카드 생성은
막는다(안 막으면 `assets/images/generated/` 에 실제 PNG/WEBP/AVIF 를 쓴다).
`_state/` 는 conftest autouse 가 이미 tmp 로 보낸다.
"""

from __future__ import annotations

import importlib
from typing import Any, Dict, List

import pytest

from common.summary_quality import is_ascii_heavy

geo = importlib.import_module("collect_geopolitical")
wm = importlib.import_module("collect_worldmonitor_news")
sm = importlib.import_module("collect_social_media")

_ENGLISH_TITLES = [
    "Iran sanctions tighten as nuclear standoff deepens",
    "NATO allies weigh new eastern flank deployments",
    "Oil prices surge on Strait of Hormuz disruption fears",
    "Fed signals prolonged restrictive policy stance",
]
_KOREAN_TITLES = [
    "이란 제재 강화로 핵 협상 교착 심화",
    "나토 동맹국, 동부 전선 추가 배치 검토",
    "호르무즈 해협 차질 우려에 유가 급등",
    "연준, 긴축 기조 장기화 시사",
]


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def isolated_posts(tmp_path, monkeypatch):
    """`create_post` 가 저장소 `_posts/` 대신 tmp 에 쓰게 한다."""
    from common import post_generator as pg

    posts = tmp_path / "_posts"
    posts.mkdir()
    monkeypatch.setattr(pg, "POSTS_DIR", str(posts))
    return posts


@pytest.fixture
def no_image_writes(monkeypatch):
    """브리핑 카드 생성을 막는다 — 켜두면 저장소 `assets/` 트리를 오염시킨다."""
    import common.image_generator as ig

    monkeypatch.setattr(ig, "generate_news_briefing_card", lambda *_a, **_kw: "")


@pytest.fixture
def translation_fails_open(monkeypatch):
    """`translate_to_korean` 이 원문을 그대로 돌려주는 상태 (translator.py fail-open).

    번역 서비스가 꺼져 있거나 에러일 때의 실제 동작이며, 영어 제목이 한국어 설명에
    새어 들어가던 바로 그 조건이다.
    """
    import common.headline as headline_mod

    monkeypatch.setattr(headline_mod, "translate_to_korean", lambda t: t)


@pytest.fixture
def translation_succeeds(monkeypatch):
    """영어 제목을 한국어로 번역해 주는 상태."""
    import common.headline as headline_mod

    mapping = dict(zip(_ENGLISH_TITLES, _KOREAN_TITLES, strict=True))
    monkeypatch.setattr(headline_mod, "translate_to_korean", lambda t: mapping.get(t, t))


def _spy_create_post(collector, monkeypatch) -> Dict[str, Any]:
    """`create_post` 인자를 캡처한다 (원래 동작 유지).

    최종 파일에서 읽으면 안 된다 — `post_generator` 가 generic-description 정책으로
    값을 갈아치울 수 있어 `run()` 이 무엇을 계산했는지 관측할 수 없게 된다.
    """
    captured: Dict[str, Any] = {}
    original = collector.create_post

    def spy(**kwargs):
        captured.update(kwargs)
        return original(**kwargs)

    monkeypatch.setattr(collector, "create_post", spy)
    return captured


# ---------------------------------------------------------------------------
# collect_geopolitical — "핵심 이슈: {headline}. 총 N건 …"
# ---------------------------------------------------------------------------


@pytest.fixture
def geo_no_network(monkeypatch):
    """지정학 수집기의 세 소스를 전부 대체한다. 기본값은 '빈 결과'."""
    state: Dict[str, Any] = {"markets": [], "gdelt": [], "news": []}
    monkeypatch.setattr(geo, "fetch_polymarket", lambda **_kw: list(state["markets"]))
    monkeypatch.setattr(geo, "fetch_gdelt", lambda **_kw: list(state["gdelt"]))
    monkeypatch.setattr(geo, "fetch_google_news_geopolitical", lambda: list(state["news"]))
    monkeypatch.setattr(geo, "enrich_items", lambda items, ctx, **_kw: items)
    return state


def _geo_news(titles: List[str]) -> List[Dict[str, Any]]:
    return [{"title": t, "link": f"https://example.com/{i}"} for i, t in enumerate(titles)]


def _run_geo(monkeypatch) -> str:
    collector = geo.GeopoliticalCollector()
    monkeypatch.setattr(collector, "is_duplicate_exact", lambda *_a, **_kw: False)
    captured = _spy_create_post(collector, monkeypatch)
    collector.run()
    return captured["extra_frontmatter"]["description_ko"]


class TestGeopoliticalDescription:
    def test_english_headline_is_not_used_as_lead(
        self, isolated_posts, geo_no_network, no_image_writes, translation_fails_open, monkeypatch
    ) -> None:
        """번역이 실패하면 영어 헤드라인 대신 헤드라인 없는 분기가 돌아야 한다."""
        geo_no_network["news"] = _geo_news(_ENGLISH_TITLES)
        desc = _run_geo(monkeypatch)

        assert "핵심 이슈:" not in desc, desc
        assert desc.startswith("지정학적 리스크 4건 수집"), desc
        for title in _ENGLISH_TITLES:
            assert title not in desc, desc
        assert is_ascii_heavy(desc) is False, desc

    def test_translated_english_headline_leads_in_korean(
        self, isolated_posts, geo_no_network, no_image_writes, translation_succeeds, monkeypatch
    ) -> None:
        """번역이 되면 그 한국어 헤드라인이 앞머리에 온다 (기능 상실 아님)."""
        geo_no_network["news"] = _geo_news(_ENGLISH_TITLES)
        desc = _run_geo(monkeypatch)

        assert desc.startswith(f"핵심 이슈: {_KOREAN_TITLES[0]}."), desc
        assert _ENGLISH_TITLES[0] not in desc, desc
        assert is_ascii_heavy(desc) is False, desc

    def test_korean_headline_is_kept(
        self, isolated_posts, geo_no_network, no_image_writes, translation_fails_open, monkeypatch
    ) -> None:
        geo_no_network["news"] = _geo_news(_KOREAN_TITLES)
        desc = _run_geo(monkeypatch)

        assert desc.startswith(f"핵심 이슈: {_KOREAN_TITLES[0]}."), desc
        assert is_ascii_heavy(desc) is False, desc

    def test_headline_trim_is_preserved_at_seventy_chars(
        self, isolated_posts, geo_no_network, no_image_writes, translation_fails_open, monkeypatch
    ) -> None:
        """헬퍼는 자르지 않는다 — 호출부의 `[:70]` 이 그대로 살아 있어야 한다."""
        long_title = "이란 제재 강화 동향 " * 20
        geo_no_network["news"] = _geo_news([long_title] * 4)
        desc = _run_geo(monkeypatch)

        headline = desc[len("핵심 이슈: ") :].split(". 총 ")[0]
        assert len(headline) == 70, (len(headline), headline)

    def test_english_gdelt_headline_is_not_used_as_lead(
        self, isolated_posts, geo_no_network, no_image_writes, translation_fails_open, monkeypatch
    ) -> None:
        """GDELT 는 영문 소스다 — 같은 `_desc_ko` 를 먹이므로 같은 가드가 필요하다."""
        geo_no_network["gdelt"] = [{"title": t, "tone": -1.0} for t in _ENGLISH_TITLES]
        desc = _run_geo(monkeypatch)

        assert "핵심 이슈:" not in desc, desc
        assert is_ascii_heavy(desc) is False, desc

    def test_english_polymarket_headline_is_not_used_as_lead(
        self, isolated_posts, geo_no_network, no_image_writes, translation_fails_open, monkeypatch
    ) -> None:
        """Polymarket 질문도 영문이며 세 번째 폴백으로 같은 자리에 들어간다."""
        geo_no_network["markets"] = [{"title": t, "volume": 10_000, "probability": 0.6} for t in _ENGLISH_TITLES]
        desc = _run_geo(monkeypatch)

        assert "핵심 이슈:" not in desc, desc
        assert is_ascii_heavy(desc) is False, desc


# ---------------------------------------------------------------------------
# collect_worldmonitor_news — "{a}; {b} 등 핵심 이슈 포함."
# ---------------------------------------------------------------------------

_WM_CLAUSE = "등 핵심 이슈 포함"


@pytest.fixture
def wm_no_network(monkeypatch):
    state: Dict[str, Any] = {"items": []}
    monkeypatch.setattr(wm, "fetch_worldmonitor_feeds", lambda: list(state["items"]))
    monkeypatch.setattr(wm, "fetch_worldmonitor_map_snapshot", lambda days=7: {})
    monkeypatch.setattr(wm, "enrich_items", lambda items, *a, **kw: None)
    return state


def _wm_items(titles: List[str]) -> List[Dict[str, Any]]:
    return [
        {
            "title": t,
            "description": "본문 설명입니다.",
            "link": f"https://worldmonitor.app/{i}",
            "source": f"WorldMonitor/Src{i}",
            "tags": ["worldmonitor", "geopolitics"],
        }
        for i, t in enumerate(titles)
    ]


def _run_wm(monkeypatch) -> str:
    collector = wm.WorldMonitorCollector()
    monkeypatch.setattr(collector, "is_duplicate_exact", lambda *_a, **_kw: False)
    captured: Dict[str, Any] = {}
    original = collector.post_gen.create_post

    def spy(**kwargs):
        captured.update(kwargs)
        return original(**kwargs)

    monkeypatch.setattr(collector.post_gen, "create_post", spy)
    collector.run()
    return captured["extra_frontmatter"]["description_ko"]


class TestWorldMonitorDescription:
    def test_all_english_headlines_drop_the_clause(
        self, isolated_posts, wm_no_network, no_image_writes, translation_fails_open, monkeypatch
    ) -> None:
        """헤드라인이 전부 영어면 절 자체가 사라져야 한다.

        빈 문자열을 그냥 이어붙이면 `"; "` 나 내용 없는 `" 등 핵심 이슈 포함."` 이
        남는다 — 그 두 형태를 모두 거부한다.
        """
        wm_no_network["items"] = _wm_items(_ENGLISH_TITLES)
        desc = _run_wm(monkeypatch)

        assert _WM_CLAUSE not in desc, desc
        assert "; " not in desc, desc
        for title in _ENGLISH_TITLES:
            assert title not in desc, desc
        assert is_ascii_heavy(desc) is False, desc

    def test_korean_headlines_keep_the_clause(
        self, isolated_posts, wm_no_network, no_image_writes, translation_fails_open, monkeypatch
    ) -> None:
        wm_no_network["items"] = _wm_items(_KOREAN_TITLES)
        desc = _run_wm(monkeypatch)

        assert _WM_CLAUSE in desc, desc
        assert _KOREAN_TITLES[0][:40] in desc, desc
        assert is_ascii_heavy(desc) is False, desc

    def test_mixed_headlines_produce_no_empty_separator(
        self, isolated_posts, wm_no_network, no_image_writes, translation_fails_open, monkeypatch
    ) -> None:
        """한국어 1개 + 영어 1개면 절은 남되 빈 항목이 끼면 안 된다."""
        wm_no_network["items"] = _wm_items([_KOREAN_TITLES[0], _ENGLISH_TITLES[3]])
        desc = _run_wm(monkeypatch)

        assert "; ;" not in desc, desc
        assert "; 등" not in desc, desc
        assert _ENGLISH_TITLES[3] not in desc, desc
        assert is_ascii_heavy(desc) is False, desc

    def test_headline_trim_is_preserved_at_forty_chars(
        self, isolated_posts, wm_no_network, no_image_writes, translation_fails_open, monkeypatch
    ) -> None:
        """헬퍼는 자르지 않는다 — 호출부의 `[:40]` 이 그대로 살아 있어야 한다."""
        long_title = "이란 제재 강화 동향 " * 20
        wm_no_network["items"] = _wm_items([long_title])
        desc = _run_wm(monkeypatch)

        headline = desc.split(_WM_CLAUSE)[0].rsplit(". ", 1)[-1].strip()
        assert len(headline) <= 40, (len(headline), headline)
        assert headline == long_title[:40].rstrip(), headline


# ---------------------------------------------------------------------------
# collect_social_media — "화제: {headline}"
# ---------------------------------------------------------------------------


@pytest.fixture
def sm_no_network(monkeypatch):
    state: Dict[str, Any] = {"items": []}
    monkeypatch.setattr(sm, "is_playwright_available", lambda: False)
    monkeypatch.setattr(sm, "fetch_telegram_channel", lambda ch, limit=10: [])
    monkeypatch.setattr(sm, "fetch_twitter_search", lambda token, q, limit=10: [])
    monkeypatch.setattr(sm, "fetch_google_news_social", list)
    monkeypatch.setattr(sm, "fetch_reddit_posts", lambda limit=10: list(state["items"]))
    monkeypatch.setattr(sm, "fetch_political_economy_news", list)
    monkeypatch.setattr(sm, "enrich_items", lambda items, *a, **kw: None)
    return state


def _sm_items(titles: List[str]) -> List[Dict[str, Any]]:
    return [
        {
            "title": t,
            "description": "본문 설명입니다.",
            "link": f"https://reddit.com/r/x/{i}",
            "source": f"r/src{i}",
            "tags": ["social-media", "reddit"],
            "score": 5000 - i,
        }
        for i, t in enumerate(titles)
    ]


def _run_sm(monkeypatch) -> str:
    collector = sm.SocialMediaCollector()
    monkeypatch.setattr(collector, "is_duplicate_exact", lambda *_a, **_kw: False)
    captured = _spy_create_post(collector, monkeypatch)
    collector.run()
    return captured["extra_frontmatter"]["description_ko"]


class TestSocialMediaDescription:
    def test_english_headline_is_not_used_as_topic(
        self, isolated_posts, sm_no_network, no_image_writes, translation_fails_open, monkeypatch
    ) -> None:
        """번역 fail-open 시 영어 원문을 `화제:` 로 되붙이면 안 된다.

        기존 코드는 `if not _social_top_title: _social_top_title = _social_raw` 로
        원문을 **명시적으로** 되살렸다 — 이 클래스의 가장 직접적인 사례다.
        """
        sm_no_network["items"] = _sm_items(_ENGLISH_TITLES)
        desc = _run_sm(monkeypatch)

        assert "화제:" not in desc, desc
        for title in _ENGLISH_TITLES:
            assert title not in desc, desc
        assert is_ascii_heavy(desc) is False, desc

    def test_translated_english_headline_becomes_korean_topic(
        self, isolated_posts, sm_no_network, no_image_writes, translation_succeeds, monkeypatch
    ) -> None:
        sm_no_network["items"] = _sm_items(_ENGLISH_TITLES)
        desc = _run_sm(monkeypatch)

        assert "화제: " in desc, desc
        topic = desc.split("화제: ", 1)[1]
        assert topic and topic in _KOREAN_TITLES[0], (topic, desc)
        assert is_ascii_heavy(desc) is False, desc

    def test_korean_headline_is_kept_as_topic(
        self, isolated_posts, sm_no_network, no_image_writes, translation_fails_open, monkeypatch
    ) -> None:
        sm_no_network["items"] = _sm_items(_KOREAN_TITLES)
        desc = _run_sm(monkeypatch)

        assert "화제: " in desc, desc
        topic = desc.split("화제: ", 1)[1]
        assert topic in _KOREAN_TITLES[0], (topic, desc)
        assert is_ascii_heavy(desc) is False, desc

    def test_headline_trim_is_preserved_at_seventy_chars(
        self, isolated_posts, sm_no_network, no_image_writes, translation_fails_open, monkeypatch
    ) -> None:
        """헬퍼는 자르지 않는다 — 호출부의 70자 word-boundary 절단이 살아 있어야 한다."""
        long_title = "이란 제재 강화 동향 " * 20
        sm_no_network["items"] = _sm_items([long_title])
        desc = _run_sm(monkeypatch)

        topic = desc.split("화제: ", 1)[1]
        assert len(topic) <= 70, (len(topic), topic)
