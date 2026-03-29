#!/usr/bin/env bash
# scripts/purgecss_build.sh
#
# Jekyll 빌드 후 PurgeCSS로 미사용 CSS 제거
# 사용법:
#   bash scripts/purgecss_build.sh          # 일반 실행
#   bash scripts/purgecss_build.sh --dry-run # 삭제 없이 분석 결과만 출력
#   bash scripts/purgecss_build.sh --stats   # 용량 비교 통계 출력
#
# 전제조건:
#   - Node.js + npx 설치됨
#   - Ruby + bundle + Jekyll 설치됨

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

DRY_RUN=false
SHOW_STATS=false

for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=true ;;
    --stats)   SHOW_STATS=true ;;
    --help|-h)
      echo "사용법: bash scripts/purgecss_build.sh [--dry-run] [--stats]"
      echo "  --dry-run  CSS를 실제로 변경하지 않고 분석만 수행"
      echo "  --stats    빌드 전후 CSS 용량 비교 출력"
      exit 0
      ;;
    *)
      echo "[경고] 알 수 없는 인수: $arg (무시됨)"
      ;;
  esac
done

cd "$PROJECT_ROOT"

echo "========================================"
echo " Jekyll + PurgeCSS 빌드 파이프라인"
echo "========================================"

# ── 1. Jekyll 빌드 ────────────────────────────────────────────
echo ""
echo "[1/3] Jekyll 빌드 시작..."
bundle exec jekyll build
echo "[1/3] Jekyll 빌드 완료 → _site/"

# ── 2. 사전 통계 수집 (--stats 옵션 시) ───────────────────────
if $SHOW_STATS; then
  echo ""
  echo "[통계] PurgeCSS 적용 전 CSS 크기:"
  find "$PROJECT_ROOT/_site" -name "*.css" | while read -r f; do
    size=$(wc -c < "$f")
    echo "  $(basename "$f"): ${size} bytes"
  done
  BEFORE_TOTAL=$(find "$PROJECT_ROOT/_site" -name "*.css" -exec wc -c {} \; | awk '{sum+=$1} END{print sum}')
  echo "  합계: ${BEFORE_TOTAL} bytes"
fi

# ── 3. PurgeCSS 실행 ──────────────────────────────────────────
echo ""

# purgecss CLI 존재 확인
if ! npx --yes purgecss --version > /dev/null 2>&1; then
  echo "[오류] purgecss를 실행할 수 없습니다. 'npm install -g purgecss' 또는 npx를 확인하세요."
  exit 1
fi

echo "[2/3] PurgeCSS 실행 중..."

if $DRY_RUN; then
  echo "[dry-run] 실제 파일 변경 없이 분석만 수행합니다."
  find "$PROJECT_ROOT/_site" -name "*.css" ! -name "*.map" | while read -r css_file; do
    rel_path="${css_file#$PROJECT_ROOT/}"
    size=$(wc -c < "$css_file")
    echo "  분석 대상: $rel_path (${size} bytes)"
  done
  echo "[dry-run] purgecss.config.js 설정으로 실행 시 위 파일들이 처리됩니다."
else
  # 실제 실행: 각 CSS 파일을 같은 경로에 덮어씀 (in-place)
  # purgecss --output은 디렉토리 단위로 동작하므로 파일별로 같은 디렉토리를 지정
  find "$PROJECT_ROOT/_site" -name "*.css" ! -name "*.map" | while read -r css_file; do
    css_dir="$(dirname "$css_file")"
    rel_path="${css_file#$PROJECT_ROOT/}"
    echo "  처리 중: $rel_path"
    npx purgecss \
      --config "$PROJECT_ROOT/purgecss.config.js" \
      --css "$css_file" \
      --output "$css_dir/"
  done
  echo "[2/3] PurgeCSS 완료"
fi

# ── 4. 사후 통계 및 요약 ──────────────────────────────────────
if $SHOW_STATS && ! $DRY_RUN; then
  echo ""
  echo "[통계] PurgeCSS 적용 후 CSS 크기:"
  find "$PROJECT_ROOT/_site" -name "*.css" | while read -r f; do
    size=$(wc -c < "$f")
    echo "  $(basename "$f"): ${size} bytes"
  done
  AFTER_TOTAL=$(find "$PROJECT_ROOT/_site" -name "*.css" -exec wc -c {} \; | awk '{sum+=$1} END{print sum}')
  echo "  합계: ${AFTER_TOTAL} bytes"

  if [ -n "${BEFORE_TOTAL:-}" ] && [ "${BEFORE_TOTAL}" -gt 0 ]; then
    SAVED=$((BEFORE_TOTAL - AFTER_TOTAL))
    PCT=$(awk "BEGIN{printf \"%.1f\", ($SAVED / $BEFORE_TOTAL) * 100}")
    echo ""
    echo "[결과] 절약: ${SAVED} bytes (${PCT}% 감소)"
  fi
fi

echo ""
echo "[3/3] 빌드 파이프라인 완료"
echo "  출력 디렉토리: $PROJECT_ROOT/_site/"
echo "========================================"
