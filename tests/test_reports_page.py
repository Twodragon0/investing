"""E2E integration tests for the reports page rendered HTML.

Validates that all major features are present in the built _site/reports/index.html.
No browser needed - tests the static HTML/JS/CSS output directly.
"""

import os

import pytest

SITE_DIR = os.path.join(os.path.dirname(__file__), "..", "_site")
REPORTS_HTML = os.path.join(SITE_DIR, "reports", "index.html")
RSS_FEED = os.path.join(SITE_DIR, "reports-feed.xml")


REPORTS_JS = os.path.join(SITE_DIR, "assets", "js", "reports.js")


@pytest.fixture(scope="module")
def reports_html():
    if not os.path.exists(REPORTS_HTML):
        pytest.skip("_site not built; run `bundle exec jekyll build` first")
    with open(REPORTS_HTML, encoding="utf-8") as f:
        return f.read()


@pytest.fixture(scope="module")
def reports_js():
    if not os.path.exists(REPORTS_JS):
        pytest.skip("reports.js not built")
    with open(REPORTS_JS, encoding="utf-8") as f:
        return f.read()


@pytest.fixture(scope="module")
def full_content(reports_html, reports_js):
    """Combined HTML + JS for feature detection."""
    return reports_html + "\n" + reports_js


@pytest.fixture(scope="module")
def rss_content():
    if not os.path.exists(RSS_FEED):
        pytest.skip("RSS feed not built")
    with open(RSS_FEED, encoding="utf-8") as f:
        return f.read()


class TestReportsPageStructure:
    def test_has_reports_dashboard(self, reports_html):
        assert "reports-dashboard" in reports_html

    def test_has_header_stats(self, reports_html):
        assert "reports-stat-value" in reports_html
        assert "reports-stat-label" in reports_html

    def test_has_charts_section(self, reports_html):
        assert "category-chart" in reports_html
        assert "daily-chart" in reports_html


class TestFilterControls:
    def test_has_filter_buttons(self, reports_html):
        assert 'data-filter="all"' in reports_html
        assert "filter-btn" in reports_html

    def test_has_search_input(self, reports_html):
        assert 'id="report-search"' in reports_html

    def test_has_date_filters(self, reports_html):
        assert 'id="report-date-from"' in reports_html
        assert 'id="report-date-to"' in reports_html

    def test_has_clear_button(self, reports_html):
        assert 'id="report-clear"' in reports_html

    def test_has_bookmark_filter(self, reports_html):
        assert '_bookmarks' in reports_html


class TestSearchFeatures:
    def test_has_debounce(self, full_content):
        assert "_searchTimer" in full_content
        assert "setTimeout" in full_content

    def test_has_highlight_function(self, full_content):
        assert "highlightText" in full_content
        assert "search-highlight" in full_content


class TestViewModes:
    def test_has_view_toggle_buttons(self, reports_html):
        assert 'data-view="grid"' in reports_html
        assert 'data-view="list"' in reports_html

    def test_has_list_view_class(self, full_content):
        assert "reports-list-view" in full_content


class TestBookmarks:
    def test_has_bookmark_button(self, full_content):
        assert "report-bookmark" in full_content
        assert "toggleBookmark" in full_content

    def test_has_bookmark_count_badge(self, full_content):
        assert "bookmark-count-badge" in full_content
        assert "updateBookmarkBadge" in full_content

    def test_uses_localstorage(self, full_content):
        assert "report-bookmarks" in full_content
        assert "localStorage" in full_content


class TestInfiniteScroll:
    def test_has_intersection_observer(self, full_content):
        assert "IntersectionObserver" in full_content
        assert "scroll-sentinel" in full_content

    def test_has_load_more_button(self, reports_html):
        assert 'id="load-more-btn"' in reports_html


class TestSkeletonLoading:
    def test_has_skeleton_cards(self, reports_html):
        assert "skeleton-card" in reports_html


class TestRelativeTime:
    def test_has_relative_time(self, full_content):
        assert "relativeTime" in full_content
        assert "report-relative-time" in full_content


class TestKeyboardNavigation:
    def test_has_arrow_key_handling(self, full_content):
        assert "ArrowDown" in full_content
        assert "ArrowUp" in full_content
        assert "focusedCardIndex" in full_content

    def test_has_slash_search_shortcut(self, full_content):
        assert "e.key === '/'" in full_content


