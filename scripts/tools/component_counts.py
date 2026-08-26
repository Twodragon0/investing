#!/usr/bin/env python3
"""컴포넌트 카운트 단일 소스(single source of truth).

수집기/생성기/공통 모듈/워크플로우/카테고리 페이지/테스트 개수를 저장소에서
직접 계산한다. 문서에 하드코딩된 수치가 코드와 드리프트되는 것을 방지하기 위한
용도이며, 마커 블록(`<!-- component-counts:start -->` ~ `:end -->`)을 가진
문서를 자동 갱신하거나 검증할 수 있다.

사용법:
    python scripts/tools/component_counts.py                # 표 출력
    python scripts/tools/component_counts.py --json         # JSON 출력
    python scripts/tools/component_counts.py --write        # 마커 블록 갱신
    python scripts/tools/component_counts.py --check        # 드리프트 시 exit 1 (CI)

`--write`/`--check`는 기본적으로 docs/component-counts.md 를 대상으로 하며,
추가 파일 경로를 인자로 넘길 수 있다.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

START_MARKER = "<!-- component-counts:start -->"
END_MARKER = "<!-- component-counts:end -->"

DEFAULT_TARGET = REPO_ROOT / "docs" / "component-counts.md"


def _count_glob(pattern: str) -> int:
    """REPO_ROOT 기준 glob 매칭 개수."""
    return len(list(REPO_ROOT.glob(pattern)))


def _count_common_modules() -> int:
    """scripts/common 하위 .py 모듈 수 (재귀, __init__.py 제외)."""
    common = REPO_ROOT / "scripts" / "common"
    return sum(1 for p in common.rglob("*.py") if p.name != "__init__.py" and "__pycache__" not in p.parts)


#: 공유 수집 액션. 이 액션이 자체적으로 `git push origin main` 한다
#: (`.github/actions/python-collect/action.yml`).
PUSH_ACTION = "actions/python-collect"

#: 워크플로우가 자체적으로 푸시할 때 나타나는 토큰.
PUSH_MARKERS = ("git push", "git-auto-commit-action")


def main_push_workflows() -> list[Path]:
    """main 에 직접 푸시할 수 있는 워크플로우 목록.

    두 경로의 합집합이다:

    1. `PUSH_ACTION` 사용 — 그 공유 액션이 `git push origin main` 을 한다.
       워크플로우 본문에는 push 문자열이 없으므로 액션 참조로만 탐지된다.
    2. 워크플로우 본문에 `PUSH_MARKERS` 중 하나가 있음 — 자체 푸시.

    이 수치가 필요한 이유: 브랜치 보호에 required status check 를 걸면 직접 푸시가
    거부되므로, 몇 개의 푸시 지점을 고쳐야 하는지가 그대로 마이그레이션 비용이 된다
    (`docs/devsecops/branch-protection.md`).

    **휴리스틱이다.** main 이 아닌 ref 로 푸시하는 워크플로우가 생기면 과다 계수된다.
    `tests/test_component_counts.py` 가 매칭된 전건이 main 대상임을 단언해서 그
    가정이 조용히 깨지지 않게 한다.
    """
    workflows = REPO_ROOT / ".github" / "workflows"
    hits: list[Path] = []
    for path in sorted(workflows.glob("*.yml")):
        text = path.read_text(encoding="utf-8")
        if PUSH_ACTION in text or any(marker in text for marker in PUSH_MARKERS):
            hits.append(path)
    return hits


def compute_counts() -> dict[str, int]:
    """저장소에서 직접 계산한 컴포넌트 카운트."""
    return {
        "collectors": _count_glob("scripts/collect_*.py"),
        "generators": _count_glob("scripts/generate_*.py"),
        "common_modules": _count_common_modules(),
        "workflows": _count_glob(".github/workflows/*.yml"),
        "main_push_workflows": len(main_push_workflows()),
        "category_pages": _count_glob("pages/*.md"),
        "tests": _count_glob("tests/test_*.py"),
    }


# 표시 라벨 (한국어)
_LABELS = {
    "collectors": "수집기 (scripts/collect_*.py)",
    "generators": "생성기 (scripts/generate_*.py)",
    "common_modules": "공통 모듈 (scripts/common/**/*.py, __init__ 제외)",
    "workflows": "GitHub Actions 워크플로우 (.github/workflows/*.yml)",
    "main_push_workflows": "main 직접 푸시 워크플로우 (python-collect 경유 + 자체 push)",
    "category_pages": "카테고리 페이지 (pages/*.md)",
    "tests": "테스트 파일 (tests/test_*.py)",
}


def render_table(counts: dict[str, int]) -> str:
    """마커 블록에 들어갈 markdown 표를 생성한다."""
    lines = [
        START_MARKER,
        "",
        "> 이 표는 `scripts/tools/component_counts.py` 가 자동 생성한다. 직접 수정하지 마라.",
        "",
        "| 컴포넌트 | 개수 |",
        "| --- | --- |",
    ]
    for key, label in _LABELS.items():
        lines.append(f"| {label} | {counts[key]} |")
    lines.extend(["", END_MARKER])
    return "\n".join(lines)


def _replace_block(text: str, new_block: str) -> str:
    """마커 사이 내용을 new_block으로 교체. 마커가 없으면 예외."""
    start = text.find(START_MARKER)
    end = text.find(END_MARKER)
    if start == -1 or end == -1 or end < start:
        raise ValueError(f"마커({START_MARKER} ... {END_MARKER})를 찾을 수 없다")
    end += len(END_MARKER)
    return text[:start] + new_block + text[end:]


def write_targets(counts: dict[str, int], targets: list[Path]) -> None:
    block = render_table(counts)
    for target in targets:
        if target == DEFAULT_TARGET and not target.exists():
            # 기본 문서는 없으면 생성한다.
            header = "# 컴포넌트 카운트\n\n저장소 컴포넌트의 실측 개수. 문서 수치 드리프트를 막기 위한 단일 소스다.\n\n"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(header + block + "\n", encoding="utf-8")
            print(f"created {target.relative_to(REPO_ROOT)}")
            continue
        text = target.read_text(encoding="utf-8")
        target.write_text(_replace_block(text, block), encoding="utf-8")
        print(f"updated {target.relative_to(REPO_ROOT)}")


def check_targets(counts: dict[str, int], targets: list[Path]) -> int:
    """마커 블록이 실측과 일치하는지 검증. 불일치 시 1 반환."""
    block = render_table(counts)
    drift = 0
    for target in targets:
        if not target.exists():
            print(f"MISSING: {target.relative_to(REPO_ROOT)}")
            drift = 1
            continue
        text = target.read_text(encoding="utf-8")
        try:
            expected = _replace_block(text, block)
        except ValueError as exc:
            print(f"NO MARKERS in {target.relative_to(REPO_ROOT)}: {exc}")
            drift = 1
            continue
        if expected != text:
            print(f"DRIFT: {target.relative_to(REPO_ROOT)} — --write 로 갱신 필요")
            drift = 1
        else:
            print(f"OK: {target.relative_to(REPO_ROOT)}")
    return drift


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="컴포넌트 카운트 단일 소스")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--json", action="store_true", help="JSON 출력")
    group.add_argument("--write", action="store_true", help="마커 블록 갱신")
    group.add_argument("--check", action="store_true", help="드리프트 시 exit 1")
    parser.add_argument(
        "files",
        nargs="*",
        help="--write/--check 대상 파일 (기본: docs/component-counts.md)",
    )
    args = parser.parse_args(argv)

    counts = compute_counts()
    targets = [Path(f).resolve() for f in args.files] or [DEFAULT_TARGET]

    if args.json:
        print(json.dumps(counts, ensure_ascii=False, indent=2))
        return 0
    if args.write:
        write_targets(counts, targets)
        return 0
    if args.check:
        return check_targets(counts, targets)

    # 기본: 표 출력
    print(render_table(counts))
    return 0


if __name__ == "__main__":
    sys.exit(main())
