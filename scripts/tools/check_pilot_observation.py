#!/usr/bin/env python3
"""no-op 커밋 스킵 파일럿의 관측 지표를 집계한다.

`docs/devsecops/collector-push-batching-design.md` 의 관측 게이트 두 개를
측정 가능한 형태로 좁힌 것이다.

측정하는 것
-----------
1. 수집기 커밋 수 (일자별) — 절감이 실제로 일어났는가
2. no-op skip 발생 횟수 — 새 코드 경로가 실행되기는 했는가 (표본 0이면 판정 불가)
3. 중복 포스트 — 아래 "좁힌 정의" 참조
4. 부하 보정 절감 — 아래 "부하 보정" 참조
5. 포착률 — 아래 "포착률" 참조

포착률
------
절감 %는 표본이 작을 때 판정에 쓸 수 없다. 파일럿 후 4실행(2026-08-11 시점)이면
skip 비율의 95% 신뢰구간 폭이 0.53 이라 51.9%(파일럿 전 실측 no-op 비율)와 25%를
구분하지 못한다. 해상도는 √n 으로만 늘어서 regulatory 단독 30일 관측이 폭 0.20 이다.

포착률은 표본이 작아도 판정된다. 묻는 것이 비율이 아니라 **사건의 유무**이기 때문:

- **누출** — 파일럿 후에도 화이트리스트 부분집합 커밋이 남아 있는가. 1건이라도
  있으면 skip 이 동작하지 않은 것이다. git 만으로 판정된다.
- **오검출** — skip 이 화이트리스트 **밖**까지 버렸는가. 1건이라도 있으면 dedup
  상태나 콘텐츠가 유실된 것이다. gh 로그가 필요하다(`--with-runs`).

화이트리스트는 액션(`NOOP_STATE_PATHS`)에서 읽는다. 여기 상수로 복사하면 액션이
바뀔 때 조용히 어긋나고, 어긋난 화이트리스트는 판정을 거짓 PASS 로 만든다. 읽기에
실패하면 빈 집합으로 폴백하지 않고 **판정을 보류**한다 — 빈 집합이면 모든
`_state`-only 커밋이 "부분집합 아님" 이 되어 누출 0건으로 보인다.

부하 보정
---------
지표 1의 **원값은 절감의 증거가 되지 못한다.** 커밋 수는 그날 수집기가 몇 번
돌았는지, 뉴스가 얼마나 나왔는지에 따라 파일럿과 무관하게 움직인다. 파일럿 전후를
원값으로 비교하면 그 변동이 절감으로 위장한다.

두 비율로 나눠 본다. 교란원이 서로 달라 교차 검증이 된다:

- **실행당 커밋** = 수집기 커밋 수 / 워크플로우 실행 수. "몇 번 돌았나" 를 상쇄한다.
  파일럿이 직접 건드리는 축이라 해석이 가장 곧다 — 실행 한 번이 커밋을 만들 확률.
- **대조군 비** = 수집기 커밋 수 / 파일럿 미적용 수집기들의 커밋 수. 뉴스량처럼
  모든 수집기에 공통으로 걸리는 변동을 상쇄한다 (difference-in-differences).

`main` 총 커밋 수를 분모로 쓰지 않는 이유: 그 값은 PR 머지에 지배된다(08-07 은
61건 중 25건이 PR 머지 — 개발 활동 스파이크이지 정상 부하가 아니다). 개발이 활발한
날 regulatory 비중이 파일럿과 무관하게 떨어져 절감으로 오독된다.

전·후 구간의 길이가 달라도 된다 — 둘 다 비율이라 기간에 정규화돼 있다.

한계 두 가지, 명시해 둔다:

- **경계 귀속**. 커밋은 커밋 시각으로, 실행은 실행 시작 시각으로 각각 나눈다. 머지
  직전에 시작해 직후에 커밋한 실행은 분자와 분모가 갈릴 수 있다 — 최대 1실행.
  후 구간 표본이 작을 때 무시할 수 없으므로 분자/분모 원값을 함께 출력한다.
- **대조군 오염**. 파일럿을 다른 수집기로 확대하면 그 수집기는 대조군에서 빼야
  한다. `CONTROL_COLLECTORS` 를 갱신하지 않으면 분모도 함께 줄어 절감이 과소평가된다.

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
  python scripts/tools/check_pilot_observation.py --pilot-merged 2026-08-10T13:14:51+09:00

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
from typing import NamedTuple
from urllib.parse import urlparse

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
# 항목 재등장 집계에서 제외할 호스트 — 자기 사이트와 XML 네임스페이스
NON_ITEM_HOSTS = ("2twodragon.com", "w3.org")

DEFAULT_COLLECTOR = "regulatory"

# 파일럿이 main 에 들어온 시각 — 커밋 5297e40bb
# "feat: no-op 수집기 커밋을 만들지 않는다 (regulatory 파일럿) …(#1148)"
PILOT_MERGED_DEFAULT = "2026-08-10T13:14:51+09:00"

# 대조군 — no-op 커밋을 실제로 만들면서 파일럿이 **적용되지 않은** 수집기.
#
# 나머지 7개 수집기는 설계 문서 실측(최근 600커밋)에서 no-op 커밋이 0건이다. 넣어도
# 파일럿에 반응할 수 없는 상수 항이라 분모만 키워 비율의 민감도를 떨어뜨린다.
#
# 파일럿을 확대하면 그 수집기를 여기서 빼야 한다. 안 빼면 분모도 같이 줄어 절감이
# 과소평가된다. `tests/test_check_pilot_observation_load_adjusted.py` 가 파일럿
# 대상이 이 목록에 들어오는 경우를 red 로 만든다.
CONTROL_COLLECTORS = ("crypto", "stock", "social", "political", "geopolitical")

# 설계 문서의 "수집기 1개에 먼저 적용해 최소 3일 관측" 게이트.
MIN_OBSERVATION_DAYS = 3

# 화이트리스트는 액션이 원본이다. 여기 상수로 복사하면 액션이 바뀔 때 조용히 어긋나고,
# 그 어긋남은 포착률을 거짓 PASS 로 만든다.
ACTION_PATH = REPO_ROOT / ".github" / "actions" / "python-collect" / "action.yml"
NOOP_PATHS_RE = re.compile(r'^\s*NOOP_STATE_PATHS="(?P<paths>[^"]*)"\s*$', re.M)

# 사이트 산출물 — 이게 섞이면 무조건 커밋돼야 한다.
CONTENT_PREFIXES = ("_posts/", "assets/")

# skip 로그에서 파일 목록 줄을 가려내는 형태. 경로는 공백을 포함하지 않는다.
SKIP_PATH_RE = re.compile(r"^[\w./-]+$")


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


def commit_log(days: int) -> str:
    """`origin/main` 의 최근 커밋을 `<ISO>|<subject>` 줄로 가져온다.

    한 번 가져와 여러 수집기에 대해 파싱한다 — 수집기마다 git 을 다시 돌리면 대조군
    6축에 6번 돈다.
    """
    return _git("log", "origin/main", f"--since={days + 1}.days.ago", "--format=%cI|%s")


def parse_commit_timestamps(raw: str, collector: str) -> list[datetime]:
    """커밋 로그에서 해당 수집기 커밋의 시각만 KST 로 뽑는다.

    주제 매칭은 `collect <name>` 접두 — `collect political` 이
    `collect geopolitical news` 를 잡아채지 않는다(두 축이 하나로 합쳐지면 대조군
    분모가 조용히 틀어진다). 파싱 불가한 줄은 건너뛴다.
    """
    needle = f"collect {collector}".lower()
    stamps: list[datetime] = []
    for line in raw.splitlines():
        if "|" not in line:
            continue
        iso, subject = line.split("|", 1)
        if needle not in subject.lower():
            continue
        try:
            stamps.append(datetime.fromisoformat(iso).astimezone(KST))
        except ValueError:
            logger.warning("커밋 시각 파싱 실패: %s", iso)
    return stamps


def collect_commit_counts(collector: str, days: int) -> dict[str, int]:
    """수집기 커밋을 KST 일자별로 센다."""
    by_day: Counter[str] = Counter()
    for when in parse_commit_timestamps(commit_log(days), collector):
        by_day[when.date().isoformat()] += 1
    return dict(by_day)


def split_by_pilot(stamps: list[datetime], pilot_merged: datetime) -> tuple[int, int]:
    """(파일럿 전, 후) 개수. 머지 시각과 같은 순간은 '후' 다.

    들어오는 시각의 타임존이 섞여 있어도 된다(커밋은 KST, gh 실행은 UTC) — 비교는
    aware datetime 끼리라 절대 시각으로 이뤄진다.
    """
    pre = post = 0
    for stamp in stamps:
        if stamp < pilot_merged:
            pre += 1
        else:
            post += 1
    return pre, post


class LoadRatio(NamedTuple):
    """파일럿 전·후의 분자/분모 원값. 비율은 메서드로 파생한다.

    원값을 들고 다니는 이유: 후 구간 표본이 한 자릿수라 `0.67` 만 봐서는 2/3인지
    20/30인지 구분이 안 되는데 둘의 신뢰도는 전혀 다르다.
    """

    pre_num: int
    pre_den: int
    post_num: int
    post_den: int

    def pre(self) -> float | None:
        """분모가 0이면 None — 0.0 을 돌려주면 '절감 100%' 로 읽힌다."""
        return self.pre_num / self.pre_den if self.pre_den else None

    def post(self) -> float | None:
        return self.post_num / self.post_den if self.post_den else None

    def delta_pct(self) -> float | None:
        """전 대비 후의 변화율(%). 음수가 절감이다."""
        pre, post = self.pre(), self.post()
        if pre is None or post is None or pre == 0:
            return None
        return (post - pre) / pre * 100


def build_ratio(
    numerator: list[datetime],
    denominator: list[datetime],
    pilot_merged: datetime,
    since: datetime | None = None,
) -> LoadRatio:
    """두 시각 계열을 파일럿 경계로 갈라 분자/분모 쌍을 만든다.

    `since` 는 두 계열에 **같은** 창을 강제한다. 커밋은 git `--since` 로, 실행은 gh
    `--limit` 으로 각각 잘려 오기 때문에 그대로 두면 창이 어긋난다 — 실행 쪽이 더
    멀리까지 오면 전 구간 분모만 부풀어 절감이 과대평가된다.
    """
    if since is not None:
        numerator = [t for t in numerator if t >= since]
        denominator = [t for t in denominator if t >= since]
    pre_num, post_num = split_by_pilot(numerator, pilot_merged)
    pre_den, post_den = split_by_pilot(denominator, pilot_merged)
    return LoadRatio(pre_num, pre_den, post_num, post_den)


def is_underpowered(pilot_merged: datetime, now: datetime) -> bool:
    """관측 기간이 설계 게이트(3일)에 못 미치는가."""
    return now - pilot_merged < timedelta(days=MIN_OBSERVATION_DAYS)


def collect_run_timestamps(workflow: str, limit: int) -> tuple[list[datetime], str | None]:
    """gh CLI 로 워크플로우 실행 시작 시각을 가져온다.

    `collect_skip_counts` 와 달리 목록 한 번만 부른다(로그를 받지 않는다). gh 가
    없으면 ([], 이유) 로 graceful degradation — 대조군 비 쪽은 그래도 계산된다.
    """
    try:
        listing = subprocess.run(
            ["gh", "run", "list", f"--workflow={workflow}", f"--limit={limit}", "--json", "createdAt"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
    except FileNotFoundError:
        return [], "gh CLI 미설치"
    except subprocess.CalledProcessError as e:
        return [], f"gh run list 실패 ({e.returncode})"

    try:
        runs = json.loads(listing.stdout)
    except json.JSONDecodeError:
        return [], "gh 출력 파싱 실패"

    stamps: list[datetime] = []
    for run in runs:
        created = run.get("createdAt")
        if not created:
            continue
        try:
            stamps.append(datetime.fromisoformat(created.replace("Z", "+00:00")).astimezone(KST))
        except ValueError:
            logger.warning("실행 시각 파싱 실패: %s", created)
    return stamps, None


def collect_skip_counts(workflow: str, limit: int) -> tuple[int, int, str | None, list[list[str]]]:
    """gh CLI 로 워크플로우 실행 로그에서 skip 발생 횟수와 버린 파일 목록을 센다.

    Returns (skip 횟수, 조사한 실행 수, 건너뛴 이유, skip 블록들). gh 가 없거나
    인증이 없으면 (0, 0, 이유, []) 로 graceful degradation.

    파일 목록까지 같은 로그에서 뽑는 이유: 오검출 판정([5])에 필요한데, 로그를 다시
    받으면 실행당 수 초가 두 배로 든다.
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
        return 0, 0, "gh CLI 미설치", []
    except subprocess.CalledProcessError as e:
        return 0, 0, f"gh run list 실패 ({e.returncode})", []

    try:
        runs = json.loads(listing.stdout)
    except json.JSONDecodeError:
        return 0, 0, "gh 출력 파싱 실패", []

    skips = 0
    checked = 0
    blocks: list[list[str]] = []
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
        found = parse_skip_paths(log.stdout)
        if found:
            skips += 1
            blocks.extend(found)
    return skips, checked, None, blocks


