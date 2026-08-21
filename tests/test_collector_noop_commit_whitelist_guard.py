"""CI config regression guard: the no-op-commit whitelist never swallows dedup state.

## What the whitelist does

`main` 커밋 1건 = Vercel 배포 레코드 1건이다(2026-08-08 실측, SHA 1:1, 중복 0).
수집기 커밋 321건을 분류하면 41.1%(132건)가 `_state/` 안의 두 파일만 바꾼다 —
`image_rejection_metrics.json` 의 `last_seen` 한 줄과 `translation_cache.json` 의
번역 캐시 증분. 사이트 산출물에 영향이 없고 `ignoreCommand` 가 빌드도 이미
skip 하는데 배포 레코드만 만든다. `python-collect` 액션은 staged 집합이 그
화이트리스트의 부분집합이면 커밋 자체를 만들지 않는다.

## The incident this exists for

같은 스캔에서 **12.8%(41건)의 `_state`-only 커밋에는 `*_seen.json` 이 섞여 있다.**
이건 dedup 상태다 — 어떤 항목을 이미 처리했는지의 기록이고, 커밋되지 않으면
다음 실행이 같은 항목을 다시 발행할 수 있다(라이브 사이트에 중복 포스트).

화이트리스트에 `_state/crypto_news_seen.json` 한 줄을 더하는 것은 diff 한 줄이고,
리뷰에서 "이것도 어차피 `_state` 인데" 로 통과하기 쉽다. 그리고 실패는 조용하다:
CI 는 green 이고, 수집기도 성공으로 끝나며, 중복은 며칠 뒤 사이트에서만 보인다.
이 가드는 그 한 줄을 red 로 만든다.

`*_seen.json` 재평가가 결정적(deterministic)이라 버려도 안전한지는 **확인되지
않았다**. 확인되면 그때 이 가드의 판정 근거를 바꾸면 된다 — 지금은 "확인되지
않았으므로 금지" 가 옳은 기본값이다.

Direction: presence — 금지 패턴(`*_seen.json`, `*dedup*`)의 **부재**를 요구한다.
화이트리스트가 줄어드는 것은 안전한 방향이라 통과시킨다. 텍스트 스캔만 — PyYAML
없이, `docs/devsecops/ci-regression-guards.md` 규약을 따른다.
"""

from __future__ import annotations

import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_ACTION = _REPO_ROOT / ".github" / "actions" / "python-collect" / "action.yml"

# 액션이 화이트리스트를 담는 셸 변수. 이름이 바뀌면 아래 카나리가 먼저 실패한다.
_WHITELIST_RE = re.compile(r'^\s*NOOP_STATE_PATHS="(?P<paths>[^"]*)"\s*$', re.M)

# dedup 상태로 읽히는 경로 패턴. `*_seen.json` 이 실제 관측된 형태이고,
# `dedup` 는 같은 역할의 파일이 다른 이름으로 들어오는 경우를 덮는다.
_DEDUP_PATTERNS = (re.compile(r"_seen\.json$"), re.compile(r"dedup"))


def _action_text() -> str:
    return _ACTION.read_text(encoding="utf-8")


def _whitelist() -> list[str]:
    match = _WHITELIST_RE.search(_action_text())
    assert match, (
        f'`NOOP_STATE_PATHS="..."` not found in {_ACTION}. If the whitelist moved or was '
        "renamed, update `_WHITELIST_RE` here — do not delete this guard. If the no-op skip "
        "was removed entirely, remove this file and its row in "
        "docs/devsecops/ci-regression-guards.md in the same change."
    )
    return match.group("paths").split()


def _is_dedup_path(path: str) -> bool:
    return any(pattern.search(path) for pattern in _DEDUP_PATTERNS)


def test_action_file_exists() -> None:
    """Canary: a moved action file fails here rather than vacuously."""
    assert _ACTION.is_file(), f"{_ACTION} not found"
    assert _action_text().strip(), f"{_ACTION} is empty"


def test_whitelist_is_non_empty() -> None:
    """An empty whitelist makes every other assertion here vacuously true."""
    assert _whitelist(), (
        "`NOOP_STATE_PATHS` is empty. The no-op skip then never fires, so this guard would "
        "pass no matter what — and the 41% deployment-record saving it exists for is gone."
    )


def test_whitelist_excludes_dedup_state() -> None:
    """A dedup file on the whitelist means uncommitted dedup state → duplicate posts."""
    offenders = sorted(path for path in _whitelist() if _is_dedup_path(path))
    assert not offenders, (
        f"`NOOP_STATE_PATHS` lists dedup state: {offenders}. Those files record which items "
        "were already processed; if their change alone no longer produces a commit, the next "
        "run re-evaluates the same items and can publish duplicates on the live site. The "
        "whitelist is only for files whose change has no site effect — today that is the "
        "`last_seen` timestamp and the translation cache. Whether dropping dedup state is "
        "safe depends on re-evaluation being deterministic, which is NOT established."
    )


def test_whitelist_entries_are_state_paths() -> None:
    """Only `_state/` may be skipped — `_posts/` or `assets/` there would hide content."""
    strays = sorted(path for path in _whitelist() if not path.startswith("_state/"))
    assert not strays, (
        f"`NOOP_STATE_PATHS` lists non-`_state/` paths: {strays}. Content paths (`_posts/`, "
        "`assets/`) change the built site; skipping their commit means the site silently "
        "stops receiving posts while the collector still reports success."
    )


def test_skip_is_opt_in_per_collector() -> None:
    """Defaulting the input to `true` would roll the pilot out to all 13 collectors at once."""
    text = _action_text()
    block = re.search(r"^  skip-noop-state-commits:\s*$(?P<body>.*?)(?=^  \S|^runs:)", text, re.M | re.S)
    assert block, "`skip-noop-state-commits` input not found — was the pilot flag removed?"
    assert re.search(r"^\s{4}default:\s*'false'\s*$", block.group("body"), re.M), (
        "`skip-noop-state-commits` no longer defaults to 'false'. The default applies to every "
        "collector using this action, so flipping it enables the skip fleet-wide in one diff — "
        "the opposite of the staged rollout this flag exists for."
    )


def test_dedup_detector_is_bidirectional() -> None:
    """A detector loosened to match nothing would leave the assertions green.

    Without this, replacing `_DEDUP_PATTERNS` with an empty tuple would make
    `test_whitelist_excludes_dedup_state` pass for any whitelist at all.
    """
    for dedup in (
        "_state/crypto_news_seen.json",
        "_state/stock_news_seen.json",
        "_state/dedup_hashes.json",
    ):
        assert _is_dedup_path(dedup), f"detector misses dedup path {dedup!r}"

    for safe in (
        "_state/image_rejection_metrics.json",
        "_state/translation_cache.json",
    ):
        assert not _is_dedup_path(safe), f"detector flags safe path {safe!r}"
