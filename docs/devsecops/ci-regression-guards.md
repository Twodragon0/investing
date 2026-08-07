# CI 회귀 가드 카탈로그

이 저장소의 **CI 인바리언트 가드** 인벤토리. 각 가드는 "조용히 약화되면
보호가 사라지는" 특정 불변식을, 일반 단위 테스트 스위트(`tests/`, Code
Quality 워크플로우의 pytest 잡) 안에서 강제한다. 로컬에서도 CI보다 먼저
실패하므로 회귀가 PR 단계에서 잡힌다.

매핑: OWASP **CICD-SEC-1**(Insufficient Flow Control) / **CICD-SEC-7**(Insecure
System Configuration), NIST SSDF(SP 800-218) **PO.3 / PW.4**.

> 작성 2026-06-22. 새 가드 추가/제거 시 이 표를 갱신할 것.

## 가드 일람

| 가드 테스트 | 케이스 | 불변식 (방향) | 막는 사고 |
|---|---|---|---|
| `tests/test_state_path_anchoring.py` | 18 | 모든 `_state` 작성자가 `__file__` 앵커(절대·repo-root 하위)를 쓴다 — bare-relative 금지 | 잘못된 cwd 에서 스크립트 실행 시 stray `scripts/_state/` 생성, dedup 상태 분기 |
| `tests/test_pip_audit_ignore_sync.py` | 4 | `code-quality.yml` ↔ `dependency-check.yml` 의 pip-audit `--ignore-vuln` ID 집합 동일(equality), 파일 내 모든 호출이 동일 집합 보유 | 한쪽만 ignore 갱신 → 다른 쪽 보안 게이트 매주 silent red (2026-06 사고) |
| `tests/test_ruff_version_pin_sync.py` | 3 | ruff 버전 핀 3곳(`.pre-commit-config.yaml` rev, `requirements-dev.txt`, `code-quality.yml`) 동기화(equality) | 핀 불일치 → format 규칙 차이로 코드 변경 없이 main 이 red |
| `tests/test_workflow_step_if_safety.py` | 53 | step-level `if:` 가 `secrets.*` 컨텍스트를 직접 참조하지 않음(presence) — 전 워크플로우 파라미터화 | actionlint 가 거부하는 expression → 워크플로우 startup_failure |
| `tests/test_workflow_permission_lint.py` | 8 | `check_workflow_permissions.py` 도구가 워크플로우 `permissions:` 최소권한 규칙을 검사 | 과대 권한(`contents: write` 남발) GITHUB_TOKEN 노출면 확대 |
| `tests/test_generated_image_guard.py` | 2 | 레이아웃이 렌더하는 생성 이미지가 404 나지 않음(존재 보장) | 30일 이미지 정리가 참조 살아있는 og/hero 이미지를 삭제 → 깨진 이미지 |
| `tests/test_encoding_guard.py` | 16 | `encoding_guard` 모듈의 UTF-8/CP949 라벨 교정 동작 불변 | 한국어 텍스트 인코딩 깨짐(mojibake) |
| `tests/test_requirements_lock_coverage.py` | 6 | `requirements.txt` 직접 의존성 전부가 `requirements.lock` 에 ==핀(부분집합) + 락의 모든 핀이 최소 1개 `--hash` 보유(presence) | 락 staleness(검증 안 되는 새 의존성) / hashless 핀이 `--require-hashes` 무결성 검증을 무력화하는 공급망 변조 창 |
| `tests/test_workflow_action_pinning_guard.py` | 4 | `.github/workflows/**` · `.github/actions/**` 의 모든 외부 `uses:` 가 40-hex SHA 핀(presence) + 탐지기 양방향 | 가변 태그(`@v4`)/브랜치 참조 → 업스트림 변조가 diff 없이 CI 에서 실행 |
| `tests/test_required_check_aggregator_guard.py` | 5 | 집계 잡의 `needs:` 가 나머지 전 잡을 덮음(집합 동일) + `if: always()` 보유 + 대상 워크플로우의 PR 트리거에 `paths:` 없음(presence) + 잡 id 스캐너 양방향 | ①`needs:` 밖의 잡이 실패해도 required 체크는 green ②`always()` 없으면 upstream skip 시 체크 미생성 → PR 영구 대기 ③`paths:` 재도입도 같은 영구 대기 |
| `tests/test_workflow_action_version_label_guard.py` | 7 | 모든 핀이 `# vX.Y` 라벨 보유 + 라벨이 버전 형태(presence), 한 SHA 에 모순 라벨 금지 · 한 버전이 두 SHA 로 분기 금지(내부 정합성), 비교기 양방향 | SHA 는 핀됐지만 라벨이 거짓 → 리뷰어·Dependabot 이 잘못된 changelog·CVE 목록을 근거로 판단 (2026-08-07 감사에서 3건: checkout `# v4`→실제 v6.0.2, github-script `# v7`→v9.0.0, git-auto-commit `# v5`→v7.1.0) |
| `tests/test_secret_scan_gate_guard.py` | 7 | Gitleaks 게이트 무결성: `useDefault=true`(presence), allowlist `targetRules`/`paths` 집합 동일(==), 게이트 차단성(no `continue-on-error`/`\|\| true`), `fetch-depth: 0`(presence) | 잡은 남아있는데 룰셋 해제·allowlist 확대·exit 흡수·히스토리 절단으로 시크릿 스캔이 조용히 무력화 |
| `tests/test_delimiter_regex_guard.py` | 13 | 출처 구분자 정규식이 구분자 앞 공백을 **요구**한다(`\s+`, presence) — 열린 꼬리 형태만 대상, 고정 alternation·마크다운 불릿·고정 숫자 리터럴은 면제 | `\s*` 는 복합어 내부 하이픈을 구분자로 오인해 뒤를 전부 삭제 (2026-08-06 4회 반복, main 에 13건 피해) |
| `tests/test_workflow_permission_gate_guard.py` | 4 | `code-quality.yml` 이 `check_workflow_permissions.py` 를 `--workflows-dir .github/workflows` 로 차단 실행(presence) | 도구 단위 테스트는 green 인데 CI 배선만 끊겨 2026-04-23 수집기 장애 클래스가 재무방비 |

