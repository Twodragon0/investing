#!/usr/bin/env python3
"""no-op 커밋 스킵 파일럿의 관측 지표를 집계한다.

`docs/devsecops/collector-push-batching-design.md` 의 관측 게이트 두 개를
측정 가능한 형태로 좁힌 것이다.

측정하는 것
-----------
1. 수집기 커밋 수 (일자별) — 절감이 실제로 일어났는가
2. no-op skip 발생 횟수 — 새 코드 경로가 실행되기는 했는가 (표본 0이면 판정 불가)
3. 중복 포스트 — 아래 "좁힌 정의" 참조

중복 지표의 좁힌 정의
--------------------
게이트로 쓰는 것은 **포스트 수준 중복**뿐이다:

- 같은 `title` 을 가진 포스트 파일이 2개 이상
- 같은 (날짜, 포스트 종류) 조합의 파일이 2개 이상

**항목 URL 재등장은 게이트가 아니다.** 수집기는 실행 안에서 `deduplicate_by_url`
로 중복을 걷어내고 포스트 수준에서 `mark_seen(post_title, ...)` 로 재발행을 막지만,
지난 날 포스트에 실린 항목을 오늘 피드에서 배제하지는 않는다. 일일 리포트는 그
시점 피드(피드당 limit 10)의 스냅샷이므로, 아직 목록에 남아 있는 공지는 매일 다시
실린다 — 설계된 동작이다. 실제로 2026-08-10 관측에서 regulatory 포스트 8개에
항목 URL 33건이 여러 날 재등장했는데 전부 이 경로였고 파일럿과 무관했다. 이 수치를
게이트로 쓰면 파일럿이 무죄인데도 실패로 읽힌다. 참고용으로만 출력한다.

Usage
-----
  python scripts/tools/check_pilot_observation.py
  python scripts/tools/check_pilot_observation.py --collector regulatory --days 7
  python scripts/tools/check_pilot_observation.py --with-runs   # gh CLI 로 skip 횟수까지

종료 코드: 포스트 수준 중복이 있으면 1, 없으면 0.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "common"))
from config import setup_logging  # noqa: E402

logger = setup_logging("check_pilot_observation")

REPO_ROOT = Path(__file__).resolve().parents[2]
POSTS_DIR = REPO_ROOT / "_posts"
KST = timezone(timedelta(hours=9))

SKIP_MARKER = "No-op state churn only"
# gh 는 액션 스크립트 본문을 에코할 때 ANSI 이스케이프를 리터럴 "^[" 2글자로 흘린다.
# 실제 ESC(0x1b) 로 오는 경우도 있어 양쪽을 다 걷어낸다.
ANSI_RE = re.compile(r"(?:\x1b|\^\[)\[[0-9;]*m")
LOG_TS_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\S+Z\s*")
POST_TYPE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}-(?P<kind>.+)\.md$")
# 재발행 변형의 꼬리 숫자(`…-report-2`) 를 떼어 같은 슬롯으로 묶는다
KIND_SUFFIX_RE = re.compile(r"-\d+$")
TITLE_RE = re.compile(r"^title:\s*(?P<title>.+?)\s*$", re.MULTILINE)
URL_RE = re.compile(r'https?://[^\s)\]"<>]+')


def is_runtime_skip_line(line: str) -> bool:
    """로그 한 줄이 skip 의 **런타임 출력**인지 판정한다.

    액션 스크립트 본문이 에코된 줄(`echo "No-op state churn only …"`)을 세면 커밋한
    실행도 skip 으로 잡힌다. 페이로드가 마커로 **시작**할 때만 인정한다.
    """
    payload = line.rsplit("\t", 1)[-1]
    payload = LOG_TS_RE.sub("", ANSI_RE.sub("", payload)).strip()
    return payload.startswith(SKIP_MARKER)


def _git(*args: str) -> str:
    """저장소 루트에서 git 을 돌리고 stdout 을 돌려준다."""
    try:
        out = subprocess.run(
            ["git", *args],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        logger.warning("git %s 실패: %s", " ".join(args), e)
        return ""
    return out.stdout


def collect_commit_counts(collector: str, days: int) -> dict[str, int]:
    """수집기 커밋을 KST 일자별로 센다."""
    raw = _git(
        "log",
        "origin/main",
        f"--since={days + 1}.days.ago",
        "--format=%cI|%s",
    )
    needle = f"collect {collector}".lower()
    by_day: Counter[str] = Counter()
    for line in raw.splitlines():
        if "|" not in line:
            continue
        iso, subject = line.split("|", 1)
        if needle not in subject.lower():
            continue
        when = datetime.fromisoformat(iso).astimezone(KST)
        by_day[when.date().isoformat()] += 1
    return dict(by_day)


def collect_skip_counts(workflow: str, limit: int) -> tuple[int, int, str | None]:
    """gh CLI 로 워크플로우 실행 로그에서 skip 발생 횟수를 센다.

    Returns (skip 횟수, 조사한 실행 수, 건너뛴 이유). gh 가 없거나 인증이 없으면
    (0, 0, 이유) 로 graceful degradation.
    """
    try:
        listing = subprocess.run(
            [
                "gh",
                "run",
                "list",
                f"--workflow={workflow}",
                f"--limit={limit}",
                "--json",
                "databaseId,conclusion",
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
    except FileNotFoundError:
        return 0, 0, "gh CLI 미설치"
    except subprocess.CalledProcessError as e:
        return 0, 0, f"gh run list 실패 ({e.returncode})"

    try:
        runs = json.loads(listing.stdout)
    except json.JSONDecodeError:
        return 0, 0, "gh 출력 파싱 실패"

    skips = 0
    checked = 0
    for run in runs:
        run_id = str(run.get("databaseId", ""))
        if not run_id:
            continue
        try:
            log = subprocess.run(
                ["gh", "run", "view", run_id, "--log"],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                check=True,
            )
        except subprocess.CalledProcessError:
            continue
        checked += 1
        if any(is_runtime_skip_line(line) for line in log.stdout.splitlines()):
            skips += 1
    return skips, checked, None


def _post_title(path: Path) -> str | None:
    try:
        head = path.read_text(encoding="utf-8")[:4000]
    except OSError as e:
        logger.warning("포스트 읽기 실패 %s: %s", path.name, e)
        return None
    m = TITLE_RE.search(head)
    if not m:
        return None
    return m.group("title").strip().strip("\"'")


def check_post_duplicates(kind_filter: str | None) -> tuple[list[str], list[str]]:
    """포스트 수준 중복만 찾는다. Returns (제목 중복 리포트, 날짜·종류 중복 리포트).

    슬롯 키의 `kind` 는 꼬리 숫자를 떼고 정규화한다. 파일명을 그대로 키로 쓰면 두
    파일이 같은 키를 가질 수 없어(파일시스템이 막는다) 검사가 구조적으로 도달
    불가가 된다. 실제 재발행은 `…-report-2.md` 처럼 꼬리 숫자가 붙어서 나므로,
    정규화해야 이 검사가 의미를 갖는다. 제목이 없는 포스트를 잡는 유일한 경로이기도
    하다.
    """
    by_title: dict[str, list[str]] = defaultdict(list)
    by_slot: dict[tuple[str, str], list[str]] = defaultdict(list)

    for path in sorted(POSTS_DIR.glob("*.md")):
        m = POST_TYPE_RE.match(path.name)
        if not m:
            continue
        kind = m.group("kind")
        if kind_filter and kind_filter not in kind:
            continue
        title = _post_title(path)
        if title:
            by_title[title].append(path.name)
        by_slot[(path.name[:10], KIND_SUFFIX_RE.sub("", kind))].append(path.name)

    title_dups = [f"{title!r} → {', '.join(files)}" for title, files in sorted(by_title.items()) if len(files) > 1]
    slot_dups = [
        f"{day} / {kind} → {', '.join(files)}" for (day, kind), files in sorted(by_slot.items()) if len(files) > 1
    ]
    return title_dups, slot_dups


def count_item_recurrence(kind_filter: str, recent: int) -> tuple[int, int]:
    """참고용 — 항목 URL 이 몇 개나 여러 포스트에 재등장하는가. 게이트 아님."""
    posts = [p for p in sorted(POSTS_DIR.glob("*.md")) if kind_filter in p.name][-recent:]
    seen: dict[str, set[str]] = defaultdict(set)
    for path in posts:
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        for url in set(URL_RE.findall(text)):
            # 자기 사이트 링크와 XML 네임스페이스는 항목이 아니다
            if "2twodragon" in url or "w3.org" in url:
                continue
            seen[url].add(path.name)
    return len([1 for files in seen.values() if len(files) > 1]), len(seen)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--collector", default="regulatory", help="수집기 이름 (기본: regulatory)")
    parser.add_argument("--days", type=int, default=7, help="커밋 집계 기간 (기본: 7일)")
    parser.add_argument(
        "--with-runs",
        action="store_true",
        help="gh CLI 로 워크플로우 로그에서 no-op skip 횟수까지 센다 (느림)",
    )
    parser.add_argument("--run-limit", type=int, default=12, help="--with-runs 시 조사할 실행 수")
    args = parser.parse_args()

    logger.info("no-op skip 파일럿 관측 — %s", args.collector)

    logger.info("[1] 수집기 커밋 수 (최근 %d일, KST)", args.days)
    counts = collect_commit_counts(args.collector, args.days)
    if not counts:
        logger.info("  해당 수집기 커밋 없음")
    for day in sorted(counts):
        logger.info("  %s  %d건  %s", day, counts[day], "#" * counts[day])

    logger.info("[2] no-op skip 발생 횟수")
    if args.with_runs:
        skips, checked, reason = collect_skip_counts(f"collect-{args.collector}.yml", args.run_limit)
        if reason:
            logger.info("  건너뜀: %s", reason)
        else:
            logger.info("  실행 %d건 중 skip %d건", checked, skips)
            if skips == 0:
                logger.warning("  표본 0 — 새 코드 경로가 실행되지 않았다. 절감 판정 불가.")
    else:
        logger.info("  건너뜀 (--with-runs 로 활성화)")

    logger.info("[3] 포스트 수준 중복 (게이트)")
    title_dups, slot_dups = check_post_duplicates(args.collector)
    logger.info("  제목 중복: %d건", len(title_dups))
    for line in title_dups:
        logger.warning("    %s", line)
    logger.info("  같은 날짜·종류 파일 중복: %d건", len(slot_dups))
    for line in slot_dups:
        logger.warning("    %s", line)

    dup_urls, total_urls = count_item_recurrence(args.collector, recent=8)
    logger.info("[참고] 항목 URL 재등장: %d/%d건 (최근 포스트 8개)", dup_urls, total_urls)
    logger.info("  게이트 아님 — 일일 리포트는 그 시점 피드의 스냅샷이라 설계상 반복된다.")

    failed = len(title_dups) + len(slot_dups)
    logger.info("판정: 포스트 수준 중복 %d건 → %s", failed, "FAIL" if failed else "PASS")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
