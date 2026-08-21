"""FSC 피드의 후보 URL 회귀 가드.

배경: `www.fsc.go.kr` 은 GitHub Actions 러너에서 connect timeout(15s)이 잦다.
일일 포스트는 그날 아침(KST) 런 하나가 쓰기 때문에, 아침 런이 타임아웃하면 그날
포스트에서 한국 규제 항목이 통째로 빠진다 (2026-08-08·08-09 실제 발생).

이 파일이 지키는 불변식 두 개:

1. FSC 피드에는 후보 URL 이 있고, 그 호스트가 기본 URL 과 **다르다**. 같은 호스트를
   한 번 더 넣는 것은 connect timeout 앞에서 15초를 더 쓰고 똑같이 실패할 뿐이라
   후보로서 무의미하다.
2. `fetch_region_feeds` 가 그 후보를 실제로 `fetch_rss_feed` 에 넘긴다. 매핑만
   있고 전달되지 않으면 조용히 아무 일도 하지 않는다.
"""

import importlib
import os
import sys
from urllib.parse import urlparse

SCRIPTS_DIR = os.path.join(os.path.dirname(__file__), "..", "scripts")
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

FSC_FEED_NAMES = ("금융위원회 보도자료", "금융위원회 보도참고")


def _primary_url(mod, source_name: str) -> str:
    for url, name, _tags in mod.KOREA_FEEDS:
        if name == source_name:
            return url
    raise AssertionError(f"KOREA_FEEDS 에 {source_name!r} 이(가) 없다")


def test_fsc_feeds_declare_fallback():
    """두 FSC 피드 모두 후보 URL 을 선언한다."""
    mod = importlib.import_module("collect_regulatory")
    for name in FSC_FEED_NAMES:
        fallbacks = mod.FEED_FALLBACKS.get(name)
        assert fallbacks, f"{name}: 후보 URL 이 선언되지 않았다"
        assert all(f.strip() for f in fallbacks), f"{name}: 빈 후보 URL"


def test_fsc_fallback_uses_different_host():
    """후보 URL 의 호스트가 기본 URL 과 달라야 한다 — 이 가드의 핵심."""
    mod = importlib.import_module("collect_regulatory")
    for name in FSC_FEED_NAMES:
        primary_host = urlparse(_primary_url(mod, name)).hostname
        assert primary_host, f"{name}: 기본 URL 에 호스트가 없다"
        for fallback in mod.FEED_FALLBACKS[name]:
            fallback_host = urlparse(fallback).hostname
            assert fallback_host, f"{name}: 후보 URL 에 호스트가 없다 ({fallback})"
            assert fallback_host != primary_host, (
                f"{name}: 후보 URL 호스트가 기본과 같다({fallback_host}). "
                "connect timeout 은 호스트 단위로 나므로 같은 호스트는 후보가 되지 못한다."
            )


def test_fetch_region_feeds_passes_fallbacks(monkeypatch):
    """매핑이 실제로 fetch_rss_feed 까지 전달되는지 — 전달 누락은 조용한 실패다."""
    mod = importlib.import_module("collect_regulatory")
    seen: dict[str, object] = {}

    def fake_fetch(url, name, tags, limit=10, fallback_urls=None):
        seen[name] = fallback_urls
        return []

    monkeypatch.setattr(mod, "fetch_rss_feed", fake_fetch)
    monkeypatch.setattr(mod.time, "sleep", lambda _s: None)

    mod.fetch_region_feeds(mod.KOREA_FEEDS, "한국")

    for name in FSC_FEED_NAMES:
        assert name in seen, f"{name}: fetch_rss_feed 가 호출되지 않았다"
        assert seen[name] == mod.FEED_FALLBACKS[name], f"{name}: 후보 URL 이 전달되지 않았다 (받은 값: {seen[name]!r})"


def test_non_fsc_feed_gets_no_fallback(monkeypatch):
    """매핑에 없는 피드는 None 을 받는다 — 무관한 피드에 후보가 새지 않는다."""
    mod = importlib.import_module("collect_regulatory")
    seen: dict[str, object] = {}

    def fake_fetch(url, name, tags, limit=10, fallback_urls=None):
        seen[name] = fallback_urls
        return []

    monkeypatch.setattr(mod, "fetch_rss_feed", fake_fetch)
    monkeypatch.setattr(mod.time, "sleep", lambda _s: None)

    mod.fetch_region_feeds(mod.US_FEEDS, "미국")

    assert seen, "US_FEEDS 가 비어 있다"
    assert all(v is None for v in seen.values()), f"FSC 아닌 피드에 후보가 붙었다: {seen}"