총 **150 케이스**.

> 2026-08-07 실측 재집계. 이전 표기(131)는 `test_state_path_anchoring`(16→18)과
> `test_workflow_step_if_safety`(48→53, 워크플로우 수에 파라미터라이즈됨)가
> 자라는 동안 갱신되지 않아 stale 했다.

### 오프라인 가드로 끝나지 않는 축: 액션 핀 라벨

`test_workflow_action_version_label_guard.py` 는 네트워크 없이 판정 가능한
층까지만 강제한다 — 라벨의 존재·형태, 그리고 라벨들 사이의 모순. "이 SHA 가
정말 `# v6.0.2` 인가"는 업스트림만 답할 수 있고, 스위트는
`tests/conftest.py` 가 HTTP 를 차단하므로(의도된 설계) 여기서 물을 수 없다.

그 마지막 구간은 `.github/workflows/action-pin-verify.yml` 이 담당한다:
`scripts/tools/verify_action_pins.py` 가 각 핀을 GitHub API 로 대조하고,
MISMATCH 면 실패한다. 워크플로우/액션 변경 PR + 주간 스케줄로 돈다(주간이 필요한
이유는 업스트림 태그 삭제·재지정이 우리 diff 없이 일어나기 때문).

역할 분담이 이렇게 갈린 결과, 2026-08-07 감사에서 나온 3건 중 2건(같은 SHA 에
`# v4`/`# v6`, `# v7`/`# v9.0.0`)은 오프라인 가드가 잡고, 1건(`# v5` 가 단 한 곳에만
있어 비교 대상이 없던 v7.1.0 핀)은 온라인 잡만 잡는다.

> 공급망/시크릿 3종(2026-08-06 추가)의 배경: `security-scan.yml` 의
> `actions-permissions` 잡은 이름과 달리 **build 를 실패시킬 수 없다** — 모든 발견이
> `::warning::` 이고 exit 하지 않으며, 핀닝 체크의 `has_issues=true` 는
> `grep ... | while` 파이프라인 서브셸에 갇혀 전파조차 안 된다. 게다가
> `grep -v '@v'` 는 문제의 대상인 가변 태그를 "핀됨"으로 분류한다. 위 3개 가드는
> 그 잡을 대체하는 게 아니라, 차단 가능한 pytest 잡에 실제 강제를 처음으로 만든다.

## 설계 규약 (신규 가드 작성 시)

`.claude/skills/ci-config-guard` 플레이북을 따른다:

1. **위치**: `tests/` — 기존 pytest 잡이 CI 에서 실행하므로 그대로 실행됨.
2. **최소 의존**: stdlib + 텍스트/regex 스캔 우선. 워크플로우 YAML 검사용으로
   PyYAML 같은 파서를 새로 들이지 말 것. 측정 대상 소스를 import 하지 말 것
   (coverage 게이트를 움직이지 않도록).
3. **방향 명시**: 하한선은 `>=`(상향은 green), 핀은 `==`/집합 동일(어떤 변경도
   trip), 트리거/플래그는 presence. docstring 에 방향을 적는다.
4. **non-vacuous 필수**: 실제 파일에서 통과(positive) + 임시 사본을 변형하면
   assertion 이 FAIL(negative) 둘 다 증명한 뒤 머지. 실제 워크플로우 파일은
   변형하지 말고 모듈의 경로 상수를 임시 파일로 monkeypatch.
5. **카나리**: 대상 파일 존재 + 비어있지 않음을 확인하는 테스트를 둬서, 파일
   이동/리네임 시 vacuous 통과 대신 명확히 실패하게 한다.
6. **메시지**: 다음 엔지니어에게 고치는 법(또는 의도적 변경이면 가드 갱신법)을
   알려주는 assertion 메시지를 쓴다.

## 가드를 "추가하지 않는" 기준

가드 난립(sprawl) 방지: **특정 불변식의 조용한 약화가 실제로 강제를 무력화**
하고, 구체적 과거/유력 사고를 댈 수 있을 때만 추가한다. 사고가 없으면 보통
추가하지 않는다.

