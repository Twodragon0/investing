#!/usr/bin/env bash
# scripts/requirements.lock 재생성 헬퍼 (공급망 변조 방어 해시 핀 락).
#
# scripts/requirements.txt 의 직접 의존성으로부터 pip-compile --generate-hashes 로
# 전이 의존성+휠 해시를 포함한 락을 격리 venv 에서 재생성한다. 의존성을 추가/제거/
# bump 한 뒤 실행할 것. 절차는 supply-chain-lock.yml 상단 주석과 동일하다.
#
# 사용법:
#   bash scripts/refresh_requirements_lock.sh            # 재생성 + 검증
#   PYTHON=python3.11 bash scripts/refresh_requirements_lock.sh
#   PIP_TOOLS_VERSION=7.5.3 bash scripts/refresh_requirements_lock.sh  # 다른 버전 핀
#   PIP_TOOLS_VERSION= bash scripts/refresh_requirements_lock.sh        # 핀 해제(최신)
#
# 환경변수:
#   PYTHON             락 생성 인터프리터(기본: python3.11 — 락은 3.11 에서 생성됨).
#   PIP_TOOLS_VERSION  pip-tools 버전 핀(기본: 7.5.3). 기본 핀은 현재 커밋된
#                      scripts/requirements.lock 을 in-place(앵커 존재, --upgrade 없음)
#                      재생성 시 비-주석 부분 byte-identical 로 재현됨이 실증되었다
#                      (2026-06-24). 빈 값으로 설정하면 최신 pip-tools 를 쓴다(출력
#                      포맷이 달라질 수 있음).
#
# 결정성 주의: pip-compile 은 기존 락이 있으면(앵커) 이미 핀된 패키지를 --upgrade
# 없이는 올리지 않는다. 이 헬퍼는 REQ_LOCK 을 in-place 로 덮어쓰므로 앵커가 유지돼,
# requirements.txt 에서 실제로 바뀐 의존성만 락에 반영된다(무관 패키지의 상류 drift
# 없음). 의도적으로 전 패키지를 최신으로 올리려면 락을 비우고 실행하거나 --upgrade 를
# 추가하라(이 헬퍼는 보수적 기본을 택한다).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REQ_TXT="scripts/requirements.txt"
REQ_LOCK="scripts/requirements.lock"
PYTHON="${PYTHON:-python3.11}"
PIP_TOOLS_VERSION="${PIP_TOOLS_VERSION-7.5.3}"
LOG="[refresh-lock]"

cd "$REPO_ROOT"

if [[ ! -f "$REQ_TXT" ]]; then
  echo "$LOG $REQ_TXT 없음 (repo 루트에서 실행하세요)" >&2
  exit 1
fi

# 락은 Python 3.11 에서 생성됨 — 동일 버전을 강제해 플랫폼/버전 churn 을 막는다.
if ! command -v "$PYTHON" >/dev/null 2>&1; then
  echo "$LOG '$PYTHON' 인터프리터를 찾지 못함." >&2
  echo "$LOG 락은 Python 3.11 에서 생성됩니다. python3.11 을 설치하거나" >&2
  echo "$LOG PYTHON=<3.11 경로> 로 지정하세요 (예: mise/pyenv 의 3.11)." >&2
  exit 1
fi

PYVER="$("$PYTHON" -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
if [[ "$PYVER" != "3.11" ]]; then
  echo "$LOG 경고: $PYTHON 은 Python $PYVER 입니다(권장: 3.11)." >&2
  echo "$LOG 다른 마이너 버전으로 생성하면 락 내용이 달라질 수 있습니다." >&2
fi

VENV="$(mktemp -d)/lockgen"
cleanup() { rm -rf "$(dirname "$VENV")" 2>/dev/null || true; }
trap cleanup EXIT

echo "$LOG 격리 venv 생성: $VENV ($PYTHON / $PYVER)"
"$PYTHON" -m venv "$VENV"
"$VENV/bin/python" -m pip install --quiet --upgrade pip

if [[ -n "$PIP_TOOLS_VERSION" ]]; then
  echo "$LOG pip-tools==$PIP_TOOLS_VERSION 설치"
  "$VENV/bin/pip" install --quiet "pip-tools==$PIP_TOOLS_VERSION"
else
  echo "$LOG pip-tools(최신) 설치 — 출력 안정화를 원하면 PIP_TOOLS_VERSION 핀 권장"
  "$VENV/bin/pip" install --quiet pip-tools
fi

# --no-strip-extras: pip-tools 8.0.0 부터 --strip-extras 가 기본이 된다(7.5.3 경고).
# 현 락은 extras 핀(lxml[html-clean]==)을 보유하므로, strip 되면 lxml + lxml-html-clean
# 으로 분해돼 락 내용·커버리지 가드 관점이 바뀐다. 현 동작을 고정하기 위해 명시한다.
echo "$LOG pip-compile --generate-hashes --no-strip-extras → $REQ_LOCK"
"$VENV/bin/pip-compile" --generate-hashes --no-strip-extras \
  --output-file "$REQ_LOCK" "$REQ_TXT"

echo "$LOG 커버리지/해시 가드 검증 (network 불필요)"
if python3 -m pytest tests/test_requirements_lock_coverage.py --no-cov -q >/dev/null 2>&1; then
  echo "$LOG  → 가드 통과"
else
  echo "$LOG  → 가드 실패 — tests/test_requirements_lock_coverage.py 출력 확인" >&2
  python3 -m pytest tests/test_requirements_lock_coverage.py --no-cov -q >&2 || true
  exit 1
fi

echo "$LOG require-hashes dry-run 무결성 검증 (network, best-effort)"
if "$VENV/bin/pip" install --require-hashes --dry-run -r "$REQ_LOCK" >/dev/null 2>&1; then
  echo "$LOG  → require-hashes 통과"
else
  echo "$LOG  → require-hashes dry-run 실패/스킵 (오프라인이면 무시 가능; CI 가 재검증)" >&2
fi

echo "$LOG 락 변경 요약:"
git diff --stat -- "$REQ_LOCK" || true
echo "$LOG 완료. 변경을 검토 후 커밋하세요: git add $REQ_LOCK && git commit"
