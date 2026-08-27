#!/usr/bin/env bash
#
# dev_sync_state_safe.sh — skip-worktree 를 넘어 로컬 main 을 안전하게 fast-forward
#
# ## 문제
#
# `dev_ignore_state.sh` 가 `_state/*.json` 에 skip-worktree 를 걸어 두면 git status 는
# 깨끗해지지만, **로컬 변경이 인덱스에 남아 있어 fast-forward 가 거부된다**:
#
#     $ gh pr merge 1234 --squash --delete-branch
#     error: Your local changes to the following files would be overwritten by merge:
#         _state/image_rejection_metrics.json
#     Aborting
#     Updating abc1234..def5678
#     ! warning: not possible to fast-forward to: "main"
#
# 원격 머지는 성공했는데 로컬만 뒤처진다. 2026-08-26 한 세션에서 세 번 발생했고
# 매번 손으로 같은 순서를 반복했다: un-skip → 되돌리기 → pull → 다시 skip.
#
# ## 왜 `gh pr merge` 래퍼가 아닌가
#
# 실패 지점은 머지가 아니라 **로컬 동기화**다. 같은 일이 평범한 `git pull` 에서도
# 난다. 래퍼로 만들면 `gh pr merge` 의 플래그를 계속 따라가야 하는데 얻는 게 없다.
# 그래서 독립 스크립트로 두고, 머지 뒤에 이어서 실행한다:
#
#     gh pr merge 1234 --squash --delete-branch
#     bash scripts/dev_sync_state_safe.sh
#
# ## 이 스크립트가 버리는 것과 버리지 않는 것
#
# `_state/*.json` 의 로컬 변경은 수집기가 다시 만들어내는 파생물이므로 버린다.
# 그 외에는 **아무것도 버리지 않는다** — `_state` 밖에 변경이 있으면 즉시 중단한다.
#
# 안전장치:
#   - `_state` 밖 dirty 파일이 하나라도 있으면 중단 (커밋/stash 를 사람이 결정)
#   - `_state` 파일의 diff 가 커지면(기본 20줄 초과) 중단하고 `--force` 를 요구.
#     타임스탬프 한 줄 bump 는 안전하지만 큰 diff 는 실제 내용일 수 있다.
#   - 실패 시 skip-worktree 를 원상 복구한다 (중간 상태로 방치하지 않는다)
#
# 순서상 한 가지 알아둘 것: dirty 한 상태로는 pull 이 안 되므로 **버리기가 pull 보다
# 먼저**다. 따라서 pull 이 실패하면(upstream 없음, non-FF 등) `_state` 변경은 이미
# 버려진 뒤다. 버린 내용은 수집기가 다시 만들므로 손실이 아니지만, 순서를 뒤집을 수는
# 없다는 점은 알고 있어야 한다. 그 경우에도 skip-worktree 는 복구되고 종료코드는 1 이다.
#
# 사용법:
#   bash scripts/dev_sync_state_safe.sh              # 동기화
#   bash scripts/dev_sync_state_safe.sh --dry-run    # 무엇을 할지만 출력
#   bash scripts/dev_sync_state_safe.sh --force      # 큰 _state diff 도 버림
#
# 관련: docs/state-friction-mitigation.md, scripts/dev_ignore_state.sh

set -euo pipefail

# bash 4+ 필요 — `mapfile` 이 4.0 빌트인이다. macOS 기본 `/bin/bash` 는 3.2 라서
# 가드가 없으면 `mapfile: command not found` (exit 127) 만 남는다. 원인도 조치도
# 알 수 없는 메시지다.
#
# `set -e` 가 그 지점에서 멈춰 주므로 지금은 파괴적이지 않지만, 그건 mapfile 이
# 우연히 첫 동작이라서다. 위치가 바뀌면 조용한 오작동이 된다 — SKIPPED 가 빈
# 배열이면 이 스크립트는 "skip-worktree 파일 없음" 으로 판단하고 평범한 pull 로
# 넘어간다. 인터프리터 요구사항은 실행 순서에 의존하지 않는 곳에서 검사한다.
if (( BASH_VERSINFO[0] < 4 )); then
  echo "error: bash 4 이상이 필요합니다 (mapfile 빌트인). 현재: ${BASH_VERSION}" >&2
  echo >&2
  echo "macOS 기본 /bin/bash 는 3.2 입니다. Homebrew bash 로 실행하세요:" >&2
  echo "  brew install bash" >&2
  echo "  bash scripts/dev_sync_state_safe.sh   # PATH 의 bash (Homebrew)" >&2
  exit 1
fi

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || true)"
if [[ -z "${REPO_ROOT}" ]]; then
  echo "error: git 레포 내부에서 실행하세요." >&2
  exit 1
fi
cd "${REPO_ROOT}"

