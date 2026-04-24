# 장애 대응 최상위 네비게이션

## TL;DR

Investing Dragon 수집기 파이프라인은 4개 레이어 알림으로 감시된다. 장애 의심 시: (1) SOP §3 감지 채널로 알림 여부 확인 → (2) SOP §4 초동 대응으로 근본 원인 식별 → (3) SOP §5 에스컬레이션 판정 → (4) postmortem 작성 및 action item 추적.

---

## 어떤 상황에 어떤 문서를 읽을까

| 상황 | 먼저 볼 문서 | 섹션 |
|---|---|---|
| Slack 알림을 못 받았는데 수집기가 장애라고 의심함 | `sop-incident-response.md` | §3 감지 채널 |
| 장애 원인을 모르거나 근본 원인 분석이 필요함 | `postmortem-2026-04-collector-outages.md` | Timeline + 근본 원인 #1/#2 |
| 13/13 수집기가 동시에 `startup_failure` 상태임 | `postmortem-2026-04-collector-outages.md` | 근본 원인 #2 (Reusable Workflow Permission) |
| `ModuleNotFoundError: No module named 'scripts'` 발생 | `postmortem-2026-04-collector-outages.md` | 근본 원인 #1 (절대 import) |
| 장애 초동 15분 내 무엇을 해야 할지 모름 | `sop-incident-response.md` | §4 초동 대응 플레이북 |
| 신규 수집기 또는 reusable workflow 추가 시 permission 검증 | `scripts/tools/check_workflow_permissions.py` | — |
| 매주/매월 알림 품질 리뷰 필요 | `scripts/tools/review_alerting_quality.py` | — |
| 롤백이 필요한지 판단할 수 없음 | `sop-incident-response.md` | §5 에스컬레이션 기준 + §6 롤백 절차 |
| 장애 선언/해제 메시지를 Slack에 보낼 형식이 필요함 | `sop-incident-response.md` | §7.2 장애 선언 템플릿 + §7.3 복구 완료 알림 |

---

## 4-레이어 알림 인프라

| 레이어 | 목적 | 파일 | 감지 대상 | 한계 |
|------|------|------|-----------|------|
| **1. alert-consecutive-failures** | 수집기 연속 실패 추적 | `.github/workflows/alert-consecutive-failures.yml` | 3회+ 연속 실패 | startup_failure는 job 시작 안 되어 알림 불발 |
| **2. watchdog-zero-job-runs** | startup_failure 및 0-job run 감지 | `.github/workflows/watchdog-zero-job-runs.yml` | `conclusion == "startup_failure"` | 매 5분 폴링, 7일 이상 된 이벤트는 추적 안 함 |
| **3. collector-heartbeat** | 일일 건강 리포트 | `.github/workflows/collector-heartbeat.yml` | 24시간 내 성공/실패 통계 | 비정기 장애는 다음날 리포트까지 미지각 가능 |
| **4. description-quality CI** | 포스트 품질 저하 (수집기 무음 실패 간접 지표) | `scripts/check_description_quality.py` | boilerplate > 50% | 입력 포스트 수 = 0일 때 엣지케이스 있음 (§4.3 참조) |

---

## 운영 일과

### 매일
- Slack `investing` 채널에 heartbeat 메시지 확인 (09:10 KST 자동 발송)
  - 녹색: 모든 수집기 정상
  - 주황색/빨강: N개 수집기 24시간 내 0 success → §4 초동 대응 진입

### 매주 (목요일 권장)
```bash
# 지난 1주일 알림 품질 리뷰
python scripts/tools/review_alerting_quality.py --window-hours 168
```
결과 해석: false positive (불필요한 알림) 및 false negative (놓친 장애) 비율 확인.

### 매월
- postmortem action items 진행률 리뷰
  - 완료된 항목: GitHub Issues 닫기
  - 기한 초과 항목: 담당자에게 escalation

### 신규 워크플로우/수집기 추가 시
```bash
# permission lint 실행 (PR #788 머지 후)
python scripts/tools/check_workflow_permissions.py
```
caller workflow가 reusable callee의 모든 permission scope을 선언했는지 확인.

---

## 에스컬레이션 경로

| 시간 | 액션 |
|------|------|
| **0–15분** | SOP §4 초동 대응 플레이북 따라 근본 원인 식별 |
| **15–30분** | 원인 미확정 → Slack에 장애 선언 (§7.2 템플릿) + rollback 검토 (§6) 또는 핫픽스 적용 |
| **30분–4시간** | 복구 완료 후 Slack 해제 메시지 (§7.3) + SEV-1/2는 postmortem 발행 (§8) |

---

## 관련 파일 전체 목록

### 문서
- `docs/incident-recovery-readme.md` — 이 파일 (최상위 네비게이션)
- `docs/sop-incident-response.md` — 264줄 SOP, 초동 대응 상세 절차
- `docs/postmortem-2026-04-collector-outages.md` — 160줄 사례 연구, 실제 장애 분석

### GitHub Actions 워크플로우
- `.github/workflows/alert-consecutive-failures.yml` — 수집기 연속 실패 알림 (reusable)
- `.github/workflows/watchdog-zero-job-runs.yml` — startup_failure 감지 (매 5분)
- `.github/workflows/collector-heartbeat.yml` — 일일 건강 리포트 (매일 09:10 KST)

### Python 도구
- `scripts/tools/check_workflow_permissions.py` — Reusable workflow permission lint
- `scripts/tools/review_alerting_quality.py` — 알림 품질 감사 (false positive/negative 측정)

### CI 통합
- `.github/workflows/code-quality.yml` — permission lint 및 상대 import 검사 포함 (PR #788)

---

## 온보딩 순서 (신입 팀원)

1. **이 문서 (incident-recovery-readme.md) 읽기** — 5분
   - 상황별 문서 네비게이션 이해

2. **SOP (sop-incident-response.md) 읽기** — 20분
   - Severity 분류 (§2)
   - 감지 채널 및 수동 점검 명령 (§3)
   - 초동 대응 플레이북 (§4) — 가장 중요

3. **최근 postmortem 1개 읽기** — 15분
   - 실제 장애 케이스 이해 (2026-04 사례)
   - 놓친 관측 공백 패턴 학습

4. **Slack investing 채널 구독**
   - 4개 자동 알림 실시간 수신
   - heartbeat 메시지로 일일 상태 확인

5. **4개 워크플로우 구조 파악** — 선택 (심화)
   - `alert-consecutive-failures.yml` — `needs: collect`, `if: failure()` 패턴
   - `watchdog-zero-job-runs.yml` — `gh api` 폴링 + state file 추적
   - `collector-heartbeat.yml` — Python 일괄 처리 + jq 파싱
   - 각 워크플로우의 permission scope과 Slack 시크릿 해석

---

## 주의사항

- **alert-consecutive-failures 자체 장애**: startup_failure 상태에서는 이 알림이 작동하지 않음. watchdog-zero-job-runs이 대신 감지.
- **description_quality 엣지케이스**: 수집기 무음 실패가 지속되면 "입력 포스트 수 = 0"을 "정상"으로 오인할 수 있음 → 반드시 `gh run view`로 교차 검증.
- **Slack 채널 시크릿**: 채널 ID는 `.github/actions/resolve-slack-config/action.yml`에 의해 런타임에 결정되며 이 문서에 기재하지 않음.
- **_state/ 파일**: 장애 조사 중 `_state/*.json` 파일을 수정하면 안 됨 (중복 방지 상태 손상).

---

*최종 갱신: 2026-04-24 | 근거: 2026-04 수집기 파이프라인 2단 장애 (PR #773, #777, #786, #788)*