def read_noop_whitelist() -> frozenset[str] | None:
    """액션의 `NOOP_STATE_PATHS` 를 읽는다. 읽지 못하면 None.

    **빈 집합으로 폴백하면 안 된다.** 모든 `_state`-only 커밋이 "부분집합 아님" 이
    되어 누출 0건 — 거짓 PASS 가 난다. None 을 돌려 판정 자체를 보류시킨다.
    """
    try:
        text = ACTION_PATH.read_text(encoding="utf-8")
    except OSError as e:
        logger.warning("액션 파일을 읽지 못했다 %s: %s", ACTION_PATH, e)
        return None
    match = NOOP_PATHS_RE.search(text)
    if not match:
        logger.warning('`NOOP_STATE_PATHS="..."` 를 %s 에서 찾지 못했다', ACTION_PATH)
        return None
    paths = frozenset(match.group("paths").split())
    return paths or None


def classify_commit(paths: list[str], whitelist: frozenset[str]) -> str:
    """커밋을 content / noop / state_other 로 가른다.

    `noop` 은 "파일럿이 있었다면 skip 됐어야 하는 것" 이다. 콘텐츠가 섞이면 무조건
    content, 화이트리스트 밖 `_state`(주로 dedup)가 섞이면 state_other 다. 빈 커밋은
    noop 이 아니다 — 버릴 것이 없었던 것이지 skip 대상이 아니다.
    """
    if any(p.startswith(CONTENT_PREFIXES) for p in paths):
        return "content"
    if paths and set(paths) <= whitelist:
        return "noop"
    return "state_other"


