# 장애 대응 SOP — Investing Dragon 수집기 파이프라인

- **버전**: 1.0
- **최초 작성**: 2026-04-24
- **참조 사례**: [Postmortem 2026-04 수집기 파이프라인 2단 장애](postmortem-2026-04-collector-outages.md)

---

## 1. 목적 / 스코프

이 SOP는 Investing Dragon 저장소의 **CI 및 수집기 파이프라인 장애**에 대한 탐지·대응·복구·사후 처리 절차를 정의한다.

적용 범위:
- `.github/workflows/collect-*.yml` 13개 수집기 워크플로우
- `scripts/collect_*.py` 및 `scripts/common/*.py` 공통 모듈
- `alert-consecutive-failures.yml` 알림 인프라
- Jekyll 빌드·배포 파이프라인

적용 제외: 기능 개발 PR 리뷰, 콘텐츠 품질 개선, 인프라 비용 최적화.

---

## 2. Severity 분류

| 등급 | 이름 | 임계값 | 예시 |
|------|------|--------|------|
| SEV-1 | 전면 중단 | 10개 이상 수집기가 연속 2회 이상 실패, 또는 `startup_failure`로 워크플로우 자체가 시작 불가 | PR #777 이후 13/13 startup_failure |
| SEV-2 | 부분 장애 | 3–9개 수집기가 연속 2회 이상 실패, 또는 핵심 수집기(crypto-news, stock-news) 단독 연속 실패 | risk_classifier import 오류로 6일 무음 실패 |
| SEV-3 | 간헐 실패 | 1–2개 수집기 단발 실패, 또는 동일 수집기 7일 이내 3회 미만 실패 | API rate limit 1회 초과 |

SEV-1/2는 즉시 대응한다. SEV-3은 24시간 내 원인 확인 후 패턴 반복 시 SEV-2로 격상한다.

---

## 3. 감지 채널

### 3.1 자동 알림

**`alert-consecutive-failures` Slack 알림**
- 수집기 워크플로우의 `alert-consecutive-failures` job이 연속 실패 임계값 도달 시 Slack `investing` 채널 alias로 발송.
- 채널 실제 이름은 시크릿(`SLACK_CHANNEL_ID_INVESTING` 등)으로 관리되며 `.github/actions/resolve-slack-config/action.yml`에서 런타임에 결정된다. 코드에 직접 노출하지 않는다.
- 주의: `startup_failure` 상태에서는 이 알림이 작동하지 않는다. 아래 3.2의 수동 점검이 필수다.

**`watchdog-zero-job-runs` (계획됨)**
- 5분 주기 외부 크론에서 `gh run list --json conclusion,jobs`를 폴링해 `jobs=0`인 run을 감지하고 Slack 알림.
- 현재 미착수 상태(Action Item 참조).

**Description quality CI**
- `check_description_quality.py --days 7` 결과가 boilerplate > 50% 시 CI 실패.
- 수집기 무음 실패가 지속되면 "입력 포스트 수 = 0" 상태를 CI가 정상으로 오인할 수 있음 — 반드시 실제 run 결과와 교차 확인한다.

### 3.2 수동 점검 명령

```bash
# 최근 20개 run의 결론 확인
gh run list --limit 20 --json conclusion,name,createdAt,url

# 특정 수집기 워크플로우 상태 확인
gh run list --workflow collect-crypto-news.yml --limit 5 --json conclusion,databaseId

# startup_failure 징후: duration ~2초, jobs 배열 비어 있음
gh run view <run-id> --json jobs,conclusion,createdAt
```

---

## 4. 초동 대응 플레이북 (15분 내)

### 4.1 장애 확인 및 재현

```bash
# 1. 대상 워크플로우 수동 트리거
gh workflow run collect-crypto-news.yml

# 2. 실행 결과 실시간 대기
gh run list --workflow collect-crypto-news.yml --limit 1 --json databaseId \
  | jq -r '.[0].databaseId' \
  | xargs gh run watch

# 3. 실패 로그 수집
gh run view <run-id> --log-failed
```

### 4.2 최근 변경사항 확인

```bash
# 장애 발생 시점 전후 24시간 커밋 목록
git log --oneline --since="24 hours ago"

# 머지된 PR 목록 (GitHub CLI)
gh pr list --state merged --limit 10 --json number,title,mergedAt,url
```

### 4.3 공통 원인 패턴 체크리스트

장애 증상에 따라 해당 항목을 먼저 확인한다.

| 증상 | 확인 항목 | 명령 |
|------|-----------|------|
| `startup_failure`, duration ~2초, jobs=0 | Reusable workflow permission mismatch | `gh run view <id> --json jobs,conclusion` — jobs 비어 있으면 permission 확인 |
| `ModuleNotFoundError: No module named 'scripts'` | `scripts/common/*.py`의 절대 import (`from scripts.common.*`) | `python3 scripts/tools/check_relative_imports.py` |
| `ModuleNotFoundError` (lazy import) | 함수 내부 `from scripts.common.*` 형태 lazy import | `python3 -m pytest tests/test_import_compatibility.py` |
| 모든 수집기 동시 실패 | 최근 머지된 공통 모듈 변경 또는 workflow 변경 | `git log --oneline scripts/common/ .github/workflows/` |
| 일부 수집기만 실패 | API key rotation, rate limit, 외부 서비스 장애 | 해당 수집기 로그에서 HTTP 상태코드 확인 |
| 스케줄 실행 없음 | 워크플로우 disabled 상태 | `gh workflow list --all` |
| 시크릿 관련 오류 | Secret rotation 또는 만료 | GitHub repo Settings > Secrets 확인 |

