"""`check_pilot_observation.py` `[2]` skip 비율의 분모 단위 테스트.

## 왜 분모를 파일럿 뒤로 자르는가

`gh run list --limit N` 은 최근 N 실행을 그냥 준다. 파일럿 **전** 실행은 skip 코드가
없어 구조적으로 skip 할 수 없으므로, 그것을 분모에 넣으면 비율이 희석된다.

방향이 나쁘다. 2026-08-14 실측에서 조사한 20실행 중 8건이 파일럿 전이었다:

| | skip/실행 | 비율 | 95% CI |
|---|---|---|---|
| 전·후 혼합 | 5/20 | 25.0% | [11.2%, 46.9%] |
| 파일럿 후만 | 5/12 | 41.7% | [19.3%, 68.0%] |

희석된 25.0% 는 **CI 상한이 46.9%** 라 파일럿 전 실측 no-op 비율 55.2% 를 배제한다 —
"skip 이 기대보다 덜 걸린다" 는 잘못된 인상을 준다. 후만 세면 55.2% 를 포함한다.

게이트 판정 자체는 `[3]`·`[5]`(사건 유무)가 하므로 이 결함이 판정을 뒤집지는 않았다.
그래도 출력에 실린 비율이 틀렸고, 비율은 확대 규모를 정하는 데 쓰인다.

## 이 파일이 지키는 것

- 파일럿 전 실행이 분모에 들어가지 않을 것
- `createdAt` 을 못 읽는 실행은 **버릴 것** — 남기면 경계를 모르는 표본이 분모에
  들어가 같은 희석이 재발한다
- 경계는 배타적일 것 (`> pilot_start`) — 머지 커밋과 같은 시각에 시작한 실행은
  그 코드로 돌았다는 보장이 없다
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta, timezone
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


def _run(created: str, run_id: int = 1) -> dict:
    return {"databaseId": run_id, "conclusion": "success", "createdAt": created}


def test_drops_runs_started_before_pilot() -> None:
    """파일럿 전 실행은 skip 할 수 없다 — 분모에 넣으면 비율이 희석된다."""
    runs = [
        _run("2026-08-10T22:39:00Z", 1),  # 후
        _run("2026-08-09T22:12:00Z", 2),  # 전
        _run("2026-08-11T07:53:00Z", 3),  # 후
    ]
    kept = cpo.filter_runs_after(runs, PILOT)
    assert [r["databaseId"] for r in kept] == [1, 3]


def test_boundary_is_exclusive() -> None:
    """머지 시각과 **정확히 같은** 시각에 시작한 실행은 제외한다.

    그 실행이 새 코드로 돌았다는 보장이 없다. 포함하면 skip 못 하는 실행 하나가
    분모에 들어간다.
    """
    same = PILOT.astimezone(UTC).isoformat().replace("+00:00", "Z")
    assert cpo.filter_runs_after([_run(same)], PILOT) == []

    one_second_later = (PILOT + timedelta(seconds=1)).astimezone(UTC)
    later = one_second_later.isoformat().replace("+00:00", "Z")
    assert len(cpo.filter_runs_after([_run(later)], PILOT)) == 1


def test_drops_runs_without_parsable_timestamp() -> None:
    """경계를 모르는 표본을 남기면 희석이 재발한다 — 없는 데이터가 낫다."""
    runs = [
        {"databaseId": 1, "conclusion": "success"},  # createdAt 없음
        _run("not-a-timestamp", 2),
        {"databaseId": 3, "conclusion": "success", "createdAt": 12345},  # 문자열 아님
        _run("2026-08-11T07:53:00Z", 4),
    ]
    kept = cpo.filter_runs_after(runs, PILOT)
    assert [r["databaseId"] for r in kept] == [4]


def test_empty_input_is_empty_output() -> None:
    assert cpo.filter_runs_after([], PILOT) == []


def test_all_before_pilot_yields_no_sample() -> None:
    """표본 0 은 "skip 0회" 와 다르다. 호출부가 비율을 내지 않도록 빈 목록이어야 한다."""
    runs = [_run("2026-08-08T22:09:00Z", 1), _run("2026-08-09T22:12:00Z", 2)]
    assert cpo.filter_runs_after(runs, PILOT) == []


def test_utc_offset_forms_are_equivalent() -> None:
    """`Z` 와 `+00:00` 은 같은 시각이다. 한쪽만 파싱되면 표본이 조용히 준다."""
    zulu = _run("2026-08-11T07:53:00Z", 1)
    offset = _run("2026-08-11T07:53:00+00:00", 2)
    assert len(cpo.filter_runs_after([zulu, offset], PILOT)) == 2


def test_per_collector_boundary_is_respected() -> None:
    """확대 수집기는 경계가 늦다 — regulatory 경계로 자르면 그 수집기 분모가 부푼다."""
    later_pilot = datetime.fromisoformat("2026-08-13T09:00:00+09:00")
    runs = [_run("2026-08-11T07:53:00Z", 1), _run("2026-08-13T22:40:00Z", 2)]
    assert [r["databaseId"] for r in cpo.filter_runs_after(runs, PILOT)] == [1, 2]
    assert [r["databaseId"] for r in cpo.filter_runs_after(runs, later_pilot)] == [2]


def test_counts_only_boundary_drops_not_unparsable() -> None:
    """상한 안내의 판정 기준은 "**경계 때문에** 버려진 수" 다.

    `filter_runs_after` 결과 길이만 보면 두 종류의 탈락이 섞인다. `createdAt` 을
    못 읽어 버려진 실행 한 건이 "가져온 것이 전부 파일럿 후" 안내를 꺼 버리면,
    표본이 `--run-limit` 상한에 묶인 것을 놓친다.
    """
    unparsable_plus_post = [
        {"databaseId": 1, "conclusion": "success"},  # createdAt 없음 → 버려지지만 경계 탈락은 아님
        _run("2026-08-11T07:53:00Z", 2),
    ]
    assert len(cpo.filter_runs_after(unparsable_plus_post, PILOT)) == 1
    assert cpo.count_runs_before(unparsable_plus_post, PILOT) == 0

    with_pre_pilot = [_run("2026-08-09T22:12:00Z", 3), _run("2026-08-11T07:53:00Z", 4)]
    assert cpo.count_runs_before(with_pre_pilot, PILOT) == 1


def test_count_runs_before_includes_the_boundary_instant() -> None:
    """경계와 같은 시각은 `filter_runs_after` 가 버리므로 여기서도 세야 짝이 맞는다."""
    same = PILOT.astimezone(UTC).isoformat().replace("+00:00", "Z")
    assert cpo.count_runs_before([_run(same)], PILOT) == 1
    assert cpo.filter_runs_after([_run(same)], PILOT) == []
