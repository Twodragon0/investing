"""`_state` 임시 파일이 커밋될 수 없어야 한다.

## 왜 있나

`_state` 의 모든 쓰기는 원자적이다 — `tempfile.mkstemp(dir=_state, suffix=".tmp")`
로 쓰고 `os.replace` 로 바꿔치기한다. 성공하면 temp 는 rename 에 소비되므로
밀리초만 존재한다. 하지만 프로세스가 그 사이에 죽으면 남는다. 2026-09-07 백필 런이
`_state/` 에 ~900KB 짜리 고아 4개를 남긴 게 실측 사례다
(`scripts/common/translator.py` 의 cleanup 주석 참조).

문제는 수집 워크플로우가 이렇게 스테이징한다는 것이다:

    git-add-paths: '_posts/ _state/ assets/images/'
    → for path in ...; do git add "$path"; done

`_state/` 전체를 `git add` 하므로, CI 러너에서 같은 누출이 일어나면 900KB 짜리
임시 blob 이 저장소 히스토리에 그대로 들어간다. 자동 커밋이라 사람 눈을 거치지도
않는다. `.tmp` 는 어떤 상황에서도 커밋 대상이 아니므로 `.gitignore` 로 표현
불가능하게 만든다.

주의: 무시한다고 탐지까지 없어지지는 않는다. 고아 자체는
`scripts/tools/check_state_orphans.py` 가 나이 기준으로 잡고,
`scripts/ops/health_and_logrotate.sh` 가 그걸 호출한다.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent


def _check_ignore(relative_path: str) -> bool:
    """`git check-ignore` 로 실제 무시 여부를 묻는다 (.gitignore 문자열 매칭이 아니라)."""
    result = subprocess.run(
        ["git", "check-ignore", "-q", "--no-index", relative_path],
        cwd=_REPO_ROOT,
        capture_output=True,
        check=False,
    )
    if result.returncode not in (0, 1):
        pytest.skip(f"git check-ignore unavailable: {result.stderr.decode(errors='replace')}")
    return result.returncode == 0


@pytest.mark.parametrize(
    "path",
    [
        "_state/tmp0kxjtma9.tmp",
        "_state/tmpABCDEFGH.tmp",
    ],
)
def test_state_temp_files_are_ignored(path: str) -> None:
    assert _check_ignore(path), (
        f"{path} is committable. The collect workflows run `git add _state/`, so an "
        "orphaned atomic-write temp (~900KB, seen 2026-09-07) would land in history "
        "via an unreviewed auto-commit."
    )


def test_real_state_files_are_still_tracked() -> None:
    """반대 방향: 무시 규칙이 넓어져 상태 JSON 까지 삼키면 중복 방지가 조용히 죽는다."""
    assert not _check_ignore("_state/crypto_news.json"), (
        "`_state/*.json` must stay tracked — it is the cross-run dedup state, and "
        "ignoring it would silently re-publish already-collected items."
    )
