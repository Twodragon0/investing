# `.claude/` — Claude Code 환경 구성

이 디렉토리는 **investing** 프로젝트에서 Claude Code(클로드 코드)와 oh-my-claudecode(OMC) 에이전트가 어떻게 협업할지 정의합니다.

## 디렉토리 구조

```
.claude/
├── CLAUDE.md              # OMC 통합 안내 (자동 관리됨, 직접 편집 금지)
├── README.md              # 이 파일
├── settings.json          # 팀 공유 설정 (커밋됨)
├── settings.local.json    # 개인 설정 (gitignored)
├── agents/                # 프로젝트 전용 서브에이전트 정의
├── hooks/                 # 도구 호출 전후 실행 스크립트
├── rules/                 # 코딩 규칙 / 워크플로우 가이드라인
└── skills/                # 프로젝트 전용 슬래시 커맨드 / 스킬
```

## 핵심 파일

### `settings.json` (팀 공유)
- 권한 베이스라인: 프로젝트 스크립트, ruff, jekyll, git read-only 명령 등
- 보호: `_state/`, `.env`, `_site/` 직접 편집 차단
- 훅 등록: `protect-files.sh`(편집 차단), `auto-lint-python.sh`(자동 ruff), `memory-guard.sh`(에이전트 동시 실행 시 메모리 경고)

### `settings.local.json` (개인, gitignored)
개인 권한 추가, 임시 환경변수 등. 팀과 공유할 필요 없는 설정.

### `CLAUDE.md` (OMC 자동 관리)
oh-my-claudecode 플러그인이 관리. `omc update` 시 덮어씌워지므로 직접 편집하지 말 것. 프로젝트별 가이드는 루트 `CLAUDE.md`에 작성.

## Agents (`agents/`)

프로젝트 전용 서브에이전트 9종. 작업에 맞춰 자동 라우팅됨:

| 에이전트 | 담당 영역 |
|---------|----------|
| `investing-lead` | 전체 코디네이션 |
| `architect` | 시스템 아키텍처 / 모듈 설계 |
| `data-pipeline-lead` | `scripts/collect_*.py` + `scripts/common/` |
| `collector-reviewer` | 수집기 코드 리뷰 + 중복 방지 검증 |
| `content-pipeline` | `scripts/generate_*.py` 요약/이미지 |
| `workflow-optimizer` | `.github/workflows/` 최적화 |
| `workflow-debugger` | CI/워크플로우 장애 분석 |
| `jekyll-checker` | `_layouts/`, `_includes/`, `_sass/` |
| `test-engineer` | 테스트 작성 + dedup 검증 |

호출: `/agents` 메뉴 또는 `Task(subagent_type="...")` 자동.

## Skills (`skills/`)

프로젝트 슬래시 커맨드 8종:

| 스킬 | 용도 |
|-----|------|
| `add-data-source` | 새 뉴스 소스 추가 가이드 |
| `new-collector` | 새 collector 스크립트 스캐폴드 |
| `debug-workflow` | GitHub Actions 디버깅 |
| `site-health-check` | Jekyll 사이트 헬스체크 |
| `lint-fix` | ruff 린트 자동 수정 |
| `fix-issue` | 이슈 기반 수정 워크플로우 |
| `deep-research` | 코드베이스 심층 분석 |
| `omc-reference` | OMC 에이전트/도구 카탈로그 |

호출: `/<스킬명>` 또는 키워드 자동 탐지.

## Rules (`rules/`)

코딩 가이드라인 7종. Claude가 작업 시 자동 참조:

- `coding-style.md` — 불변성, 파일 구조, 검증
- `git-workflow.md` — 커밋 메시지 형식, PR 워크플로우
- `karpathy-guidelines.md` — 단순함 우선, 외과적 변경
- `news-collector.md` — 수집기/스크립트 가드레일
- `performance.md` — 모델 라우팅, 알고리즘 효율성
- `security.md` — 시크릿 관리, OWASP 체크리스트
- `testing.md` — TDD, 80% 커버리지, 엣지 케이스

