"""tests/test_post_loop_to_slack.py — post_loop_to_slack 단위 테스트.

이 모듈은 0% 커버리지였다. 두 가지가 조용히 깨질 수 있어서 덮는다:

* `_sanitize_message` — Slack 은 3000바이트 상한을 **거절**로 응답하므로, 절단이
  깨지면 매시간 루프 게시가 통째로 실패한다. 절단은 바이트 기준이라 한글에서
  멀티바이트 경계를 밟는데, `errors="ignore"` 가 그걸 흡수한다.
* `main()` 의 경로 탈출 가드 — `--message-path` 는 워크플로우 입력에서 온다.

네트워크는 타지 않는다. `slack_api` 를 대체하고, `urlopen` 을 검증할 때만 가짜로
바꾼다. `main()` 이 `__file__` 로 프로젝트 루트를 계산하므로 모듈의 `__file__` 을
tmp 로 돌려 저장소 트리에 쓰지 않게 한다.
"""

from __future__ import annotations

import io
import json
import urllib.parse

import post_loop_to_slack as plts
import pytest

# ---------------------------------------------------------------------------
# _sanitize_message
# ---------------------------------------------------------------------------


class TestSanitizeMessage:
    def test_plain_text_is_unchanged(self):
        assert plts._sanitize_message("hello world") == "hello world"

    def test_korean_text_is_unchanged(self):
        assert plts._sanitize_message("한국어 메시지") == "한국어 메시지"

    @pytest.mark.parametrize("char", ["\t", "\n", "\r"])
    def test_whitespace_control_chars_survive(self, char):
        assert plts._sanitize_message(f"a{char}b") == f"a{char}b"

    @pytest.mark.parametrize("char", ["\x00", "\x07", "\x08", "\x0b", "\x0c", "\x1b", "\x7f"])
    def test_other_control_chars_are_stripped(self, char):
        assert plts._sanitize_message(f"a{char}b") == "ab"

    def test_message_at_the_limit_is_not_truncated(self):
        text = "a" * plts.MAX_MESSAGE_BYTES
        assert plts._sanitize_message(text) == text

    def test_oversized_message_is_truncated_with_a_marker(self):
        result = plts._sanitize_message("a" * (plts.MAX_MESSAGE_BYTES + 100))
        assert result.endswith("\n...(truncated)")
        assert len(result.encode("utf-8")) <= plts.MAX_MESSAGE_BYTES

    def test_truncation_is_byte_wise_not_char_wise(self):
        """한글은 3바이트라 문자 수 기준으로 자르면 상한을 넘긴다."""
        result = plts._sanitize_message("가" * plts.MAX_MESSAGE_BYTES)
        assert len(result.encode("utf-8")) <= plts.MAX_MESSAGE_BYTES

    def test_truncation_never_emits_broken_utf8(self):
        """멀티바이트 경계를 밟아도 디코딩 가능한 문자열이 나와야 한다."""
        result = plts._sanitize_message("가" * plts.MAX_MESSAGE_BYTES)
        result.encode("utf-8").decode("utf-8")  # raises on broken output

    def test_control_chars_are_stripped_before_size_check(self):
        raw = "\x00" * 5000 + "short"
        assert plts._sanitize_message(raw) == "short"

    def test_empty_stays_empty(self):
        assert plts._sanitize_message("") == ""


# ---------------------------------------------------------------------------
# find_root_thread_ts
# ---------------------------------------------------------------------------


class TestFindRootThreadTs:
    def test_prefers_thread_ts_over_ts(self):
        messages = [{"text": "[ultrawork-loop] x", "thread_ts": "111.1", "ts": "222.2"}]
        assert plts.find_root_thread_ts(messages, "[ultrawork-loop]") == "111.1"

    def test_falls_back_to_ts(self):
        messages = [{"text": "[ultrawork-loop] x", "ts": "222.2"}]
        assert plts.find_root_thread_ts(messages, "[ultrawork-loop]") == "222.2"

    def test_returns_the_first_match(self):
        messages = [
            {"text": "unrelated", "ts": "1.0"},
            {"text": "[ultrawork-loop] a", "ts": "2.0"},
            {"text": "[ultrawork-loop] b", "ts": "3.0"},
        ]
        assert plts.find_root_thread_ts(messages, "[ultrawork-loop]") == "2.0"

    def test_no_match_returns_none(self):
        assert plts.find_root_thread_ts([{"text": "unrelated", "ts": "1.0"}], "[marker]") is None

    def test_empty_history_returns_none(self):
        assert plts.find_root_thread_ts([], "[marker]") is None

    def test_match_without_any_timestamp_returns_none(self):
        assert plts.find_root_thread_ts([{"text": "[marker] x"}], "[marker]") is None

    def test_message_without_text_is_skipped(self):
        assert plts.find_root_thread_ts([{"ts": "1.0"}], "[marker]") is None


