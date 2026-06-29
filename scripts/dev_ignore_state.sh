#!/usr/bin/env bash
#
# dev_ignore_state.sh — _state 마찰 완화 (로컬 개발자용)
#
# 문제: 수집기를 로컬에서 실행하면 _state/*.json (dedup 상태)이 매번 변경되어
#       git status 를 더럽히고, 실수로 커밋되거나 pull 시 머지 충돌을 유발한다.
#
# 해결 (2단):
#   C) skip-worktree  : 추적 중인 _state 파일의 로컬 변경을 git 이 무시하도록 표시
#                       → git status 깨끗 유지, 실수 커밋 차단
#   B) merge=ours 드라이버 : .gitattributes 의 `_state/*.json merge=ours` 가 실제로
#                       동작하도록 로컬 git config 에 드라이버를 등록
#                       (git 에는 'ours' 라는 이름의 내장 드라이버가 없어,
#                        등록 전에는 해당 attribute 가 무동작/no-op 이다)
#
# 사용법:
#   bash scripts/dev_ignore_state.sh            # 적용 (기본)
#   bash scripts/dev_ignore_state.sh --status   # 현재 상태 확인
#   bash scripts/dev_ignore_state.sh --undo     # 원복 (skip-worktree 해제 + 드라이버 제거)
#
# 주의:
#   - skip-worktree 는 .git/index 의 로컬 플래그이므로 다른 개발자/CI 에 전파되지 않는다.
#     각 개발자가 클론 후 한 번 실행하면 된다.
#   - 자동화(CI/cron)는 이 스크립트를 실행하지 않으므로 _state 커밋은 정상 동작한다.
#   - skip-worktree 적용 후에는 `git pull` 이 _state 변경을 덮어쓰지 못해 막힐 수 있다.
#     그럴 땐 --undo 로 잠시 해제하거나, 이미 등록된 merge=ours 드라이버가 충돌을 흡수한다.

set -euo pipefail

# 레포 루트로 이동 (어디서 실행해도 동작)
REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || true)"
if [[ -z "${REPO_ROOT}" ]]; then
  echo "error: git 레포 내부에서 실행하세요." >&2
  exit 1
fi
cd "${REPO_ROOT}"

MODE="apply"
case "${1:-}" in
  --undo)   MODE="undo" ;;
  --status) MODE="status" ;;
  ""|--apply) MODE="apply" ;;
  *)
    echo "error: 알 수 없는 인자 '${1}'. 사용법: --status | --undo | (없음=apply)" >&2
    exit 1
    ;;
esac

# 추적 중인 _state 파일 목록 (널 구분으로 안전 처리)
mapfile -d '' -t STATE_FILES < <(git ls-files -z -- '_state/*.json' '_state/*.lock')

if [[ ${#STATE_FILES[@]} -eq 0 ]]; then
  echo "info: 추적 중인 _state 파일이 없습니다. 할 일 없음."
  exit 0
fi

driver_registered() {
  [[ "$(git config --local --get merge.ours.driver || true)" == "true" ]]
}

print_status() {
  echo "== merge=ours 드라이버 =="
  if driver_registered; then
    echo "  [O] 등록됨 (merge.ours.driver=true) → .gitattributes 의 merge=ours 동작함"
  else
    echo "  [X] 미등록 → .gitattributes 의 _state/*.json merge=ours 가 무동작(no-op) 상태"
  fi
  echo "== skip-worktree (_state, ${#STATE_FILES[@]}개 추적) =="
  # git ls-files -v: skip-worktree 는 대문자 'S' 태그로 표시된다
  local flagged
  flagged="$(git ls-files -v -- '_state/' | grep -c '^S' || true)"
  if [[ "${flagged}" -gt 0 ]]; then
    echo "  [O] ${flagged}개 파일에 skip-worktree 적용됨"
  else
    echo "  [X] skip-worktree 미적용"
  fi
}

case "${MODE}" in
  status)
    print_status
    ;;

  apply)
    echo "→ merge=ours 드라이버 등록 중..."
    git config --local merge.ours.driver true

    echo "→ _state 파일 ${#STATE_FILES[@]}개에 skip-worktree 적용 중..."
    git update-index --skip-worktree -- "${STATE_FILES[@]}"

    echo
    echo "완료. 이제 로컬 _state 변경이 git status 를 더럽히지 않습니다."
    echo
    print_status
    ;;

  undo)
    echo "→ _state 파일 skip-worktree 해제 중..."
    git update-index --no-skip-worktree -- "${STATE_FILES[@]}"

    echo "→ merge=ours 드라이버 제거 중..."
    if driver_registered; then
      git config --local --unset merge.ours.driver
    fi

    echo
    echo "원복 완료. _state 변경이 다시 git 에 노출됩니다."
    echo
    print_status
    ;;
esac