class CollectorCommit(NamedTuple):
    when: datetime
    sha: str
    paths: tuple[str, ...]


def commit_paths(sha: str) -> tuple[str, ...]:
    return tuple(_git("show", "--format=", "--name-only", sha).split())


def collect_collector_commits(collector: str, days: int) -> list[CollectorCommit]:
    """해당 수집기의 커밋을 (시각, sha, 변경 파일) 로 모은다."""
    raw = _git("log", "origin/main", f"--since={days + 1}.days.ago", "--format=%cI|%H|%s")
    needle = f"collect {collector}".lower()
    commits: list[CollectorCommit] = []
    for line in raw.splitlines():
        parts = line.split("|", 2)
        if len(parts) != 3:
            continue
        iso, sha, subject = parts
        if needle not in subject.lower():
            continue
        try:
            when = datetime.fromisoformat(iso).astimezone(KST)
        except ValueError:
            logger.warning("커밋 시각 파싱 실패: %s", iso)
            continue
        commits.append(CollectorCommit(when=when, sha=sha, paths=commit_paths(sha)))
    return commits


def find_leaks(
    commits: list[CollectorCommit],
    pilot_merged: datetime,
    whitelist: frozenset[str],
) -> tuple[list[CollectorCommit], Counter[str]]:
    """파일럿 후에도 살아남은 no-op 커밋(=누출)과 후 구간 분류 집계.

    누출 1건은 skip 이 동작하지 않았다는 뜻이다. 비율이 아니라 사건의 유무라 표본이
    작아도 판정된다.
    """
    leaks: list[CollectorCommit] = []
    counts: Counter[str] = Counter()
    for commit in commits:
        if commit.when < pilot_merged:
            continue
        kind = classify_commit(list(commit.paths), whitelist)
        counts[kind] += 1
        if kind == "noop":
            leaks.append(commit)
    return leaks, counts