## 관련 운영 사실

- **dev-tool install 갭** (ruff/yamllint/basedpyright/pytest/pre-commit/actionlint/
  bandit/gitleaks 등 `scripts/requirements.txt` 에 없는 도구를 install 없이 호출)
  은 2026-06-22 전수 재감사에서 **잔여 0건** 확인. 신규 워크플로우에서 이들 도구
  호출 시 동일 잡 내 install 선행을 확인할 것. (사고 이력: `generate-weekly-report.yml`
  이 ruff 미설치로 매주 red → 중복 lint 스텝 제거로 해소.)
- CI red 진단은 `gh run list --limit 60` 으로 워크플로우별 실패 tally 를 먼저 떠서
  만성/일회성을 구분하고, 만성 의심 시 `gh workflow run "<name>"` 로 수동 트리거해
  스케줄 대기 없이 즉시 검증한다.
- **공급망 락 차단 승격 예약**: `.github/workflows/supply-chain-lock.yml` 의
  `--require-hashes` 무결성 스텝은 현재 non-blocking(경고). 도입 2026-06-22, 안정화
  2주 → **승격 예정일 2026-07-06(이후)**. 게이트: 예정일 경과 + 무결성 스텝 연속 green
  + `::warning title=lock integrity::` 0건. 승격은 그 스텝의 `|| echo ...` fallback
  제거로 수행. staleness/hashless 회귀는 위 `test_requirements_lock_coverage.py` 가
  워크플로우 트리거와 무관하게 매 PR 차단하므로, 승격은 무결성(다운로드 검증) 차단만
  추가하는 것이다.

## 구분자 오절단 감사 기록 (2026-08-06)

`\s*[-–—|]\s*<열린 꼬리>` 결함이 네 곳에서 발견됐다. 같은 조사를 반복하지
않도록 결론을 남긴다.

| 위치 | 표면 | 코퍼스 피해 |
|---|---|---|
| `enrichment_synthetic._strip_source_suffix` | 백필 일괄 편집(#1084) | **13건** — #1087 에서 원문 복구 |
| `enrichment_synthetic.clean_title` | 수집 시점 합성 설명문 | 0건 |
| `summarizer.clean` | 수집 시점 테마 설명문 | 0건 |
| `collect_crypto_news._extract_security_summary_from_title` | 보안 리포트 인용문 | 0건 |

**생성 시점 3건이 피해 0인 이유**: 결함이 발현하려면 하이픈 복합어가 있는
제목이 *합성 폴백 경로*를 타야 한다. 실제로 갈리는 제목(카드 4518건 중 35건,
p0 712건 중 4건, 보안 인용문 315건 중 1건)은 전부 실제 기사 설명문을 갖고 있어
폴백이 돌지 않았다. 즉 능력은 있었으나 발현하지 않았다.

검증 방법: 저장된 텍스트를 구/신 로직으로 각각 재생성해 비교했다. 단순
`startswith` 비교는 `제목 + " Seeking Alpha"` 같은 정상 텍스트를 오탐하므로
(구 로직 출력이 제목의 접두사이기 때문) 절단 여부를 별도로 확인해야 한다.

미해결로 남긴 인접 클래스: 구분자 없이 공백만으로 붙은 출처명
(`"…(BTC-USD:Cryptocurrency) Seeking Alpha"`). `normalize_blurb` 는 구분자를
요구하므로 잡지 않는다.

## 사이트 크롬 필터 재평가 (2026-08-07, 미결)

`summary_quality` 의 매체 자기소개 패턴들은 **증상 필터**다. 원인은 RSS
`<source url>` 을 기사 URL 로 오인해 퍼블리셔 홈페이지를 fetch 한 것이었고,
그 결과 홈페이지의 `og:description`(매체 태그라인)이 기사 요약이 됐다.
원인은 2026-08-07 에 막혔다(`rss_fetcher._is_article_url`).

필터를 걷어낼 수 있는지 판단하려면 **수정 이후 수집분**이 필요하다. 현재
코퍼스는 전부 수정 이전이므로 아직 판단할 수 없다. 재측정용 베이스라인:

| 링크 유형 | 블러브 | 크롬 |
|---|---|---|
| Google News 경유 | 3731 | 627 (**16.8%**) |
| 직접 퍼블리셔 경로 | 1286 | 55 (4.3%) |
| 도메인 루트 | 231 | 19 (8.2%) |

Google News 항목이 직접 피드 항목의 **약 4배**다. 홈페이지 fetch 는 Google
News 항목에서만 일어났으므로 이 격차가 인과의 간접 증거다.

월별 크롬 비율(전부 수정 이전): 2026-03 12.0% / 04 13.4% / 05 13.9% /
06 13.0% / 07 14.9% / 08 10.3%.

**재측정 시점**: 수정 이후 1주 이상 수집된 뒤. Google News 버킷이 직접 피드
버킷(4.3%)에 수렴하면 패턴 축소를 검토한다. 그전까지는 필터를 유지한다 —
근거 없이 걷어내면 보호만 사라진다.