DRY_RUN=false
FORCE=false
# _state 파일 하나가 이 줄 수를 넘게 바뀌면 타임스탬프 bump 가 아니라고 본다.
MAX_STATE_DIFF_LINES=20

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run) DRY_RUN=true ;;
    --force)   FORCE=true ;;
    *)
      echo "error: 알 수 없는 인자 '$1'. 사용법: [--dry-run] [--force]" >&2
      exit 1
      ;;
  esac
  shift
done

# skip-worktree 가 걸린 파일 목록을 먼저 기록해 둔다 — 실패 시 이걸로 복구한다.
mapfile -t SKIPPED < <(git ls-files -v | sed -n 's/^S //p')

restore_skip_worktree() {
  if [[ ${#SKIPPED[@]} -gt 0 ]]; then
    git update-index --skip-worktree -- "${SKIPPED[@]}" 2>/dev/null || true
  fi
}

echo "== 현재 상태 =="
echo "  skip-worktree 파일: ${#SKIPPED[@]}개"
git status --short --branch | head -1

if [[ ${#SKIPPED[@]} -eq 0 ]]; then
  echo
  echo "info: skip-worktree 파일이 없습니다. 평범한 pull 로 충분합니다."
  ${DRY_RUN} || git pull --ff-only
  exit 0
fi

echo
echo "→ skip-worktree 해제 (로컬 변경을 노출시켜 판정한다)"
# dry-run 에서도 해제한다. 해제는 인덱스 플래그만 바꾸고 파일 내용은 건드리지 않는다.
# 해제를 건너뛰면 skip-worktree 가 변경을 가려서 `git diff` 가 비어 보이고, dry-run 이
# "버릴 것 없음" 이라고 **거짓 보고**한다 — 정확히 이 스크립트가 막아야 할 종류의 오판이다.
git update-index --no-skip-worktree -- "${SKIPPED[@]}"

# 이 지점부터 실패하면 skip-worktree 를 되돌려 놓는다.
trap 'restore_skip_worktree' ERR

# dirty 파일 분류
mapfile -t DIRTY < <(git diff --name-only)
OUTSIDE=()
INSIDE=()
for f in "${DIRTY[@]:-}"; do
  [[ -z "${f}" ]] && continue
  if [[ "${f}" == _state/* ]]; then
    INSIDE+=("${f}")
  else
    OUTSIDE+=("${f}")
  fi
done

if [[ ${#OUTSIDE[@]} -gt 0 ]]; then
  echo >&2
  echo "error: _state 밖에 변경이 있습니다. 이 스크립트는 그것을 건드리지 않습니다." >&2
  for f in "${OUTSIDE[@]}"; do echo "  - ${f}" >&2; done
  echo >&2
  echo "커밋하거나 stash 한 뒤 다시 실행하세요." >&2
  restore_skip_worktree
  exit 1
fi

if [[ ${#INSIDE[@]} -eq 0 ]]; then
  echo "  버릴 _state 변경 없음"
else
  echo
  echo "== 버릴 _state 변경 (${#INSIDE[@]}개) =="
  BIG=()
  for f in "${INSIDE[@]}"; do
    lines="$(git diff --numstat -- "${f}" | awk '{print $1 + $2}')"
    lines="${lines:-0}"
    printf '  %-52s %s줄\n' "${f}" "${lines}"
    if [[ "${lines}" -gt "${MAX_STATE_DIFF_LINES}" ]]; then
      BIG+=("${f} (${lines}줄)")
    fi
  done

  if [[ ${#BIG[@]} -gt 0 ]] && ! ${FORCE}; then
    echo >&2
    echo "error: ${MAX_STATE_DIFF_LINES}줄을 넘게 바뀐 _state 파일이 있습니다:" >&2
    for f in "${BIG[@]}"; do echo "  - ${f}" >&2; done
    echo >&2
    echo "타임스탬프 bump 가 아니라 실제 내용일 수 있습니다. diff 를 확인한 뒤" >&2
    echo "정말 버려도 되면 --force 로 다시 실행하세요." >&2
    restore_skip_worktree
    exit 1
  fi

  if ! ${DRY_RUN}; then
    git checkout -- "${INSIDE[@]}"
    echo "  → 되돌림 완료"
  fi
fi

echo
if ${DRY_RUN}; then
  echo "→ (dry-run) git pull --ff-only 생략"
  echo "→ (dry-run) scripts/dev_ignore_state.sh 재적용 생략"
  restore_skip_worktree
  echo
  echo "dry-run 종료 — 트리는 변경되지 않았습니다."
  exit 0
fi

echo "→ git pull --ff-only"
git pull --ff-only

echo
echo "→ skip-worktree 재적용"
bash scripts/dev_ignore_state.sh >/dev/null
trap - ERR

echo
echo "== 완료 =="
git status --short --branch | head -1
echo "  skip-worktree 파일: $(git ls-files -v | grep -c '^S' || true)개"
