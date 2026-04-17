import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import check_recent_post_urls as crpu
import requests


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_collect_post_files_filters_to_recent_days(tmp_path):
    today = datetime.now(UTC).date()
    recent = tmp_path / f"{today}.md"
    yesterday = tmp_path / f"{today - timedelta(days=1)}.md"
    older = tmp_path / f"{today - timedelta(days=3)}.md"

    for path in (recent, yesterday, older):
        _write_text(path, "body")

    result = crpu.collect_post_files(tmp_path, 2)

    assert result == sorted([recent, yesterday])


def test_extract_urls_deduplicates_and_preserves_order(tmp_path):
    first = tmp_path / "one.md"
    second = tmp_path / "two.md"
    _write_text(first, "https://a.example/x and https://b.example/y")
    _write_text(second, "https://b.example/y and https://c.example/z")

    assert crpu.extract_urls([first, second]) == [
        "https://a.example/x",
        "https://b.example/y",
        "https://c.example/z",
    ]


def test_valid_url_accepts_http_and_https_only():
    assert crpu.valid_url("https://example.com") is True
    assert crpu.valid_url("http://example.com/path") is True
    assert crpu.valid_url("mailto:test@example.com") is False
    assert crpu.valid_url("https:///broken") is False


def test_check_url_handles_success_fallback_and_request_exception(monkeypatch):
    head_calls = []
    get_calls = []

    class Response:
        def __init__(self, status_code):
            self.status_code = status_code

    def fake_head(url, timeout, allow_redirects):
        head_calls.append((url, timeout, allow_redirects))
        if url.endswith("/fallback"):
            return Response(403)
        if url.endswith("/explode"):
            raise requests.RequestException("boom")
        return Response(200)

    def fake_get(url, timeout, allow_redirects):
        get_calls.append((url, timeout, allow_redirects))
        return Response(503)

    monkeypatch.setattr(crpu.requests, "head", fake_head)
    monkeypatch.setattr(crpu.requests, "get", fake_get)

    assert crpu.check_url("https://example.com/ok", 3.0) == (200, None)
    assert crpu.check_url("https://example.com/fallback", 3.0) == (503, "server_error")
    status, reason = crpu.check_url("https://example.com/explode", 3.0)
    assert status is None
    assert "boom" in reason
    assert len(head_calls) == 3
    assert len(get_calls) == 1


def test_main_writes_report_with_invalid_and_failed_urls(tmp_path, monkeypatch, capsys):
    today = datetime.now(UTC).date()
    posts_dir = tmp_path / "_posts"
    report_path = tmp_path / "_state" / "recent-url-quality.txt"
    _write_text(
        posts_dir / f"{today}-demo.md",
        "\n".join(
            [
                "https://good.example/article",
                "https://bad.example/article",
                "https:///broken",
            ]
        ),
    )

    def fake_check_url(url: str, timeout: float) -> tuple[int | None, str | None]:
        assert timeout == 4.5
        if "bad.example" in url:
            return 503, "server_error"
        if "broken" in url:
            return None, "bad url"
        return 200, None

    monkeypatch.setattr(crpu, "check_url", fake_check_url)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "check_recent_post_urls.py",
            "--posts-dir",
            str(posts_dir),
            "--days",
            "1",
            "--limit",
            "5",
            "--timeout",
            "4.5",
            "--report",
            str(report_path),
        ],
    )

    assert crpu.main() == 0

    report = report_path.read_text(encoding="utf-8")
    assert "posts_checked=1" in report
    assert "unique_urls=3" in report
    assert "invalid_format=1" in report
    assert "live_failures=2" in report
    assert "[invalid]" in report
    assert "[failures]" in report
    output = capsys.readouterr().out
    assert "URL quality summary" in output
    assert f"- report={report_path}" in output