### 4.4 빠른 검증

```bash
# Python import 호환성 전체 검사
python3 -m pytest tests/test_import_compatibility.py -v

# ruff 린팅
python3 -m ruff check scripts/

# Workflow permission lint (PR #788 머지 후 사용 가능)
python3 scripts/tools/check_workflow_permissions.py
```

---

## 5. 에스컬레이션 기준

15분 내 원인을 특정하지 못하면 다음 절차를 진행한다.

1. 장애 선언 메시지를 Slack `investing` 채널에 발송 (6절 템플릿 사용).
2. SEV-1이면 즉시 롤백 검토 (6절).
3. 30분 내 원인 미확정 시 Postmortem 발행 트리거 (8절).

---

## 6. 롤백 절차

### 6.1 PR 기반 롤백

```bash
# 원인 PR 번호를 확인한 후 revert
gh pr revert <pr-number>

# revert PR 생성 후 즉시 머지 (SEV-1은 빠른 머지 승인 필요)
gh pr merge <revert-pr-number> --squash
```

### 6.2 직접 revert commit

```bash
# 머지 커밋 해시 확인
git log --oneline -10

# 해당 커밋 revert
git revert <commit-hash> --no-edit
git push origin <current-branch>
```

### 6.3 긴급 워크플로우 비활성화

수집기 워크플로우가 반복 실패하며 부작용(중복 포스트, 잘못된 `_state/` 갱신)이 우려될 때만 사용한다.

```bash
# 특정 워크플로우 비활성화
gh workflow disable collect-crypto-news.yml

# 복구 후 재활성화
gh workflow enable collect-crypto-news.yml
```

### 6.4 롤백 완료 검증

```bash
# 롤백 후 수동 트리거로 정상 동작 확인
gh workflow run collect-crypto-news.yml
gh run list --workflow collect-crypto-news.yml --limit 1 --json conclusion,jobs
```

---

## 7. 통신

### 7.1 Slack 채널

알림은 `.github/actions/resolve-slack-config/action.yml`의 `investing` alias를 통해 라우팅된다. 채널 실제 이름은 시크릿으로 관리되므로 이 문서에 기재하지 않는다.

### 7.2 장애 선언 템플릿

```
[장애 선언] SEV-{1|2|3} — {워크플로우/수집기 이름}

- 발생 시각 (UTC): YYYY-MM-DD HH:MM
- 영향 범위: {영향받는 수집기 수 및 이름}
- 현재 증상: {startup_failure / ModuleNotFoundError / API 오류 등}
- 현재 상태: 조사 중 / 원인 확인 / 롤백 진행 중 / 복구됨
- 다음 체크포인트: HH:MM UTC (15분 후)
```

### 7.3 복구 완료 알림

```
[장애 해제] SEV-{1|2|3} — {워크플로우/수집기 이름}

- 해결 시각 (UTC): YYYY-MM-DD HH:MM
- 근본 원인: {1줄 요약}
- 적용 조치: {PR 번호 또는 커밋 해시}
- 검증: {수동 트리거 결과 또는 다음 스케줄 실행 성공 여부}
```

---

## 8. 사후 절차

### 8.1 Postmortem 발행 기준

| 조건 | 의무 여부 |
|------|-----------|
| SEV-1 장애 모두 | 필수 |
| SEV-2 장애 모두 | 필수 |
| SEV-3 동일 원인 3회 재발 | 필수 |
| SEV-3 단발 | 선택 (팀 판단) |

### 8.2 Postmortem 작성 가이드

`docs/postmortem-YYYY-MM-{제목}.md` 형식으로 작성. 포함 항목:

1. TL;DR (2–3줄)
2. Timeline (UTC 기준)
3. 근본 원인 분석
4. 왜 오래 걸렸는가 (탐지 지연 원인)
5. Action Items (담당자, 기한, 상태)
6. Learnings

### 8.3 Action Item 추적

Postmortem의 Action Items를 GitHub Issues로 등록하고 관련 PR에 연결한다.

### 8.4 본 SOP 갱신

- 새로운 장애 유형이 추가될 때마다 4.3 원인 패턴 표를 갱신한다.
- SEV 임계값 조정이 필요하면 2절을 수정하고 커밋 메시지에 근거를 기록한다.
- SOP 수정은 `docs/` 브랜치에서 PR로 반영하며 직접 `main` 푸시를 금지한다.

---

## 9. 운영자 체크리스트

장애 발생 시 아래를 순서대로 복사해 사용한다.

```
[ ] Slack에 장애 선언 메시지 발송 (7.2 템플릿)
[ ] gh run list --limit 20 --json conclusion,name,createdAt 로 전체 현황 파악
[ ] gh run view <id> --json jobs,conclusion — jobs 배열 비어 있으면 startup_failure
[ ] gh run view <id> --log-failed — 로그에서 오류 유형 식별
[ ] git log --oneline --since="24 hours ago" — 최근 변경사항 확인
[ ] 원인 패턴 표(4.3) 대조
[ ] 15분 내 원인 미확정 → 에스컬레이션 선언
[ ] 원인 확정 → 롤백 또는 핫픽스 적용 (6절)
[ ] gh workflow run <name> — 수동 트리거로 복구 검증
[ ] Slack에 장애 해제 메시지 발송 (7.3 템플릿)
[ ] SEV-1/2이면 Postmortem 발행 예약 (8절)
[ ] SOP 업데이트 필요 항목 확인
```

---

*이 문서는 실제 장애([postmortem-2026-04-collector-outages.md](postmortem-2026-04-collector-outages.md))를 기반으로 작성되었다. 새로운 장애 패턴 발견 시 즉시 갱신한다.*