def parse_skip_paths(log: str) -> list[list[str]]:
    """skip 로그에서 "무엇을 버렸는가" 목록을 블록 단위로 뽑는다.

    액션 본문이 에코된 줄은 `is_runtime_skip_line` 이 걸러낸다 — 그 줄을 세면 커밋한
    실행까지 skip 으로 잡히고 오검출 판정이 통째로 오염된다.
    """
    blocks: list[list[str]] = []
    current: list[str] | None = None
    for line in log.splitlines():
        if is_runtime_skip_line(line):
            if current is not None:
                blocks.append(current)
            current = []
            continue
        if current is None:
            continue
        payload = LOG_TS_RE.sub("", ANSI_RE.sub("", line.rsplit("\t", 1)[-1])).strip()
        if SKIP_PATH_RE.match(payload) and "/" in payload:
            current.append(payload)
        else:
            blocks.append(current)
            current = None
    if current is not None:
        blocks.append(current)
    return blocks


def find_overreach(blocks: list[list[str]], whitelist: frozenset[str]) -> list[list[str]]:
    """화이트리스트 **밖**까지 버린 skip 블록. 1건이라도 있으면 상태 유실이다.

    빈 블록도 flag 한다 — 무엇을 버렸는지 모르는 skip 은 안전을 주장할 수 없다.
    """
    return [b for b in blocks if not b or not set(b) <= whitelist]


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


