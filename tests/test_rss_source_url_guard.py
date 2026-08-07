"""`<source url="">` in Google News RSS names the publisher, not the article.

    <item>
      <title>코스피 6,600선 회복 - 산경투데이</title>
      <link>https://news.google.com/rss/articles/CBMi…</link>
      <source url="https://www.sankyungtoday.com">산경투데이</source>
    </item>

The `url` attribute is the outlet's site. Storing it as the item's original URL
had two measured consequences (2026-08-07):

* `summarizer` writes it as the p0 alert link — **264 of 909** p0 links (29%)
  pointed at a homepage instead of the story.
* `enrichment` prefers it over the Google News link when fetching a
  description, so the homepage's `og:description` — the outlet's own tagline —
  became the article summary. That is where the site-chrome blurbs come from
  (FT/CoinDesk/Fortune self-introductions), the class `summary_quality` filters
  after the fact.

The backfill surfaced it: re-fetching `https://www.sedaily.com` returned
whatever was on the front page that minute, so one published blurb ended up
describing a different article entirely.

Direction: presence — a `<source url>` that does point at an item is still
accepted; only bare domains are dropped.
"""

from __future__ import annotations

import pytest

from common.rss_fetcher import _is_article_url


@pytest.mark.parametrize(
    "url",
    [
        # The shape actually seen in Google News RSS `<source url>`.
        "https://www.sedaily.com",
        "https://www.sankyungtoday.com/",
        "https://thehill.com",
        "http://biz.chosun.com/",
        "https://finance.yahoo.com",
    ],
)
def test_bare_domains_are_not_article_urls(url: str) -> None:
    assert _is_article_url(url) is False


@pytest.mark.parametrize(
    "url",
    [
        "https://www.sedaily.com/NewsView/2ABCDEFG",
        "https://biz.chosun.com/stock/market_trend/2026/08/07/ABCDEF/",
        "https://news.google.com/rss/articles/CBMiZ0FVX3lxTFBV",
        # A query string identifies a specific item even without a path.
        "https://example.com?idxno=12345",
        "https://example.com/?articleId=42",
    ],
)
def test_item_urls_are_article_urls(url: str) -> None:
    assert _is_article_url(url) is True


def test_empty_and_malformed_are_rejected() -> None:
    assert _is_article_url("") is False
    assert _is_article_url("not a url") is True, (
        "a bare word parses as a path, which is harmless here — `is_safe_url` "
        "rejects non-http schemes before this check runs"
    )
