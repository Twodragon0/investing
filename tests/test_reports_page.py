"""E2E integration tests for the reports page rendered HTML.

Validates that all major features are present in the built _site/reports/index.html.
No browser needed - tests the static HTML/JS/CSS output directly.
"""

import os

import pytest

SITE_DIR = os.path.join(os.path.dirname(__file__), "..", "_site")
REPORTS_HTML = os.path.join(SITE_DIR, "reports", "index.html")
RSS_FEED = os.path.join(SITE_DIR, "reports-feed.xml")


@pytest.fixture(scope="module")
def reports_html():
    if not os.path.exists(REPORTS_HTML):
        pytest.skip("_site not built; run `bundle exec jekyll build` first")
    with open(REPORTS_HTML, encoding="utf-8") as f:
        return f.read()


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
    def test_has_debounce(self, reports_html):
        assert "_searchTimer" in reports_html
        assert "setTimeout" in reports_html

    def test_has_highlight_function(self, reports_html):
        assert "highlightText" in reports_html
        assert "search-highlight" in reports_html


class TestViewModes:
    def test_has_view_toggle_buttons(self, reports_html):
        assert 'data-view="grid"' in reports_html
        assert 'data-view="list"' in reports_html

    def test_has_list_view_class(self, reports_html):
        assert "reports-list-view" in reports_html


class TestBookmarks:
    def test_has_bookmark_button(self, reports_html):
        assert "report-bookmark" in reports_html
        assert "toggleBookmark" in reports_html

    def test_has_bookmark_count_badge(self, reports_html):
        assert "bookmark-count-badge" in reports_html
        assert "updateBookmarkBadge" in reports_html

    def test_uses_localstorage(self, reports_html):
        assert "report-bookmarks" in reports_html
        assert "localStorage" in reports_html


class TestInfiniteScroll:
    def test_has_intersection_observer(self, reports_html):
        assert "IntersectionObserver" in reports_html
        assert "scroll-sentinel" in reports_html

    def test_has_load_more_button(self, reports_html):
        assert 'id="load-more-btn"' in reports_html


class TestSkeletonLoading:
    def test_has_skeleton_cards(self, reports_html):
        assert "skeleton-card" in reports_html


class TestRelativeTime:
    def test_has_relative_time(self, reports_html):
        assert "relativeTime" in reports_html
        assert "report-relative-time" in reports_html


class TestKeyboardNavigation:
    def test_has_arrow_key_handling(self, reports_html):
        assert "ArrowDown" in reports_html
        assert "ArrowUp" in reports_html
        assert "focusedCardIndex" in reports_html

    def test_has_slash_search_shortcut(self, reports_html):
        assert "e.key === '/'" in reports_html


class TestThemeSync:
    def test_has_mutation_observer(self, reports_html):
        assert "MutationObserver" in reports_html
        assert "data-theme" in reports_html

    def test_chart_reinit_on_theme(self, reports_html):
        assert "themeObserver" in reports_html


class TestHashFiltering:
    def test_has_hash_support(self, reports_html):
        assert "applyHash" in reports_html
        assert "hashchange" in reports_html
        assert "updateHash" in reports_html


class TestHighlightsSection:
    def test_has_highlights(self, reports_html):
        assert "reports-highlights" in reports_html
        assert "highlights-grid" in reports_html


class TestRecentlyViewed:
    def test_has_recent_section(self, reports_html):
        assert "reports-recent" in reports_html
        assert "report-recent" in reports_html  # localStorage key


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