## Hooks (`hooks/`)

도구 호출 전후 자동 실행:

| 훅 | 시점 | 동작 |
|----|------|------|
| `protect-files.sh` | PreToolUse (Edit/Write) | `_state/`, `.env`, `*.key` 등 민감 파일 편집 차단 |
| `auto-lint-python.sh` | PostToolUse (Edit/Write) | `.py` 파일 편집 시 `ruff check --fix` 자동 실행 |
| `memory-guard.sh` | PreToolUse (Agent) | 시스템 메모리 10% 미만 시 경고 (M1/M2 16GB 보호) |

## 사용 패턴

### 빠른 작업
- 단일 파일 수정 → 직접 처리
- `/lint-fix` → ruff 일괄 수정
- `/site-health-check` → 사이트 상태 점검

### 중간 규모 (2-5 파일)
- `ulw "...작업 설명..."` → ultrawork 병렬 실행
- 자동 ruff + 보호 훅이 안전망

### 대규모 / 신규 기능
- `ralplan "..."` → 합의 기반 계획 수립
- `autopilot "..."` → 풀 사이클 자동 실행 (Phase 0-5)
- `/team` → 다중 에이전트 협업

### 디버깅
- `/debug-workflow` → CI 실패 분석
- `tracer` + `debugger` 에이전트 조합

## 자주 쓰이는 명령

```bash
# Python 린팅
python3 -m ruff check scripts/

# Jekyll 로컬 빌드
bundle exec jekyll build

# Jekyll 로컬 서버
bundle exec jekyll serve

# Description 품질 측정
python scripts/check_description_quality.py --days 7

# 포스트 이미지 검증
python scripts/check_post_images.py

# 사이트맵 로컬 검증
python scripts/tools/check_sitemap_local.py

# IndexNow 즉시 제출
python scripts/tools/indexnow_submit.py --from-recent-posts 30

# GSC sitemap 재제출 (서비스 계정 필요)
GOOGLE_APPLICATION_CREDENTIALS=/path/to/sa.json \
  python scripts/tools/gsc_api.py submit-sitemap \
  https://investing.2twodragon.com/sitemap-index.xml --confirm

# GSC 색인 감사
GOOGLE_APPLICATION_CREDENTIALS=/path/to/sa.json \
  python scripts/tools/gsc_index_audit.py --from-sitemap
```

## OMC 워크플로우 단축어

키워드만 입력해도 자동으로 해당 워크플로우 실행:

| 키워드 | 워크플로우 | 용도 |
|--------|-----------|------|
| `ulw` | ultrawork | 병렬 실행 |
| `autopilot` / `auto pilot` | autopilot | 풀 사이클 자동 |
| `ralph` | ralph | 영속 루프 |
| `ralplan` | ralplan | 합의 기반 계획 |
| `ccg` | ccg | Claude+Codex+Gemini 3-모델 |
| `deep interview` | deep-interview | Socratic 요구사항 명확화 |
| `tdd` | TDD 모드 | 테스트 주도 개발 |
| `cancelomc` / `stopomc` | cancel | 모드 종료 |

## 보호되는 파일 (자동 차단)

`hooks/protect-files.sh`가 다음 패턴 편집을 차단:

- `.env`, `secrets.*`, `credentials.*`
- `_state/*.json` (수집기 자동 관리, 수동 편집 시 dedup 깨짐)
- `package-lock.json`, `Gemfile.lock`
- `.git/`, `.ssh/`, `*.key`, `*.pem`

차단 우회가 정말 필요한 경우 사용자가 수동으로 편집하거나 `settings.local.json`에 일시 허용 추가.

## 추가 자료

- 프로젝트 가이드: 루트 `CLAUDE.md`
- 워크플로우: 루트 `AGENTS.md`
- OMC 공식 문서: `~/.claude/plugins/cache/omc/oh-my-claudecode/<버전>/skills/`