# ---------------------------------------------------------------------------
# slack_api
# ---------------------------------------------------------------------------


class _FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False


class TestSlackApi:
    @pytest.fixture
    def captured(self, monkeypatch):
        seen: dict[str, object] = {}

        def fake_urlopen(req, timeout=None):
            seen["req"] = req
            seen["timeout"] = timeout
            return _FakeResponse(json.dumps({"ok": True}).encode())

        monkeypatch.setattr(plts.urllib.request, "urlopen", fake_urlopen)
        return seen

    def test_returns_decoded_json(self, captured):
        assert plts.slack_api("chat.postMessage", "token-placeholder", {"channel": "C1"}) == {"ok": True}

    def test_posts_to_the_named_method(self, captured):
        plts.slack_api("conversations.history", "token-placeholder", {})
        assert captured["req"].full_url == f"{plts.SLACK_API_BASE}/conversations.history"
        assert captured["req"].get_method() == "POST"

    def test_sends_bearer_token(self, captured):
        plts.slack_api("chat.postMessage", "token-placeholder", {})
        assert captured["req"].headers["Authorization"] == "Bearer token-placeholder"

    def test_form_encodes_the_payload(self, captured):
        plts.slack_api("chat.postMessage", "token-placeholder", {"channel": "C1", "text": "가 나"})
        body = urllib.parse.parse_qs(captured["req"].data.decode("utf-8"))
        assert body == {"channel": ["C1"], "text": ["가 나"]}

    def test_uses_a_bounded_timeout(self, captured):
        plts.slack_api("chat.postMessage", "token-placeholder", {})
        assert captured["timeout"] == 20


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


