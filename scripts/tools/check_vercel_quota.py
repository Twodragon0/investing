#!/usr/bin/env python3
"""Vercel 배포 레코드의 롤링 피크와 거절을 집계한다.

`docs/devsecops/branch-protection.md` 의 "재측정 (2026-08-10)" 절이 손으로 돌린
절차를 코드로 고정한 것이다. 그 절차는 재현될 때마다 같은 함정 세 개를 만난다:

1. `vercel ls` 는 한 페이지 20건이다. 페이지네이션하지 않으면 최근 20건만 보고
   "피크 20" 이라는 답이 나온다.
2. **레코드 없음이 곧 거절이 아니다.** 한 푸시에 커밋이 여러 개 들어오면 Vercel 은
   head 하나에만 레코드를 만든다. 그 앞 커밋들을 거절로 세면 부풀려진다.
3. preview 를 빼면 축이 나빠진다. 쿼터는 production+preview 를 같은 통에 넣는다
   (위 문서의 격자 탐색에서 production 만 쓰면 Youden's J 가 0.886 → 0.851).

측정하는 것
-----------
1. 롤링 피크 — 창(기본 24h)을 미끄러뜨리며 센 레코드 수의 최대값. 파일럿 경계가
   주어지면 전/후를 나눠 낸다.
2. 거절 — `origin/main` 커밋 중 production 레코드를 못 받은 것. 위 2번 때문에
   `--batch-window` (기본 90초) 이내 후속 커밋이 레코드를 받았으면 non-head 로 뺀다.
3. 피크 창의 구성 — 수집기 / PR 머지 / 그 외 / preview.

3번이 이 도구의 존재 이유다. 피크는 파일럿이 건드리지 않는 축(개발 활동)이 지배하는
경우가 있어서, 총량만 보면 **피크 하락을 파일럿 성과로 오독한다**. 2026-08-14 실측이
그랬다 — 24h 피크가 95(08-07 12:30) → 52(08-12 18:44)로 떨어졌는데, 그 두 창의 수집기
레코드는 30 → 36 으로 **오히려 늘었다.** 빠진 43건은 전부 개발 활동이다
(preview 43→11, PR 머지 16→4).

전/후 피크는 **창 전체가 한쪽 구간에 드는 것만** 센다(`report_peaks` 참조). 경계를
걸친 창을 "파일럿 후" 로 세면 후 구간이 59로 부풀려진다 — 그 창들은 파일럿 전
레코드를 품고 있다.

경고: 임계값은 상수로 박지 않는다. 포화 사건이 1회뿐이라 창 폭과 임계가 강하게
식별되지 않는다(24h/95 · 30h/106 · 36h/116 이 모두 비슷하게 들어맞는다). 이 도구는
피크를 **보고**할 뿐 임계와 비교해 판정하지 않는다.

`--kind collector` 는 3번을 한 걸음 더 밀어 **피크 자체를 수집기 축으로만** 다시
낸다. 총량 피크가 개발 활동에 지배될 때 파일럿이 움직일 수 있는 축이 실제로 내려갔는지
보려면 이게 필요하다. 대신 거른 피크는 **쿼터 부하가 아니다** — 쿼터 카운터는 우리
분류를 모른다. 걸러도 `[3]` SHA 대조는 전량으로 돈다(거른 목록으로 대조하면 걸러진
레코드를 받은 커밋이 전부 거절로 둔갑한다).

Usage
-----
  python scripts/tools/check_vercel_quota.py
  python scripts/tools/check_vercel_quota.py --window-hours 30 --since 2026-08-01
  python scripts/tools/check_vercel_quota.py --pilot-merged 2026-08-10T13:14:51+09:00
  python scripts/tools/check_vercel_quota.py --kind collector   # 수집기 축만

종료 코드: 집계 성공 0, `vercel`/`git` 을 못 돌리면 2.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING, NamedTuple

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "common"))
from config import setup_logging  # noqa: E402

logger = setup_logging("check_vercel_quota")

REPO_ROOT = Path(__file__).resolve().parents[2]
KST = timezone(timedelta(hours=9))

DEFAULT_PROJECT = "investing"
DEFAULT_WINDOW_HOURS = 24
# 한 푸시의 non-head 커밋을 가르는 간격. 위 문서의 재측정이 쓴 값이다.
DEFAULT_BATCH_SECONDS = 90
# `vercel ls` 한 페이지 크기. 페이지가 이보다 작으면 마지막 페이지다.
PAGE_SIZE = 20
# 폭주 방지 — 20건/페이지이므로 기본값은 약 4000레코드다.
MAX_PAGES = 200

ENVIRONMENTS = ("production", "preview")

# 커밋 제목 → 종류. 피크 창의 **구성**과 `--kind` 축 필터가 둘 다 이걸 쓴다.
# 즉 이 표를 건드리면 `[1]` 피크와 `[2]` 일자별의 대상 집합까지 움직인다
# (`[3]` SHA 대조는 영향 없다 — 전량으로 돈다).
COLLECTOR_PREFIXES = (
    "chore: collect",
    "chore: update",
    "chore: generate",
    "chore: improve",
    "chore: backfill",
)


class Record(NamedTuple):
    """Vercel 배포 레코드 하나."""

    at: datetime
    env: str
    state: str
    sha: str | None
    subject: str


class Commit(NamedTuple):
    """`origin/main` 커밋 하나."""

    at: datetime
    sha: str
    subject: str


class Verdict(NamedTuple):
    """SHA 대조 결과."""

    deployed: list[Commit]
    non_head: list[Commit]
    rejected: list[Commit]


def _run(cmd: Sequence[str]) -> str | None:
    """외부 명령을 돌린다. 실패하면 None — 호출부가 집계를 중단한다.

    빈 문자열로 폴백하지 않는 이유: 빈 결과는 "레코드 0건" 과 구분되지 않고,
    레코드 0건이면 모든 커밋이 거절로 보고된다.
    """
    try:
        out = subprocess.run(
            list(cmd),
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
    except FileNotFoundError:
        logger.error("%s 를 찾을 수 없다", cmd[0])
        return None
    except subprocess.CalledProcessError as e:
        logger.error("%s 실패 (rc %d): %s", " ".join(cmd), e.returncode, (e.stderr or "")[:300])
        return None
    return out.stdout


def parse_records(payload: str, env: str) -> tuple[list[Record], int | None]:
    """`vercel ls -F json` 한 페이지를 파싱한다.

    Returns (레코드들, 다음 페이지 커서). 커서가 None 이면 더 없다.
    """
    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        logger.error("vercel 출력 파싱 실패 (%s)", env)
        return [], None

    records: list[Record] = []
    for item in data.get("deployments") or []:
        created = item.get("createdAt")
        if not isinstance(created, (int, float)):
            continue
        meta = item.get("meta") or {}
        records.append(
            Record(
                at=datetime.fromtimestamp(created / 1000, KST),
                env=env,
                state=str(item.get("state") or ""),
                sha=meta.get("githubCommitSha"),
                subject=str(meta.get("githubCommitMessage") or ""),
            )
        )
    cursor = (data.get("pagination") or {}).get("next")
    return records, cursor if isinstance(cursor, int) else None


def vercel_list_cmd(project: str, env: str) -> list[str]:
    """`vercel ls` 명령. `VERCEL_TOKEN` 이 있으면 `--token` 을 붙인다.

    로컬은 `vercel login` 세션을 쓰고 CI 는 토큰을 쓴다. 토큰을 인자로 받지 않고
    환경변수에서 읽는 이유: 명령줄에 넣으면 프로세스 목록과 로그에 남는다.
    """
    cmd = ["vercel", "ls", project, "--environment", env, "-F", "json"]
    token = os.environ.get("VERCEL_TOKEN", "").strip()
    if token:
        cmd += ["--token", token]
    return cmd


def fetch_records(project: str, env: str, since: datetime) -> list[Record] | None:
    """`--next` 로 `since` 를 덮을 때까지 페이지네이션한다. 실패하면 None.

    페이지 상한에 걸리면 **None 이다.** 부분 결과를 돌려주면 덜 덮인 구간의 커밋이
    전부 "레코드 없음 = 거절" 로 보고되는데, 그게 종료 코드 0 으로 나가면 조용히
    틀린 집계가 성공으로 읽힌다. 모듈 앞머리의 `_run` 폴백 원칙과 같은 이유다.
    """
    collected: list[Record] = []
    cursor: int | None = None
    for _ in range(MAX_PAGES):
        cmd = vercel_list_cmd(project, env)
        if cursor is not None:
            cmd += ["--next", str(cursor)]
        payload = _run(cmd)
        if payload is None:
            return None
        page, next_cursor = parse_records(payload, env)
        if not page:
            break
        collected += page
        oldest = min(r.at for r in page)
        logger.debug("  %s +%d건 (누적 %d) oldest=%s", env, len(page), len(collected), oldest)
        if oldest < since or next_cursor is None:
            break
        if next_cursor == cursor:
            # 커서가 안 움직이면 같은 페이지를 상한까지 다시 쌓는다 — 레코드가
            # 중복 계상되어 피크가 부풀려진다. 진전이 없으면 멈춘다.
            logger.warning("  %s 커서 정체 (%s) — 페이지네이션을 멈춘다", env, next_cursor)
            break
        cursor = next_cursor
    else:
        logger.error("  %s 페이지 상한 %d 도달 — 구간이 덜 덮였다", env, MAX_PAGES)
        return None
    return collected


def fetch_commits(since: datetime) -> list[Commit] | None:
    """`origin/main` 커밋을 시각 오름차순으로 가져온다. 실패하면 None.

    `git log` 는 최신 먼저이고, **커밋 시각이 같으면 자식을 부모보다 먼저** 낸다
    (그래프 순회 순서). 그대로 안정 정렬하면 동률 구간에서 head 가 non-head 보다
    앞에 남는다. `classify_commits` 는 뒤만 보므로 그 non-head 를 거절로 오분류한다
    — 이 도구가 없애려던 바로 그 오류가 되돌아온다.

    그래서 정렬 **전에 뒤집는다.** 뒤집으면 동률 구간이 부모→자식 순이 되고,
    안정 정렬이 그 순서를 보존한다.
    """
    raw = _run(["git", "log", "origin/main", f"--since={since.isoformat()}", "--format=%H|%cI|%s"])
    if raw is None:
        return None
    commits: list[Commit] = []
    for line in raw.splitlines():
        parts = line.split("|", 2)
        if len(parts) != 3:
            continue
        sha, stamp, subject = parts
        try:
            at = datetime.fromisoformat(stamp).astimezone(KST)
        except ValueError:
            continue
        commits.append(Commit(at=at, sha=sha, subject=subject))
    commits.reverse()
    commits.sort(key=lambda c: c.at)
    return commits


def rolling_peak(
    times: Sequence[datetime],
    window: timedelta,
    *,
    min_end: datetime | None = None,
    max_end: datetime | None = None,
) -> tuple[datetime, int] | None:
    """창을 미끄러뜨리며 센 최대 레코드 수와 그 창의 종료 시각.

    창은 `(t - window, t]` — 오른쪽 닫힘이다. 경계 규칙이 다르면 피크가 1건
    달라진다(재측정 문서의 94 와 이 도구의 95 가 그 차이다).

    `min_end`/`max_end` 는 **창 종료 시각**을 제한할 뿐 세는 레코드를 거르지
    않는다. 파일럿 전/후를 나눌 때 이 구분이 중요하다 — 레코드 쪽을 걸러 버리면
    경계를 걸친 창에서 실제 쿼터 부하를 과소평가한다. 쿼터 카운터는 파일럿이
    언제 머지됐는지 모른다. 반대로 창 종료만 제한하면 경계를 걸친 창이 "파일럿 후"
    로 잘못 귀속되는데, 호출부가 `min_end = 파일럿 + window` 로 창 전체를 후
    구간에 넣어 그 문제를 피한다.
    """
    if not times:
        return None
    ordered = sorted(times)
    best: tuple[datetime, int] | None = None
    left = 0
    for right, end in enumerate(ordered):
        while ordered[left] <= end - window:
            left += 1
        if min_end is not None and end < min_end:
            continue
        if max_end is not None and end > max_end:
            break
        count = right - left + 1
        if best is None or count > best[1]:
            best = (end, count)
    return best


def classify_commits(
    commits: Sequence[Commit],
    deployed_shas: frozenset[str],
    batch_window: timedelta,
) -> Verdict:
    """레코드를 받은 커밋 / 푸시 batch non-head / 거절 로 가른다.

    non-head 판정은 **뒤를 본다.** `batch_window` 안의 후속 커밋 중 하나라도
    레코드를 받았으면 이 커밋은 같은 푸시의 head 가 아니었다는 뜻이다.
    """
    deployed: list[Commit] = []
    non_head: list[Commit] = []
    rejected: list[Commit] = []
    for i, commit in enumerate(commits):
        if commit.sha in deployed_shas:
            deployed.append(commit)
            continue
        batched = False
        for follower in commits[i + 1 :]:
            if follower.at - commit.at > batch_window:
                break
            if follower.sha in deployed_shas:
                batched = True
                break
        (non_head if batched else rejected).append(commit)
    return Verdict(deployed=deployed, non_head=non_head, rejected=rejected)


def record_kind(record: Record) -> str:
    """레코드를 축으로 가른다. preview 는 환경으로, 나머지는 커밋 제목으로 판정한다.

    피크 창 구성 표와 `--kind` 필터(`filter_kind`)가 같이 쓴다. 후자를 통해
    `[1]`·`[2]` 의 대상 집합을 정하므로 "구성 표시용" 이 아니다.
    """
    if record.env == "preview":
        return "preview(PR)"
    subject = record.subject
    if subject.startswith(COLLECTOR_PREFIXES):
        return "수집기"
    if subject.startswith("Merge pull request") or "(#" in subject:
        return "PR 머지"
    return "그 외"


COLLECTOR_KIND = "수집기"

# `--kind` 선택지 → 남길 `record_kind` 판정.
#
# `all` 이 기본이고 그때만 이 도구가 **쿼터 부하**를 보고한다. 나머지 둘은 부하가
# 아니라 **부하의 구성**을 보는 렌즈다 — 아래 `filter_kind` 의 경고를 볼 것.
KIND_FILTERS = {
    "all": None,
    "collector": lambda kind: kind == COLLECTOR_KIND,
    "dev": lambda kind: kind != COLLECTOR_KIND,
}
KIND_LABELS = {
    "all": "production+preview",
    "collector": "수집기 축만",
    "dev": "개발 활동 축만",
}
DEFAULT_KIND = "all"


def filter_kind(records: Sequence[Record], kind: str) -> list[Record]:
    """`--kind` 로 레코드를 거른다.

    **거른 피크는 쿼터 헤드룸이 아니다.** Vercel 의 쿼터 카운터는 우리 분류를 모르고
    통에 든 레코드를 전부 센다. `--kind collector` 로 나온 36 은 "쿼터를 36 만큼
    쓰고 있다" 가 아니라 "그 창의 부하 중 36 이 수집기 축이다" 다. 둘을 섞으면
    임계(추정 하한 ~95)와 비교해 여유가 있다고 오독한다.

    이 렌즈가 필요한 이유는 반대 방향의 오독을 막기 위해서다. 2026-08-14 실측에서
    24h 피크가 95 → 52 로 떨어졌는데 그 창의 수집기 레코드는 30 → 36 으로 **늘었다.**
    총량만 보면 파일럿 성과로 읽히지만 빠진 43건은 전부 개발 활동(preview 43→11,
    PR 머지 16→4)이었다. 파일럿이 움직일 수 있는 축만 따로 세야 그 착시가 안 생긴다.
    """
    keep = KIND_FILTERS[kind]
    if keep is None:
        return list(records)
    return [r for r in records if keep(record_kind(r))]


def window_composition(records: Iterable[Record], end: datetime, window: timedelta) -> Counter[str]:
    """`(end - window, end]` 창에 든 레코드를 종류별로 센다."""
    return Counter(record_kind(r) for r in records if end - window < r.at <= end)


def _report_composition(records: Sequence[Record], end: datetime, window: timedelta, label: str) -> None:
    counts = window_composition(records, end, window)
    total = sum(counts.values())
    if not total:
        return
    logger.info("  %s 창 구성 (총 %d건)", label, total)
    for kind, count in counts.most_common():
        logger.info("    %-12s %3d  (%d%%)", kind, count, round(count / total * 100))
    dev = total - counts.get("수집기", 0)
    logger.info("    → 개발 활동 소계 %d (%d%%)", dev, round(dev / total * 100))


def report_peaks(
    records: Sequence[Record],
    window: timedelta,
    pilot_merged: datetime | None,
    since: datetime,
    kind: str = DEFAULT_KIND,
) -> None:
    """롤링 피크와 그 창의 구성을 낸다.

    `records` 는 `since` **이전 것까지** 받는다. 페이지네이션이 오버슈트해서
    가져온 그 레코드들을 버리면, `since` 직후에 끝나는 창이 자기 앞부분을 잃어
    피크가 과소평가된다 — 쿼터 카운터는 집계 시작일을 모른다. 대신 `min_end` 로
    **창 종료**만 `since` 이후로 제한한다.

    `records` 는 **거르지 않은 전량**이고 `--kind` 필터는 이 함수 안에서 건다.
    호출부가 거른 목록을 만들어 넘기는 구조로 두면 그 목록이 `main()` 의 지역변수로
    남고, 같은 타입의 전량 목록과 뒤바뀔 수 있다. 뒤바뀌면 조용히 틀린다 — 특히
    `[3]` SHA 대조가 거른 목록을 집으면 걸러진 레코드를 받은 커밋이 전부 "레코드
    없음 = 거절" 이 되어 거절 수가 통째로 조작된다. 필터를 안으로 넣으면 그 뒤바뀜이
    **표현 불가능**해진다.

    구성 표는 언제나 전량으로 낸다 — 거른 뒤 구성을 내면 "수집기 100%" 라는 자명한
    줄만 남아, 그 창의 실제 쿼터 부하가 얼마였는지가 출력에서 사라진다. 그 숫자가
    이 렌즈를 쓰는 이유의 절반이다.
    """
    hours = int(window.total_seconds() // 3600)
    composition = records
    records = filter_kind(records, kind)
    logger.info("[1] %dh 롤링 피크 (%s)", hours, KIND_LABELS[kind])
    if kind != DEFAULT_KIND:
        logger.info("  ※ 축을 걸렀다 — 아래 피크는 **쿼터 부하가 아니다.** 구성 표의 총계가 부하다.")

    times = [r.at for r in records]
    overall = rolling_peak(times, window, min_end=since)
    if overall is None:
        logger.warning("  레코드 0건 — 피크를 낼 수 없다")
        return
    at, count = overall
    logger.info("  전 기간 피크  %d건  (창 종료 %s KST)", count, at.strftime("%Y-%m-%d %H:%M"))

    if pilot_merged is None:
        _report_composition(composition, at, window, "피크")
        return

    # 창 **전체**가 한쪽 구간에 들어가는 것만 본다. 경계를 걸친 창은 전/후 어느
    # 쪽 부하도 아니라서 어디에 넣어도 그 구간을 오해하게 만든다.
    times = [r.at for r in records]
    for label, bounds in (
        ("파일럿 전", {"max_end": pilot_merged}),
        ("파일럿 후", {"min_end": pilot_merged + window}),
    ):
        peak = rolling_peak(times, window, **bounds)
        if peak is None:
            logger.info("  %s 피크  창 없음 (구간이 %dh 보다 짧다)", label, hours)
            continue
        peak_at, peak_count = peak
        logger.info("  %s 피크  %d건  (창 종료 %s)", label, peak_count, peak_at.strftime("%m-%d %H:%M"))
        _report_composition(composition, peak_at, window, label)

    logger.info("  주의: 피크는 파일럿이 건드리지 않는 축(개발 활동)이 지배할 수 있다.")
    logger.info("        총량 하락을 파일럿 성과로 읽기 전에 위 창 구성을 볼 것.")
    if kind == DEFAULT_KIND:
        logger.info("        `--kind collector` 로 파일럿이 움직일 수 있는 축만 따로 볼 수 있다.")


def report_daily(records: Sequence[Record], window: timedelta, since: datetime, kind: str = DEFAULT_KIND) -> None:
    """일자별 레코드 수와 그날의 롤링 최대.

    `report_peaks` 와 같은 이유로 `since` 이전 레코드도 **세는 데는** 쓴다. 표시만
    `since` 이후 날짜로 자른다 — 안 그러면 첫날의 롤링 최대가 그날 레코드 수와
    같아지는 가짜 계단이 생긴다.

    `report_peaks` 와 같이 전량을 받아 **안에서** 거른다(그 docstring 참조).
    """
    records = filter_kind(records, kind)
    logger.info("[2] 일자별 (KST) — 레코드 수 / 그날의 롤링 최대 (%s)", KIND_LABELS[kind])
    if kind != DEFAULT_KIND:
        # `[1]` 과 `[2]` 는 따로 인용된다. 경고를 `[1]` 에만 두면 `[2]` 표만 떼어
        # 읽는 사람에게는 이 숫자가 쿼터 부하로 보인다.
        logger.info("  ※ 축을 걸렀다 — 쿼터 부하가 아니다.")
    ordered = sorted(records, key=lambda r: r.at)
    times = [r.at for r in ordered]
    per_day: Counter[str] = Counter(r.at.strftime("%Y-%m-%d") for r in ordered if r.at >= since)
    day_peak: dict[str, int] = {}
    left = 0
    for right, end in enumerate(times):
        while times[left] <= end - window:
            left += 1
        if end < since:
            continue
        day = end.strftime("%Y-%m-%d")
        day_peak[day] = max(day_peak.get(day, 0), right - left + 1)
    for day in sorted(per_day):
        logger.info("  %s  레코드 %3d   롤링 피크 %3d", day, per_day[day], day_peak.get(day, 0))


def load_at(times: Sequence[datetime], at: datetime, window: timedelta) -> int:
    """`(at - window, at]` 에 든 레코드 수 = 그 순간의 쿼터 부하.

    `rolling_peak` 과 **같은 경계 규칙**(오른쪽 닫힘)이다. 규칙이 갈리면 같은 데이터에서
    피크와 부하가 1건씩 어긋난다.

    `rolling_peak` 과 다른 점은 평가 격자다. `rolling_peak` 은 **레코드** 시각에서
    창을 끝내고 여기는 **커밋** 시각에서 끝낸다. 두 격자는 일치하지 않으므로 이 함수의
    최대값이 `rolling_peak` 의 피크보다 작을 수 있다 — 틀린 게 아니라 다른 질문이다
    ("부하의 최대" vs "이 커밋이 겪은 부하").
    """
    return sum(1 for t in times if at - window < t <= at)


def _percentiles(values: Sequence[int]) -> str:
    """분포 요약 한 줄. 거절 부하를 비교할 기준선이 없으면 숫자를 읽을 수 없다."""
    ordered = sorted(values)
    n = len(ordered)
    return (
        f"n={n} min={ordered[0]} p25={ordered[n // 4]} "
        f"중앙값={ordered[n // 2]} p75={ordered[3 * n // 4]} max={ordered[-1]}"
    )


def report_rejections(
    verdict: Verdict,
    pilot_merged: datetime | None,
    records: Sequence[Record] | None = None,
    window: timedelta | None = None,
) -> None:
    """SHA 대조 결과를 낸다.

    `records`·`window` 를 주면 거절마다 **그 순간의 롤링 부하**를 붙이고 정상 생성의
    부하 분포를 함께 낸다. 이게 없으면 "거절 25건" 만 남아 쿼터 때문인 거절과 그렇지
    않은 거절이 구분되지 않는다 — `branch-protection.md` 의 "쿼터로 설명되지 않는
    단발 거절" 절이 손으로 계산해야 했던 숫자다. 손계산은 이 파일에서 두 번 틀렸다
    (91→79, 94→95). 도구가 내면 다시 틀리지 않는다.
    """
    logger.info("[3] SHA 대조 — main 커밋이 production 레코드를 받았는가")
    total = len(verdict.deployed) + len(verdict.non_head) + len(verdict.rejected)
    logger.info("  main 커밋 %d건", total)
    logger.info("  레코드 생성         %d", len(verdict.deployed))
    logger.info("  푸시 batch non-head %d", len(verdict.non_head))
    logger.info("  레코드 없음 = 거절   %d", len(verdict.rejected))
    if not verdict.rejected:
        return

    # sha → 그 커밋이 겪은 롤링 부하. `records`/`window` 가 없으면 None 이고 그때는
    # 부하 열을 아예 내지 않는다 — 0 으로 폴백하면 "부하 0에서 거절" 로 읽힌다.
    loads: dict[str, int] | None = None
    if records and window is not None:
        times = [r.at for r in records]
        loads = {c.sha: load_at(times, c.at, window) for c in (*verdict.deployed, *verdict.rejected)}
        if verdict.deployed:
            logger.info(
                "  정상 생성 %d건의 %dh 롤링 부하 분포: %s",
                len(verdict.deployed),
                int(window.total_seconds() // 3600),
                _percentiles([loads[c.sha] for c in verdict.deployed]),
            )

    by_day = Counter(c.at.strftime("%Y-%m-%d") for c in verdict.rejected)
    logger.info("  일자별 거절: %s", ", ".join(f"{d} {n}" for d, n in sorted(by_day.items())))
    for commit in verdict.rejected:
        if loads is None:
            logger.info("    %s  %s", commit.at.strftime("%m-%d %H:%M"), commit.subject[:60])
        else:
            logger.info(
                "    %s  부하 %3d  %s",
                commit.at.strftime("%m-%d %H:%M"),
                loads[commit.sha],
                commit.subject[:60],
            )
    if pilot_merged is not None:
        after = sum(1 for c in verdict.rejected if c.at > pilot_merged)
        logger.info("  파일럿 후 거절 %d건", after)
        logger.info("  주의: 포화 사건이 드물어 거절 0건은 성공의 증거가 아니다.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", default=DEFAULT_PROJECT, help=f"Vercel 프로젝트 (기본: {DEFAULT_PROJECT})")
    parser.add_argument(
        "--window-hours",
        type=int,
        default=DEFAULT_WINDOW_HOURS,
        help=f"롤링 창 폭 (기본: {DEFAULT_WINDOW_HOURS})",
    )
    parser.add_argument("--since", help="집계 시작일 ISO (기본: 14일 전)")
    parser.add_argument("--pilot-merged", help="파일럿 머지 시각 ISO — 주면 전/후를 나눠 낸다")
    parser.add_argument(
        "--batch-window-seconds",
        type=int,
        default=DEFAULT_BATCH_SECONDS,
        help=f"푸시 batch non-head 판정 간격 (기본: {DEFAULT_BATCH_SECONDS})",
    )
    parser.add_argument(
        "--kind",
        choices=sorted(KIND_FILTERS),
        default=DEFAULT_KIND,
        help=(
            f"롤링 피크·일자별을 낼 축 (기본: {DEFAULT_KIND}). "
            "collector 는 수집기 커밋만, dev 는 그 외(preview·PR 머지 등)만 센다. "
            "거른 피크는 쿼터 부하가 아니라 부하의 구성이다 — [3] SHA 대조에는 적용되지 않는다."
        ),
    )
    args = parser.parse_args()

    if args.window_hours <= 0:
        logger.error("--window-hours 는 양수여야 한다: %d", args.window_hours)
        return 2

    now = datetime.now(KST)
    if args.since:
        try:
            since = datetime.fromisoformat(args.since)
        except ValueError:
            logger.error("--since 파싱 실패: %s", args.since)
            return 2
        if since.tzinfo is None:
            since = since.replace(tzinfo=KST)
    else:
        since = now - timedelta(days=14)

    pilot_merged: datetime | None = None
    if args.pilot_merged:
        try:
            pilot_merged = datetime.fromisoformat(args.pilot_merged)
        except ValueError:
            logger.error("--pilot-merged 파싱 실패: %s", args.pilot_merged)
            return 2
        if pilot_merged.tzinfo is None:
            logger.error("--pilot-merged 에 타임존이 없다: %s", args.pilot_merged)
            return 2

    window = timedelta(hours=args.window_hours)
    logger.info("Vercel 쿼터 집계 — %s 이후, %dh 창", since.strftime("%Y-%m-%d %H:%M"), args.window_hours)

    records: list[Record] = []
    for env in ENVIRONMENTS:
        page = fetch_records(args.project, env, since)
        if page is None:
            logger.error("레코드 수집 실패 — 집계를 중단한다 (부분 집계는 거절을 부풀린다)")
            return 2
        records += page
    if not records:
        logger.error("레코드 0건 — vercel 프로젝트 이름과 인증을 확인할 것")
        return 2

    # 집계 구간의 레코드 수는 `since` 이후만 보고하되, 창 계산에는 오버슈트해서
    # 가져온 `since` 이전 레코드까지 넘긴다 (`report_peaks` docstring 참조).
    in_window = [r for r in records if r.at >= since]
    counts = Counter(r.env for r in in_window)
    logger.info(
        "  수집 %d건 (production %d / preview %d), 창 계산용 선행 레코드 %d건",
        len(in_window),
        counts.get("production", 0),
        counts.get("preview", 0),
        len(records) - len(in_window),
    )

    # `--kind` 는 **보고 축만** 좁힌다. 여기서 거른 목록을 만들지 않는 것이 요점이다 —
    # 지역변수로 남으면 아래 `deployed_shas` 가 그것을 집을 수 있고, 그러면 걸러진
    # 레코드를 받은 커밋이 전부 "레코드 없음 = 거절" 이 되어 거절 수가 통째로 조작된다.
    # 필터는 두 report 함수 **안**에 있다.
    report_peaks(records, window, pilot_merged, since, args.kind)
    report_daily(records, window, since, args.kind)

    commits = fetch_commits(since)
    if commits is None:
        logger.error("git log 실패 — SHA 대조를 건너뛴다")
        return 2
    deployed_shas = frozenset(r.sha for r in records if r.env == "production" and r.sha)
    verdict = classify_commits(commits, deployed_shas, timedelta(seconds=args.batch_window_seconds))
    report_rejections(verdict, pilot_merged, records, window)

    return 0


if __name__ == "__main__":
    sys.exit(main())
