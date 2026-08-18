"""`check_pilot_observation.py` `[2]` 로그 병렬 수집의 단위 테스트.

## 왜 병렬로 바꿨는가

`--with-runs` 는 실행 하나당 `gh run view --log` 를 한 번 돈다. 순차로 돌리면
`--collector all`(수집기 4개) × `--run-limit` 12 = 최대 48회가 그대로 누적돼 분
단위가 되고, 그 대기 때문에 실제로는 `--with-runs` 없이 돌리게 된다. 그러면 `[2]`
의 skip 횟수와 `[5]` 의 오검출 판정이 통째로 빈다 — 2026-08-18 게이트 판정이
"오검출: 미확인" 으로 나온 이유다.

## 이 파일이 지키는 것

병렬화가 값을 바꾸면 안 된다. 세 가지가 깨지기 쉽다:

- **순서** — `as_completed` 로 받으면 blocks 가 로그 도착 순서를 타서 같은 데이터에서
  실행마다 다른 출력이 나온다. 오검출 목록의 재현 대조가 불가능해진다.
- **분모** — 로그를 못 받은 실행은 `checked` 에서 빠져야 한다. 빈 문자열로 폴백하면
  그 실행이 "skip 하지 않은 실행" 으로 분모에 들어가 비율이 희석된다.
- **경계** — 병렬화는 `filter_runs_after` 뒤에 온다. 파일럿 전 실행의 로그를 받으러
  가면 안 된다(느려질 뿐 아니라 분모가 틀린다).
"""

from __future__ import annotations

import sys
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

_ROOT = Path(__file__).parent.parent
_TOOLS = _ROOT / "scripts" / "tools"
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))
if str(_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(_ROOT / "scripts"))

import check_pilot_observation as cpo  # noqa: E402

KST = timezone(timedelta(hours=9))
PILOT = datetime.fromisoformat("2026-08-10T13:14:51+09:00")

SKIP_LOG = "collect\tRun script\tNo-op state churn only\ncollect\tRun script\t_state/translation_cache.json\n"
PLAIN_LOG = "collect\tRun script\tCommitted 3 files\n"


def _listing(*run_ids: int) -> str:
    import json

    return json.dumps(
        [
            {
                "databaseId": rid,
                "conclusion": "success",
                # 전부 파일럿 뒤 — 경계 필터가 아니라 로그 수집을 보는 테스트다.
                "createdAt": f"2026-08-{11 + (i % 5):02d}T07:53:00Z",
            }
            for i, rid in enumerate(run_ids)
        ]
    )


def _patch_listing(monkeypatch, payload: str) -> None:
    class _Done:
        stdout = payload

    monkeypatch.setattr(cpo.subprocess, "run", lambda *a, **k: _Done())


def test_blocks_follow_input_order_not_completion_order(monkeypatch) -> None:
    """느리게 도착한 로그가 뒤로 밀리면 안 된다 — 출력이 실행마다 달라진다."""
    _patch_listing(monkeypatch, _listing(1, 2, 3))

    def fake_fetch(run_id: str) -> str:
        # 첫 실행을 가장 느리게 만들어 완료 순서를 입력 순서와 어긋나게 한다.
        if run_id == "1":
            threading.Event().wait(0.05)
        return f"collect\tRun script\tNo-op state churn only\ncollect\tRun script\t_state/run-{run_id}.json\n"

    monkeypatch.setattr(cpo, "fetch_run_log", fake_fetch)

    skips, checked, reason, blocks = cpo.collect_skip_counts("collect-crypto-news.yml", 3, PILOT)
    assert reason is None
    assert (skips, checked) == (3, 3)
    assert blocks == [["_state/run-1.json"], ["_state/run-2.json"], ["_state/run-3.json"]]


def test_unfetchable_run_leaves_the_denominator(monkeypatch) -> None:
    """로그를 못 받은 실행은 `checked` 에서 빠져야 한다. 남기면 비율이 희석된다."""
    _patch_listing(monkeypatch, _listing(1, 2, 3))
    monkeypatch.setattr(cpo, "fetch_run_log", lambda rid: None if rid == "2" else SKIP_LOG)

    skips, checked, reason, blocks = cpo.collect_skip_counts("collect-crypto-news.yml", 3, PILOT)
    assert reason is None
    assert (skips, checked) == (2, 2)
    assert len(blocks) == 2


def test_only_post_pilot_runs_are_fetched(monkeypatch) -> None:
    """파일럿 전 실행의 로그를 받으러 가면 분모가 틀린다."""
    import json

    _patch_listing(
        monkeypatch,
        json.dumps(
            [
                {"databaseId": 1, "conclusion": "success", "createdAt": "2026-08-09T22:12:00Z"},  # 전
                {"databaseId": 2, "conclusion": "success", "createdAt": "2026-08-11T07:53:00Z"},  # 후
            ]
        ),
    )
    asked: list[str] = []

    def fake_fetch(run_id: str) -> str:
        asked.append(run_id)
        return PLAIN_LOG

    monkeypatch.setattr(cpo, "fetch_run_log", fake_fetch)

    skips, checked, reason, _ = cpo.collect_skip_counts("collect-crypto-news.yml", 2, PILOT)
    assert asked == ["2"]
    assert (skips, checked, reason) == (0, 1, None)


def test_no_runs_means_no_pool(monkeypatch) -> None:
    """표본 0 에서 워커를 0개로 만들면 ThreadPoolExecutor 가 ValueError 를 던진다."""
    _patch_listing(monkeypatch, "[]")
    monkeypatch.setattr(cpo, "fetch_run_log", lambda rid: PLAIN_LOG)

    assert cpo.collect_skip_counts("collect-crypto-news.yml", 5, PILOT) == (0, 0, None, [])


def test_fetch_run_log_returns_none_on_failure(monkeypatch) -> None:
    """빈 문자열로 폴백하면 실패한 실행이 "skip 안 한 실행" 으로 집계된다."""

    def boom(*a, **k):
        raise cpo.subprocess.CalledProcessError(1, "gh")

    monkeypatch.setattr(cpo.subprocess, "run", boom)
    assert cpo.fetch_run_log("123") is None

    def missing(*a, **k):
        raise FileNotFoundError

    monkeypatch.setattr(cpo.subprocess, "run", missing)
    assert cpo.fetch_run_log("123") is None