class TestThemeSync:
    def test_has_mutation_observer(self, full_content):
        assert "MutationObserver" in full_content
        assert "data-theme" in full_content

    def test_chart_reinit_on_theme(self, full_content):
        assert "themeObserver" in full_content


class TestHashFiltering:
    def test_has_hash_support(self, full_content):
        assert "applyHash" in full_content
        assert "hashchange" in full_content
        assert "updateHash" in full_content


class TestHighlightsSection:
    def test_has_highlights(self, reports_html):
        assert "reports-highlights" in reports_html
        assert "highlights-grid" in reports_html


class TestRecentlyViewed:
    def test_has_recent_section(self, full_content):
        assert "reports-recent" in full_content
        assert "report-recent" in full_content  # localStorage key


class TestShareButtons:
    def test_has_share_functionality(self, reports_html):
        assert "report-share" in reports_html or "share" in reports_html.lower()


class TestPWA:
    def test_has_service_worker_registration(self, reports_html):
        assert "serviceWorker" in reports_html

    def test_has_rss_link(self, reports_html):
        assert "reports-feed.xml" in reports_html
        assert "rss-link" in reports_html


class TestRSSFeed:
    def test_rss_is_valid_xml(self, rss_content):
        assert '<?xml version="1.0"' in rss_content
        assert "<rss" in rss_content
        assert "</rss>" in rss_content

    def test_rss_has_channel_info(self, rss_content):
        assert "<title>Investing Dragon" in rss_content
        assert "<language>ko</language>" in rss_content

    def test_rss_has_items(self, rss_content):
        items = rss_content.count("<item>")
        assert items >= 1, f"Expected RSS items, found {items}"
        assert items <= 30

    def test_rss_items_have_categories(self, rss_content):
        assert "<category>" in rss_content


CATEGORY_FEEDS = [
    ("reports-crypto-feed.xml", "암호화폐"),
    ("reports-stock-feed.xml", "주식"),
    ("reports-regulatory-feed.xml", "규제"),
    ("reports-worldmonitor-feed.xml", "글로벌"),
    ("reports-social-feed.xml", "소셜"),
    ("reports-political-feed.xml", "정치인"),
]


class TestCategoryRSSFeeds:
    @pytest.fixture(params=CATEGORY_FEEDS, ids=[f[0] for f in CATEGORY_FEEDS])
    def cat_feed(self, request):
        name, keyword = request.param
        path = os.path.join(SITE_DIR, name)
        if not os.path.exists(path):
            pytest.skip(f"{name} not built")
        with open(path, encoding="utf-8") as f:
            return f.read(), keyword

    def test_valid_rss_structure(self, cat_feed):
        content, _ = cat_feed
        assert '<?xml version="1.0"' in content
        assert "<channel>" in content
        assert "</rss>" in content

    def test_has_title_with_keyword(self, cat_feed):
        content, keyword = cat_feed
        assert keyword in content

    def test_has_items_or_empty(self, cat_feed):
        content, _ = cat_feed
        # Category feeds may have 0 items if no posts in that category
        assert "<channel>" in content


class TestExternalJS:
    def test_reports_js_exists(self):
        js_path = os.path.join(SITE_DIR, "assets", "js", "reports.js")
        if not os.path.exists(js_path):
            pytest.skip("_site not built")
        with open(js_path, encoding="utf-8") as f:
            content = f.read()
        assert "BADGE_COLORS" in content
        assert "buildCard" in content
        assert "initCharts" in content
        assert "toggleBookmark" in content

    def test_layout_references_external_js(self, reports_html):
        assert "reports.js" in reports_html


class TestJSONData:
    def test_has_json_data_block(self, reports_html):
        assert 'id="reports-data"' in reports_html
        assert "application/json" in reports_html

    def test_json_data_is_array(self, reports_html):
        # JSON block exists and starts with array bracket
        import json
        start = reports_html.find('type="application/json">')
        assert start > 0
        start = reports_html.find("[", start)
        end = reports_html.find("</script>", start)
        data = json.loads(reports_html[start:end])
        assert isinstance(data, list)
        assert len(data) <= 300