class TestMain:
    @pytest.fixture
    def project(self, tmp_path, monkeypatch):
        """모듈의 `__file__` 을 tmp 로 돌려 프로젝트 루트를 tmp_path 로 만든다."""
        scripts = tmp_path / "scripts"
        scripts.mkdir()
        monkeypatch.setattr(plts, "__file__", str(scripts / "post_loop_to_slack.py"))
        monkeypatch.setenv("SLACK_BOT_TOKEN", "token-placeholder")
        return tmp_path

    @pytest.fixture
    def calls(self, monkeypatch):
        """`slack_api` 를 기록형 스텁으로 대체한다 (기본: 히스토리 빈 목록, 게시 성공)."""
        recorded: list[tuple[str, dict]] = []
        responses: dict[str, dict] = {
            "conversations.history": {"ok": True, "messages": []},
            "chat.postMessage": {"ok": True},
        }

        def fake(method, token, payload):
            recorded.append((method, payload))
            return responses[method]

        monkeypatch.setattr(plts, "slack_api", fake)
        return recorded, responses

    def _argv(self, monkeypatch, path, *extra):
        monkeypatch.setattr(
            "sys.argv",
            ["post_loop_to_slack.py", "--channel", "C123", "--message-path", str(path), *extra],
        )

    def test_missing_token_fails_fast(self, project, monkeypatch, capsys):
        monkeypatch.delenv("SLACK_BOT_TOKEN", raising=False)
        self._argv(monkeypatch, project / "msg.txt")

        assert plts.main() == 1
        assert "SLACK_BOT_TOKEN" in capsys.readouterr().out

    def test_path_outside_project_root_is_rejected(self, project, monkeypatch, tmp_path_factory, capsys):
        outside = tmp_path_factory.mktemp("outside") / "msg.txt"
        outside.write_text("hello", encoding="utf-8")
        self._argv(monkeypatch, outside)

        assert plts.main() == 1
        assert "must be within the project root" in capsys.readouterr().out

    def test_dotdot_in_the_raw_argument_is_rejected(self, project, monkeypatch, capsys):
        (project / "msg.txt").write_text("hello", encoding="utf-8")
        self._argv(monkeypatch, project / "scripts" / ".." / "msg.txt")

        assert plts.main() == 1
        assert "must be within the project root" in capsys.readouterr().out

    def test_empty_message_is_skipped_successfully(self, project, monkeypatch, calls, capsys):
        recorded, _ = calls
        (project / "msg.txt").write_text("   \n  ", encoding="utf-8")
        self._argv(monkeypatch, project / "msg.txt")

        assert plts.main() == 0
        assert recorded == [], "빈 메시지로 Slack 을 호출하면 안 된다"
        assert "skipping Slack post" in capsys.readouterr().out

    def test_posts_a_new_root_when_no_marker_found(self, project, monkeypatch, calls, capsys):
        recorded, _ = calls
        (project / "msg.txt").write_text("loop body", encoding="utf-8")
        self._argv(monkeypatch, project / "msg.txt")

        assert plts.main() == 0
        method, payload = recorded[-1]
        assert method == "chat.postMessage"
        assert payload == {"channel": "C123", "text": "loop body"}
        assert "new loop root message" in capsys.readouterr().out

    def test_replies_in_thread_when_marker_found(self, project, monkeypatch, calls, capsys):
        recorded, responses = calls
        responses["conversations.history"] = {
            "ok": True,
            "messages": [{"text": "[ultrawork-loop] previous", "ts": "1700.5"}],
        }
        (project / "msg.txt").write_text("loop body", encoding="utf-8")
        self._argv(monkeypatch, project / "msg.txt")

        assert plts.main() == 0
        assert recorded[-1][1]["thread_ts"] == "1700.5"
        assert "to Slack thread" in capsys.readouterr().out

    def test_custom_marker_is_honoured(self, project, monkeypatch, calls):
        recorded, responses = calls
        responses["conversations.history"] = {
            "ok": True,
            "messages": [{"text": "[other-loop] previous", "ts": "42.0"}],
        }
        (project / "msg.txt").write_text("body", encoding="utf-8")
        self._argv(monkeypatch, project / "msg.txt", "--marker", "[other-loop]")

        assert plts.main() == 0
        assert recorded[-1][1]["thread_ts"] == "42.0"

    def test_history_limit_is_clamped_to_at_least_one(self, project, monkeypatch, calls):
        """0 이나 음수를 그대로 넘기면 Slack 이 invalid_arguments 로 거절한다."""
        recorded, _ = calls
        (project / "msg.txt").write_text("body", encoding="utf-8")
        self._argv(monkeypatch, project / "msg.txt", "--history-limit", "0")

        assert plts.main() == 0
        assert recorded[0] == ("conversations.history", {"channel": "C123", "limit": "1"})

    def test_history_failure_exits_one(self, project, monkeypatch, calls, capsys):
        _, responses = calls
        responses["conversations.history"] = {"ok": False, "error": "invalid_auth"}
        (project / "msg.txt").write_text("body", encoding="utf-8")
        self._argv(monkeypatch, project / "msg.txt")

        assert plts.main() == 1
        assert "conversations.history failed" in capsys.readouterr().out

    def test_post_failure_exits_one(self, project, monkeypatch, calls, capsys):
        _, responses = calls
        responses["chat.postMessage"] = {"ok": False, "error": "channel_not_found"}
        (project / "msg.txt").write_text("body", encoding="utf-8")
        self._argv(monkeypatch, project / "msg.txt")

        assert plts.main() == 1
        assert "chat.postMessage failed" in capsys.readouterr().out

    def test_message_is_sanitized_before_posting(self, project, monkeypatch, calls):
        recorded, _ = calls
        (project / "msg.txt").write_text("clean\x00text", encoding="utf-8")
        self._argv(monkeypatch, project / "msg.txt")

        assert plts.main() == 0
        assert recorded[-1][1]["text"] == "cleantext"
