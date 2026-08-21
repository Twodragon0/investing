"""`check_pilot_observation.py` 의 포착률 지표 단위 테스트.

## 왜 절감 %가 아니라 포착률인가

파일럿 후 4실행(2026-08-11 시점)의 skip 비율로 절감을 재면 95% 신뢰구간 폭이 0.53
이다 — 51.9%(파일럿 전 실측 no-op 비율)와 25%를 구분하지 못한다. 표본이 커지길
기다려도 해상도는 √n 으로만 늘어서, regulatory 단독으로 30일을 관측해야 폭 0.20에
닿는다.

포착률은 표본이 작아도 판정된다. 묻는 것이 비율이 아니라 **사건의 유무**이기
때문이다:

- **누출** — 파일럿 후에도 화이트리스트 부분집합 커밋이 남아 있는가. 1건이라도
  있으면 skip 이 동작하지 않은 것이다. (git 만으로 판정)
- **오검출** — skip 이 화이트리스트 **밖의** 파일까지 버렸는가. 1건이라도 있으면
  dedup 상태나 콘텐츠가 유실된 것이다. (gh 로그 필요)

둘 다 "0이어야 한다" 는 단언이라 n=4 로도 반증 가능하다.

## 이 파일이 지키는 것

- 화이트리스트를 이 스크립트에 **복사하면** 액션과 조용히 어긋난다. 액션에서 읽어야
  한다. 읽기에 실패했을 때 빈 집합으로 폴백하면 모든 `_state`-only 커밋이 "부분집합
  아님" 이 되어 누출 0건 — **거짓 PASS** 다. 반드시 None 이어야 한다.
- 액션 본문이 에코된 로그 줄을 실제 skip 출력으로 세면 오검출 판정이 오염된다.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

_ROOT = Path(__file__).parent.parent
_TOOLS = _ROOT / "scripts" / "tools"
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))
if str(_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(_ROOT / "scripts"))

import check_pilot_observation as cpo  # noqa: E402

_KST = timezone(timedelta(hours=9))
_PILOT = datetime(2026, 8, 10, 13, 14, 51, tzinfo=_KST)

_METRICS = "_state/image_rejection_metrics.json"
_CACHE = "_state/translation_cache.json"
_DEDUP = "_state/regulatory_news_seen.json"


# ---------------------------------------------------------------------------
# 화이트리스트는 액션에서 읽는다
# ---------------------------------------------------------------------------


def test_whitelist_is_read_from_action_not_copied():
    """액션의 `NOOP_STATE_PATHS` 를 실제로 읽어온다."""
    whitelist = cpo.read_noop_whitelist()
    assert whitelist, "화이트리스트를 액션에서 읽지 못했다"
    assert all(p.startswith("_state/") for p in whitelist), f"_state/ 밖 경로: {whitelist}"
    assert not any(p.endswith("_seen.json") for p in whitelist), (
        f"화이트리스트에 dedup 상태가 있다: {whitelist}. 이건 별도 가드의 관할이지만, "
        "여기서도 걸리면 포착률 판정 자체가 무의미해진다."
    )


def test_whitelist_read_failure_is_none_not_empty(monkeypatch, tmp_path):
    """읽기 실패 시 빈 집합으로 폴백하면 누출 0건 거짓 PASS 가 난다."""
    monkeypatch.setattr(cpo, "ACTION_PATH", tmp_path / "does_not_exist.yml")
    assert cpo.read_noop_whitelist() is None


def test_whitelist_read_failure_on_unparseable_action(monkeypatch, tmp_path):
    bogus = tmp_path / "action.yml"
    bogus.write_text("name: python-collect\nruns:\n  using: composite\n", encoding="utf-8")
    monkeypatch.setattr(cpo, "ACTION_PATH", bogus)
    assert cpo.read_noop_whitelist() is None


# ---------------------------------------------------------------------------
# 커밋 분류
# ---------------------------------------------------------------------------


_WHITELIST = frozenset({_METRICS, _CACHE})


def test_classify_whitelist_subset_is_noop():
    assert cpo.classify_commit([_METRICS, _CACHE], _WHITELIST) == "noop"
    assert cpo.classify_commit([_METRICS], _WHITELIST) == "noop"


def test_classify_dedup_mixed_is_not_noop():
    """dedup 이 섞이면 커밋돼야 한다 — no-op 으로 세면 절감 상한이 부풀려진다."""
    assert cpo.classify_commit([_METRICS, _CACHE, _DEDUP], _WHITELIST) == "state_other"


def test_classify_content_wins_over_state():
    assert cpo.classify_commit(["_posts/2026-08-11-x.md", _METRICS], _WHITELIST) == "content"
    assert cpo.classify_commit(["assets/images/generated/x.avif", _CACHE], _WHITELIST) == "content"


def test_classify_empty_is_not_noop():
    """빈 커밋을 noop 으로 세면 누출 카운트가 허위로 늘어난다."""
    assert cpo.classify_commit([], _WHITELIST) != "noop"


# ---------------------------------------------------------------------------
# 누출 — 파일럿 후 no-op 커밋
# ---------------------------------------------------------------------------


def _commit(day: int, hour: int, sha: str, paths: list[str]) -> cpo.CollectorCommit:
    return cpo.CollectorCommit(when=datetime(2026, 8, day, hour, 0, tzinfo=_KST), sha=sha, paths=tuple(paths))


def test_leaks_counts_only_post_pilot_noop_commits():
    commits = [
        _commit(9, 7, "aaa", [_METRICS, _CACHE]),  # 전 — 누출 아님
        _commit(11, 7, "bbb", [_METRICS, _CACHE]),  # 후 no-op — 누출
        _commit(11, 8, "ccc", [_METRICS, _DEDUP]),  # 후 dedup — 정상
        _commit(11, 9, "ddd", ["_posts/x.md"]),  # 후 콘텐츠 — 정상
    ]
    leaks, counts = cpo.find_leaks(commits, _PILOT, _WHITELIST)
    assert [c.sha for c in leaks] == ["bbb"]
    assert counts == {"noop": 1, "state_other": 1, "content": 1}


def test_no_leaks_when_skip_works():
    commits = [
        _commit(11, 8, "ccc", [_METRICS, _DEDUP]),
        _commit(11, 9, "ddd", ["_posts/x.md"]),
    ]
    leaks, counts = cpo.find_leaks(commits, _PILOT, _WHITELIST)
    assert leaks == []
    assert counts.get("noop", 0) == 0


# ---------------------------------------------------------------------------
# 오검출 — skip 이 화이트리스트 밖까지 버렸는가
# ---------------------------------------------------------------------------


_RUNTIME_LOG = "\n".join(
    [
        'collect\t2026-08-10T13:41:05.4151194Z \x1b[36;1m    echo "No-op state churn only — skipping commit:"\x1b[0m',
        "collect\t2026-08-10T13:41:05.4151195Z \x1b[36;1m    git diff --staged --name-only | sed 's/^/  /'\x1b[0m",
        "collect\t2026-08-10T13:41:05.9587871Z No-op state churn only — skipping commit:",
        "collect\t2026-08-10T13:41:05.9611230Z   _state/image_rejection_metrics.json",
        "collect\t2026-08-10T13:41:05.9611918Z   _state/translation_cache.json",
        "collect\t2026-08-10T13:41:06.0000000Z Post-commit summary",
    ]
)


def test_parse_skip_paths_extracts_runtime_block():
    blocks = cpo.parse_skip_paths(_RUNTIME_LOG)
    assert blocks == [[_METRICS, _CACHE]], f"실제 파싱: {blocks}"


def test_parse_skip_paths_ignores_echoed_action_body():
    """에코된 스크립트 본문만 있는 로그에서는 skip 블록이 나오면 안 된다."""
    echoed_only = "\n".join(
        [
            'collect\t2026-08-10T13:41:05.4151194Z \x1b[36;1m    echo "No-op state churn only — skipping commit:"\x1b[0m',
            "collect\t2026-08-10T13:41:05.4151195Z \x1b[36;1m    git diff --staged --name-only\x1b[0m",
        ]
    )
    assert cpo.parse_skip_paths(echoed_only) == []


def test_overreach_flags_paths_outside_whitelist():
    assert cpo.find_overreach([[_METRICS, _CACHE]], _WHITELIST) == []
    assert cpo.find_overreach([[_METRICS, _DEDUP]], _WHITELIST) == [[_METRICS, _DEDUP]]


def test_overreach_flags_empty_skip_block():
    """파일 목록이 비어 있으면 무엇을 버렸는지 알 수 없다 — 안전 쪽으로 flag."""
    assert cpo.find_overreach([[]], _WHITELIST) == [[]]


# ---------------------------------------------------------------------------
# 배선 — 화이트리스트를 못 읽으면 판정하지 않는다
# ---------------------------------------------------------------------------


def test_report_capture_rate_skips_when_whitelist_unreadable(monkeypatch, caplog):
    monkeypatch.setattr(cpo, "read_noop_whitelist", lambda: None)
    monkeypatch.setattr(cpo, "collect_collector_commits", lambda *_a, **_k: [])

    verdict = cpo.report_capture_rate(["regulatory"], 7, {"regulatory": _PILOT}, skip_blocks=None)

    assert verdict is None, "화이트리스트를 못 읽었는데 판정을 냈다 — 거짓 PASS"


def test_report_capture_rate_reports_leak(monkeypatch):
    monkeypatch.setattr(cpo, "read_noop_whitelist", lambda: _WHITELIST)
    monkeypatch.setattr(
        cpo,
        "collect_collector_commits",
        lambda *_a, **_k: [_commit(11, 7, "bbb", [_METRICS, _CACHE])],
    )

    verdict = cpo.report_capture_rate(["regulatory"], 7, {"regulatory": _PILOT}, skip_blocks=None)

    assert verdict is False, "누출 1건인데 PASS 로 판정했다"


def test_report_capture_rate_passes_when_clean(monkeypatch):
    monkeypatch.setattr(cpo, "read_noop_whitelist", lambda: _WHITELIST)
    monkeypatch.setattr(
        cpo,
        "collect_collector_commits",
        lambda *_a, **_k: [_commit(11, 8, "ccc", [_METRICS, _DEDUP])],
    )

    verdict = cpo.report_capture_rate(["regulatory"], 7, {"regulatory": _PILOT}, skip_blocks=[[_METRICS, _CACHE]])

    assert verdict is True


def test_report_capture_rate_fails_on_overreach(monkeypatch):
    """누출이 0이어도 오검출이 있으면 PASS 가 아니다."""
    monkeypatch.setattr(cpo, "read_noop_whitelist", lambda: _WHITELIST)
    monkeypatch.setattr(cpo, "collect_collector_commits", lambda *_a, **_k: [])

    verdict = cpo.report_capture_rate(["regulatory"], 7, {"regulatory": _PILOT}, skip_blocks=[[_METRICS, _DEDUP]])

    assert verdict is False, "오검출 1건인데 PASS 로 판정했다"
