# Contributing

이 저장소는 뉴스 수집 자동화 + Jekyll 정적 사이트입니다. 대부분의 콘텐츠는
`scripts/collect_*.py` 가 자동 생성하므로, **생성물(`_posts/`, `_state/`,
`assets/images/generated/`)을 손으로 고치는 변경은 받지 않습니다** — 생성하는
쪽을 고쳐 주세요.

## 시작하기

```bash
pip install -r scripts/requirements.txt -r requirements-dev.txt
bundle install

# 로컬 상태 파일 노이즈 억제 (권장, 1회)
bash scripts/dev_ignore_state.sh
```

`_state/*.json` 은 중복 방지 상태입니다. 직접 수정하지 마세요 — pre-commit 훅이
커밋을 차단합니다.

## 변경 전 확인

| 상황 | 문서 |
| --- | --- |
| 수집기·공통 모듈 규약 | `.claude/rules/news-collector.md` |
| CI 가드를 추가/수정 | `docs/devsecops/ci-regression-guards.md` |
| 프로젝트 구조·명령 | `CLAUDE.md` |

## 검증 (PR 전 필수)

CI 와 동일한 순서입니다. `format --check` 누락이 가장 흔한 CI red 원인입니다.

```bash
python3 -m ruff check scripts/ tests/
python3 -m ruff format --check scripts/ tests/
python3 -m basedpyright                      # 옵셔널 import 폴백에서 자주 걸립니다
python3 -m pytest tests/ -q                  # 커버리지 하한 70% 포함
```

Jekyll 레이아웃/템플릿을 건드렸다면:

```bash
bundle exec jekyll build
```

워크플로우를 건드렸다면:

```bash
actionlint .github/workflows/<파일>.yml
```

로컬 도구가 CI 와 다를 수 있습니다. 과거에 `grep -P` 미지원(BSD grep), `pipefail`
부재, `mise` 파이썬 버전 차이가 로컬 green / CI red 를 만든 적이 있습니다.
셸 로직을 검증할 때는 CI 와 같은 조건인지 확인하세요.

## CI 가드를 추가한다면

이 저장소는 "조용히 약해지는" 게이트를 막는 회귀 가드를 씁니다. 새 가드는
`docs/devsecops/ci-regression-guards.md` 의 설계 규약을 따르고, 다음을 지켜야
합니다:

- **양방향 증명** — 실제 파일에서 통과(positive)하고, 위반을 주입하면 실패
  (negative)하는 것을 둘 다 확인한 뒤 머지
- **카나리** — 대상 파일이 사라지거나 스캐너가 깨지면 조용히 통과하는 대신
  명확히 실패할 것
- **falsifiability 하네스 편입** — `scripts/tools/guard_falsifiability.py` 에
  변형 케이스를 등록. 등록하지 않은 가드는 vacuous 여부가 검증되지 않습니다

```bash
python3 scripts/tools/guard_falsifiability.py          # 전체
python3 scripts/tools/guard_falsifiability.py --shard 1/8   # CI 와 동일한 샤드
```

`FALSIFIABLE` 이 아닌 결과(`VACUOUS`, `CONTROL-FAIL`, `AMBIGUOUS-ANCHOR`)는
전부 실패로 취급합니다.

## 골든 스냅샷

렌더링 출력은 골든 스냅샷으로 고정돼 있습니다. 의도한 변경이면 재생성하되
**diff 를 읽고** 커밋하세요.

```bash
UPDATE_GOLDEN=1 python3 -m pytest tests/test_summarizer_themed_news_golden.py -q
```

CI 에서는 재생성이 거부됩니다 — 그러면 모든 스냅샷이 자기 자신을 다시 써서
통과하고, 골든이 아무것도 증명하지 못하기 때문입니다.

## 커밋과 PR

- 커밋 메시지: `<type>: <설명>` (`feat`, `fix`, `refactor`, `docs`, `test`,
  `chore`, `perf`, `ci`). 본문은 한국어로 **왜** 를 적어 주세요
- 브랜치: `feat/`, `fix/`, `refactor/`, `docs/`
- 시크릿은 절대 커밋하지 마세요. 예시에는 `your-api-key-here` 같은 더미값을 쓰고,
  실제 값은 GitHub Secrets 로 관리합니다

PR 본문에는 **무엇을 측정했는지** 적어 주세요. 이 저장소는 "고쳤다" 보다
"코퍼스 N건 중 M건이 이러이러했고 수정 후 K건" 쪽을 훨씬 신뢰합니다.

## 자동화 워크플로우를 건드릴 때

`main` 에 자동 커밋하는 워크플로우(수집기, 이미지 auto-heal, URL 요약 백필)를
추가하거나 바꿀 때는 **스케줄을 끈 채로 머지**하고 `workflow_dispatch` 로 소량
실행해 산출물을 확인한 뒤 켜세요. 이 단계적 절차가 실제로 오염을 1건에서 멈춘
이력이 있습니다 (`.github/workflows/backfill-url-summaries.yml` 주석 참고).

## 버그 신고

- 일반 버그·수집기 실패: [이슈 템플릿](https://github.com/Twodragon0/investing/issues/new/choose)
- 보안 취약점: 공개 이슈를 열지 말고 [SECURITY.md](SECURITY.md) 절차를 따라
  주세요