def is_non_item_host(url: str) -> bool:
    """자기 사이트 링크와 XML 네임스페이스는 뉴스 항목이 아니다.

    호스트를 `urlparse` 로 뽑아 정확히 비교한다. `"w3.org" in url` 같은 부분 문자열
    검사는 `https://evil.com/?x=w3.org` 도 통과시킨다(CodeQL
    `py/incomplete-url-substring-sanitization`).
    """
    host = (urlparse(url).hostname or "").lower()
    return any(host == h or host.endswith(f".{h}") for h in NON_ITEM_HOSTS)


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
            if is_non_item_host(url):
                continue
            seen[url].add(path.name)
    return len([1 for files in seen.values() if len(files) > 1]), len(seen)


def _fmt_ratio(value: float | None, digits: int = 2) -> str:
    return "n/a" if value is None else f"{value:.{digits}f}"


def _fmt_delta(value: float | None) -> str:
    return "n/a" if value is None else f"{value:+.1f}%"


def report_load_adjusted(collector: str, days: int, pilot_merged: datetime, now: datetime) -> None:
    """[4] 부하 보정 절감 — 실행당 커밋과 대조군 비를 나란히 출력한다.

    판정을 내리지 않는다. 이 스크립트의 종료 코드는 포스트 수준 중복만 본다 —
    절감은 측정 대상이지 게이트가 아니다.
    """
    logger.info("[4] 부하 보정 절감 (파일럿 머지 %s)", pilot_merged.isoformat())

    # 커밋과 실행에 같은 창을 강제한다. git `--since` 와 gh `--limit` 은 서로 다른
    # 기준으로 자르므로 여기서 한 번 더 맞추지 않으면 분모만 멀리까지 샌다.
    window_start = now - timedelta(days=days)
    raw = commit_log(days)
    pilot_commits = parse_commit_timestamps(raw, collector)

    # 실행은 최대 6회/일을 가정하고 여유를 둔다 — 부족하면 전 구간이 잘려 나간다.
    runs, reason = collect_run_timestamps(f"collect-{collector}.yml", limit=max(30, days * 6))
    if reason:
        logger.info("  실행당 커밋: 건너뜀 (%s)", reason)
    else:
        per_run = build_ratio(pilot_commits, runs, pilot_merged, since=window_start)
        logger.info(
            "  실행당 커밋   전 %s (%d/%d)  후 %s (%d/%d)  → %s",
            _fmt_ratio(per_run.pre()),
            per_run.pre_num,
            per_run.pre_den,
            _fmt_ratio(per_run.post()),
            per_run.post_num,
            per_run.post_den,
            _fmt_delta(per_run.delta_pct()),
        )

    control_commits = [t for name in CONTROL_COLLECTORS for t in parse_commit_timestamps(raw, name)]
    versus = build_ratio(pilot_commits, control_commits, pilot_merged, since=window_start)
    logger.info("  대조군: %s", ", ".join(CONTROL_COLLECTORS))
    logger.info(
        "  대조군 비    전 %s (%d/%d)  후 %s (%d/%d)  → %s",
        _fmt_ratio(versus.pre(), 3),
        versus.pre_num,
        versus.pre_den,
        _fmt_ratio(versus.post(), 3),
        versus.post_num,
        versus.post_den,
        _fmt_delta(versus.delta_pct()),
    )

    elapsed_days = (now - pilot_merged).total_seconds() / 86400
    if is_underpowered(pilot_merged, now):
        logger.warning(
            "  ⚠ 관측 %.1f일 < %d일 — 판정 보류. 위 숫자는 방향 참고용이다.",
            elapsed_days,
            MIN_OBSERVATION_DAYS,
        )
    else:
        logger.info("  관측 %.1f일 — 게이트(%d일) 충족", elapsed_days, MIN_OBSERVATION_DAYS)


