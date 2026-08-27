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

## fast-forward 가 막힐 때 — `dev_sync_state_safe.sh`

skip-worktree 는 `git status` 를 깨끗하게 만들지만 **로컬 변경 자체를 없애지는 않는다.**
그래서 fast-forward 가 거부된다:

```
$ gh pr merge 1234 --squash --delete-branch
error: Your local changes to the following files would be overwritten by merge:
    _state/image_rejection_metrics.json
Aborting
Updating abc1234..def5678
! warning: not possible to fast-forward to: "main"
```

원격 머지는 성공했는데 로컬만 뒤처진다. 2026-08-26 한 세션에서 **세 번** 발생했고
매번 손으로 같은 순서를 반복했다(un-skip → 되돌리기 → pull → 다시 skip). 그 순서를
스크립트로 고정했다:

```bash
gh pr merge 1234 --squash --delete-branch
bash scripts/dev_sync_state_safe.sh            # 동기화
bash scripts/dev_sync_state_safe.sh --dry-run  # 무엇을 버릴지 먼저 확인
bash scripts/dev_sync_state_safe.sh --force    # 큰 _state diff 도 버림
```

`gh pr merge` 래퍼로 만들지 않은 이유: 실패 지점은 머지가 아니라 **로컬 동기화**이고,
같은 일이 평범한 `git pull` 에서도 난다. 래퍼는 `gh pr merge` 의 플래그를 계속 따라가야
하는데 얻는 게 없다.

**무엇을 버리는가**: `_state/*.json` 의 로컬 변경만. 수집기가 다시 만드는 파생물이다.
그 외에는 아무것도 건드리지 않는다.

**안전장치 3개** (`tests/test_dev_sync_state_safe_guard.py` 가 존재를 강제):

| 상황 | 동작 |
|---|---|
| `_state` 밖에 dirty 파일이 있다 | **중단** (exit 1). 커밋/stash 는 사람이 결정 |
| `_state` 파일 diff 가 20줄 초과 | **중단**하고 `--force` 요구. 타임스탬프 bump 가 아니라 실제 내용일 수 있다 |
| 중간에 실패 (pull 불가 등) | skip-worktree 를 **복구**하고 exit 1 |

순서상 알아둘 것: dirty 상태로는 pull 이 안 되므로 **버리기가 pull 보다 먼저**다.
pull 이 실패하면 `_state` 변경은 이미 버려진 뒤다(재생성되므로 손실은 아니다).

## 주의

- skip-worktree 적용 후 `git pull` 이 `_state` 변경을 덮어쓰지 못해 막힐 수 있다.
  위 `dev_sync_state_safe.sh` 를 쓰거나, `--undo` 로 잠시 해제하거나, 등록된
  merge=ours 드라이버가 충돌을 흡수한다.
- `_state/*.json` 은 **직접 수동 편집 금지** (pre-commit 훅 `pre-commit-state-guard` 가 차단).
- 새 `_state` 파일이 추가되면 `dev_ignore_state.sh` 를 다시 실행해 신규 파일에도 플래그를 적용한다.

관련 파일: `scripts/dev_ignore_state.sh`, `.gitattributes`
