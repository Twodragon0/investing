# _state 마찰 완화 (skip-worktree + merge=ours)

로컬에서 수집기를 실행하면 `_state/*.json` (dedup 상태)이 매번 바뀌어 git 작업을 방해한다.
이 문서는 그 마찰을 줄이는 2단 설정(C+B)과 셋업 절차를 정리한다.

## 문제

- 수집기 실행 → `_state/*.json` 해시/타임스탬프 갱신 → `git status` 가 항상 더러움
- 실수로 상태 파일이 커밋되거나, `git pull` 시 머지 충돌 발생
- `_state/*.json` 은 자동화(CI/cron)가 갱신·커밋하는 파생물이라 로컬 변경은 노이즈

## 해결 (2단)

### C) skip-worktree — 로컬 변경 무시

추적 중인 `_state` 파일에 `skip-worktree` 플래그를 설정해 git 이 로컬 변경을 무시하게 한다.

- `git status` 가 깨끗하게 유지되고 실수 커밋이 차단된다.
- `.git/index` 의 로컬 플래그라 **다른 개발자/CI 에 전파되지 않는다** → 각자 한 번씩 적용.
- 자동화는 이 설정을 하지 않으므로 `_state` 커밋 파이프라인은 정상 동작한다.

### B) merge=ours 드라이버 — 충돌 자동 흡수

`.gitattributes` 에는 이미 다음이 선언돼 있다:

```gitattributes
_state/*.json merge=ours
```

그러나 git 에는 `ours` 라는 이름의 **내장 머지 드라이버가 없다.** 로컬 config 에
드라이버를 등록하기 전까지 이 attribute 는 **무동작(no-op)** 이다:

```bash
git config merge.ours.driver true   # 'true' 는 항상 성공 종료 → 현재(ours) 버전 유지
```

등록 후에는 `_state/*.json` 머지 충돌이 자동으로 우리(local) 버전으로 해소된다.

## 셋업

클론 후 한 번 실행한다(개발자 머신 단위):

```bash
bash scripts/dev_ignore_state.sh            # 적용 (드라이버 등록 + skip-worktree)
bash scripts/dev_ignore_state.sh --status   # 현재 상태 확인
bash scripts/dev_ignore_state.sh --undo     # 원복
```

`--status` 예시 출력:

```
== merge=ours 드라이버 ==
  [O] 등록됨 (merge.ours.driver=true) → .gitattributes 의 merge=ours 동작함
== skip-worktree (_state, 19개 추적) ==
  [O] 19개 파일에 skip-worktree 적용됨
```

## 주의

- skip-worktree 적용 후 `git pull` 이 `_state` 변경을 덮어쓰지 못해 막힐 수 있다.
  이때는 `--undo` 로 잠시 해제하거나, 등록된 merge=ours 드라이버가 충돌을 흡수한다.
- `_state/*.json` 은 **직접 수동 편집 금지** (pre-commit 훅 `pre-commit-state-guard` 가 차단).
- 새 `_state` 파일이 추가되면 `dev_ignore_state.sh` 를 다시 실행해 신규 파일에도 플래그를 적용한다.

관련 파일: `scripts/dev_ignore_state.sh`, `.gitattributes`