def report_capture_rate(
    collector: str,
    days: int,
    pilot_merged: datetime,
    skip_blocks: list[list[str]] | None,
) -> bool | None:
    """[5] 포착률 — 누출 0건 · 오검출 0건인가. None 이면 판정 불가.

    절감 %와 달리 표본이 작아도 판정된다. 묻는 것이 비율이 아니라 사건의 유무라
    n=4 로도 반증 가능하다.

    `skip_blocks` 가 None 이면 오검출은 확인하지 않는다(gh 로그가 필요하다). 그
    경우에도 누출은 git 만으로 판정되므로 절 전체를 건너뛰지는 않는다.
    """
    logger.info("[5] 포착률 (누출 0건 · 오검출 0건)")

    whitelist = read_noop_whitelist()
    if whitelist is None:
        logger.warning("  판정 불가 — 액션에서 화이트리스트를 읽지 못했다.")
        return None
    logger.info("  화이트리스트(액션 기준): %s", ", ".join(sorted(whitelist)))

    leaks, counts = find_leaks(collect_collector_commits(collector, days), pilot_merged, whitelist)
    total = sum(counts.values())
    logger.info(
        "  파일럿 후 커밋 %d건 — 콘텐츠 %d / _state+dedup 등 %d / no-op %d",
        total,
        counts.get("content", 0),
        counts.get("state_other", 0),
        counts.get("noop", 0),
    )
    if leaks:
        logger.warning("  누출 %d건 — skip 이 동작하지 않았다:", len(leaks))
        for commit in leaks:
            logger.warning("    %s %s  %s", commit.when.isoformat(), commit.sha[:9], " ".join(commit.paths))
    else:
        logger.info("  누출 0건")

    if skip_blocks is None:
        logger.info("  오검출: 미확인 (--with-runs 로 활성화)")
        overreach: list[list[str]] = []
    else:
        overreach = find_overreach(skip_blocks, whitelist)
        if overreach:
            logger.warning("  오검출 %d건 — 화이트리스트 밖까지 버렸다:", len(overreach))
            for block in overreach:
                logger.warning("    %s", " ".join(block) or "(파일 목록 없음)")
        else:
            logger.info("  오검출 0건 (skip %d건 검사)", len(skip_blocks))

    passed = not leaks and not overreach
    logger.info("  포착률 판정: %s", "PASS" if passed else "FAIL")
    return passed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--collector", default=DEFAULT_COLLECTOR, help=f"수집기 이름 (기본: {DEFAULT_COLLECTOR})")
    parser.add_argument(
        "--pilot-merged",
        default=PILOT_MERGED_DEFAULT,
        help=f"파일럿 머지 시각 ISO (기본: {PILOT_MERGED_DEFAULT})",
    )
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
    skip_blocks: list[list[str]] | None = None
    if args.with_runs:
        skips, checked, reason, skip_blocks = collect_skip_counts(f"collect-{args.collector}.yml", args.run_limit)
        if reason:
            logger.info("  건너뜀: %s", reason)
            skip_blocks = None
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

    try:
        pilot_merged = datetime.fromisoformat(args.pilot_merged)
    except ValueError:
        logger.error("--pilot-merged 파싱 실패: %s", args.pilot_merged)
        return 2
    if pilot_merged.tzinfo is None:
        logger.error("--pilot-merged 에 타임존이 없다: %s (예: %s)", args.pilot_merged, PILOT_MERGED_DEFAULT)
        return 2
    report_load_adjusted(args.collector, args.days, pilot_merged, datetime.now(KST))
    report_capture_rate(args.collector, args.days, pilot_merged, skip_blocks)

    dup_urls, total_urls = count_item_recurrence(args.collector, recent=8)
    logger.info("[참고] 항목 URL 재등장: %d/%d건 (최근 포스트 8개)", dup_urls, total_urls)
    logger.info("  게이트 아님 — 일일 리포트는 그 시점 피드의 스냅샷이라 설계상 반복된다.")

    failed = len(title_dups) + len(slot_dups)
    logger.info("판정: 포스트 수준 중복 %d건 → %s", failed, "FAIL" if failed else "PASS")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
