# 테스트 격리 fixture 규약

`tests/conftest.py`의 autouse fixture들은 테스트가 **커밋된 레포 트리를 오염시키거나 실제 네트워크에 결합하는 것**을 막는다. 이 문서는 그 8종의 인벤토리와, 새 격리 fixture를 추가할 때 반드시 따라야 할 규약을 정리한다.

관련 가드: `tests/test_suite_isolation_guard.py` (fixture가 제거되면 즉시 red)

---

## 1. 인벤토리

| # | fixture | 대상 심볼 | 마커 게이트 | 대응 가드 |
|---|---------|-----------|-------------|-----------|
| 0 | *(모듈 레벨, import 시점)* | `image_rejection_metrics._STATE_PATH` / `._ARCHIVE_DIR` | — | `test_image_rejection_atexit_baseline_off_repo_tree` |
| 1 | `_block_real_http` | `requests.adapters.HTTPAdapter.send` | — | `test_real_http_transport_blocked` |
| 2 | `_deterministic_dns_resolution` | `socket.getaddrinfo` + `utils._dns_cache` | — | `test_ssrf_dns_resolution_pinned_off_live_network` |
| 3 | `_isolate_generated_images` | `image_generator.IMAGES_DIR` | — | `test_generated_images_redirected_off_repo_tree` |
| 4 | `_isolate_dedup_state` | `dedup.STATE_DIR` | `no_state_isolation` | `test_dedup_state_redirected_off_repo_tree` |
| 5 | `_isolate_signal_history_state` | `signal_tracker._HISTORY_FILE` | `no_state_isolation` | `test_signal_history_redirected_off_repo_tree` |
| 6 | `_isolate_translation_cache` | `translator._CACHE_PATH` + `_cache` / `_cache_dirty` | `no_state_isolation` | `test_translation_cache_redirected_off_repo_tree` |
| 7 | `_isolate_image_rejection_state` | `image_rejection_metrics._STATE_PATH` / `._ARCHIVE_DIR` | — | `test_image_rejection_state_redirected_off_repo_tree` |

#0과 #7은 같은 모듈을 다루지만 역할이 다르다 — 규약 6 참조.

fixture 정의 순서 = setup 실행 순서이고, teardown은 정확히 역순이다 (`pytest --setup-show`로 확인 가능). 따라서 #1·#2가 가장 먼저 설치되고 가장 나중에 해제된다 — 어떤 `_isolate_*`의 teardown도 실제 네트워크에 도달할 수 없다.

---

## 2. 규약

### 규약 1 — 호출부가 아니라 **모듈 속성**을 리다이렉트한다

프로덕션 코드가 전역을 **호출 시점에** 읽어야 autouse 리다이렉트가 성립한다. 이미 만족하는 사례:

- `DedupEngine.__init__`이 `os.path.join(dedup.STATE_DIR, ...)`를 생성 시점에 평가
- `signal_tracker._HISTORY_FILE`은 lazy sentinel — 무인자 `SignalTracker()`가 호출 시점에 해석
- `translator._CACHE_PATH`는 `_save_cache()` / `_load_cache()`가 호출 시점에 읽음 (import 시점 기본 인자 바인딩 아님)

**반례:** `def f(path=STATE_DIR)` 처럼 기본 인자로 바인딩하면 import 시점에 값이 고정되어 리다이렉트가 무력화된다. 이런 코드는 fixture가 아니라 프로덕션 쪽을 고쳐야 한다.

### 규약 2 — 모듈 트윈 **양쪽**을 패치한다

`common.X`와 `scripts.common.X`는 **같은 파일에서 로드된 별개 모듈 객체**다. 실측:

```
same module obj: False | same _dns_cache: False | same lock: False
both __file__ == scripts/common/utils.py
```

일부 테스트는 `scripts.common.*`로 import하므로 한쪽만 패치하면 그 테스트에서 격리가 새어나간다. 8종 전부 다음 형태를 따른다:

```python
try:
    import scripts.common.X as x_scripts
    if x_scripts is not x:
        monkeypatch.setattr(x_scripts, "ATTR", dest)
except ImportError:
    pass
```

### 규약 3 — **파생 메모 상태**도 함께 리셋한다

경로만 바꾸고 메모 캐시를 남기면 early-return이 리다이렉트를 무력화한다.

- `translator`: `_cache` / `_cache_dirty`를 리셋하지 않으면, `_load_cache()`가 `_cache is not None`으로 조기 반환해 재지정된 경로를 다시 읽지 않는다
- `_deterministic_dns_resolution`: `_dns_cache`(cachetools TTLCache)를 clear하지 않으면 이전 리졸버로 캐시된 값이 누수된다

clear는 **setup 시점에만** 해도 충분하다 — 모든 테스트의 setup이 무조건 실행되므로, 앞선 테스트가 오염시킨 항목은 다음 테스트 시작 전에 이미 제거된다. teardown clear는 중복이다.

### 규약 4 — `no_state_isolation` 마커는 **경로 리다이렉트 fixture에만**

`tests/test_state_path_anchoring.py`의 런타임 앵커링 가드는 `STATE_DIR` 등이 **실제 레포 루트 아래**에 있는지 검사한다. 경로를 tmp로 돌리는 fixture는 이 가드를 무력화하므로 마커로 opt-out해야 한다.

반대로 경로를 건드리지 않는 fixture(#1 HTTP, #2 DNS)에 마커 게이트를 다는 것은 **오류**다. 앵커링 가드와 충돌할 표면이 없는데 격리만 잃는다.

> 판정 기준: **레포 앵커 경로를 재지정하는가?** → Yes면 게이트, No면 무조건 적용.

### 규약 5 — fixture마다 **환경 독립적인** 가드 테스트를 짝지운다

가드는 fixture가 제거되면 **CI에서도** 실패해야 한다. 오프라인에서만 실패하는 가드는 무의미하다.

- 경로형: 활성 경로가 커밋된 트리 아래가 아님을 단언
- 스텁형: 스텁 함수에 마커 속성을 달고 그것을 단언 — `_ssrf_dns_stub`, `_http_block_stub`. 실제 `socket.getaddrinfo` / `HTTPAdapter.send`에는 이 속성이 없으므로 네트워크 상태와 무관하게 판별된다

**행위 프로브를 쓰지 말 것**: "실제로 요청해서 RuntimeError가 나는지" 검사하면, fixture가 없을 때 가드 자신이 막으려던 실제 외부 호출을 수행한다.

가드는 프로덕션의 `REPO_ROOT` / `POSTS_DIR` 상수를 import하면 안 된다 (`test_hermetic_test_writes_guard`가 이를 비-hermetic 신호로 차단). `__file__` 앵커로 도출한다:

```python
_REPO_ROOT = Path(__file__).resolve().parent.parent
```

단언이 vacuous하지 않은지도 확인한다. 예: `_dns_cache` 공백 단언은 `is_private_url_target` 1회 호출로 길이가 `0 → 1`이 되므로 clear가 no-op이면 실제로 red가 된다.

**실증 방법 — 워크트리에서 fixture를 실제로 꺼본다.** 8종 전부에 대해 검증했고, 실제로 vacuous한 가드를 1건 찾아냈다 (함정 6 참조).

```bash
git worktree add --detach /tmp/inv-falsify HEAD
# fixture별로 autouse=True → False 로 바꿔 해당 가드만 실행,
# patched_rc != 0 (red) && control_rc == 0 (green) 이어야 통과
git worktree remove /tmp/inv-falsify
```

주의: `tests/conftest.py`를 짧은 간격으로 반복해 덮어쓰면 `__pycache__`가 무효화되지 않아(pyc 검증은 mtime+size 기반) 결과가 실행마다 뒤집힌다. `python3 -B` + `PYTHONDONTWRITEBYTECODE=1` + 매 실행 전 `__pycache__` 삭제로 고정하고, 패치 해제 상태(control)도 함께 돌려 green을 확인해야 한다.

### 규약 6 — `atexit` flush 모듈은 **import 시점** 리다이렉트가 추가로 필요하다

`atexit` 훅은 인터프리터 종료 시, 즉 **모든 per-test monkeypatch가 해제된 뒤** 실행된다. 따라서 per-test fixture만으로는 부족하고, monkeypatch가 *복원할 대상 값* 자체가 이미 off-tree여야 한다. `image_rejection_metrics`가 유일한 사례이며 `tests/conftest.py` 최상단에서 처리한다.

이 import 시점 블록은 `except ImportError: pass`로 감싸여 있어 조용히 실패할 수 있다. `_STATE_TMP`는 import 성공 이후에만 바인딩되므로 정확한 tripwire가 된다.

---

## 3. 신규 격리 fixture 체크리스트

- [ ] 프로덕션이 대상 전역을 **호출 시점에** 읽는가? (규약 1)
- [ ] `common.*` / `scripts.common.*` 트윈을 모두 패치했는가? (규약 2)
- [ ] 파생 메모 캐시를 리셋했는가? (규약 3)
- [ ] 레포 앵커 경로를 재지정한다면 `no_state_isolation` 게이트를 달았는가? 아니라면 **달지 않았는가**? (규약 4)
- [ ] `test_suite_isolation_guard.py`에 환경 독립적 가드를 추가했는가? (규약 5)
- [ ] `atexit`/종료 시점 훅이 있는 모듈이면 import 시점 리다이렉트도 했는가? (규약 6)
- [ ] **전체 스위트를 랜덤 순서와 고정 순서 양쪽으로** 돌렸는가? (아래 함정 3)
- [ ] `ruff check` + `ruff format --check` + `basedpyright` 통과? (함정 4)

---

## 4. 함정 사례집

실제로 CI red 또는 flaky를 유발했던 사례들.

**함정 1 — autouse fixture vs 런타임 앵커링 가드**
`dedup.STATE_DIR` autouse 리다이렉트가 `test_state_path_anchoring.py`와 충돌했다. → `no_state_isolation` 마커 도입. autouse fixture를 추가한 뒤에는 **반드시 전체 스위트를 돌릴 것**.

**함정 2 — 리졸버 스텁이 loopback까지 리다이렉트 (PR #1070)**
`socket.getaddrinfo`를 호스트 무관하게 고정 IP로 스텁하면 `127.0.0.1` / `localhost` 접속까지 off-box로 나가 `[Errno 49] Can't assign requested address`로 실패한다. 로컬 서버를 띄우는 테스트를 추가하는 순간 원인을 알기 어렵게 깨진다.
→ loopback 호스트명과 리터럴 IP는 원본 리졸버로 패스스루하고, sockaddr에 요청 포트를 보존한다. 리터럴 IP는 `getaddrinfo`가 수치 파싱만 하므로 오프라인 안전성은 유지된다.

**함정 3 — 고정 공인 IP 선택**
RFC 5737 문서화 대역(`203.0.113.x`, `192.0.2.x`, `198.51.100.x`)은 Python `ipaddress`에서 전부 `is_private=True`, `233.252.0.1`은 multicast다. `utils._is_non_public_ip`가 모두 차단하므로 **문서화 대역은 쓸 수 없다**. 실제 공인 IP를 써야 한다 (현재 `93.184.216.34`). 스텁이므로 실제 트래픽은 발생하지 않는다.

**함정 4 — 로컬 검증 ≠ CI**
`ruff check`만으로는 부족하다. CI Code Quality는 `ruff format --check`도 실행하며 포맷 누락이 흔한 red 원인이다. 옵셔널 import 폴백(`X = None`)은 `basedpyright`의 `reportOptionalMemberAccess`를 유발한다. 푸시 전 3종을 모두 돌린다.

**함정 5 — 가드 테스트가 프로덕션 상수를 import**
새 가드가 `REPO_ROOT` / `POSTS_DIR` / `SITE_DIR`를 프로덕션에서 import하면 hermetic 가드가 CI red를 낸다. `__file__` 앵커로 도출하고, 격리는 문자열 monkeypatch로 한다.

**함정 6 — 이중 방어가 가드를 vacuous하게 만든다**
`_isolate_image_rejection_state`의 첫 가드는 "`_STATE_PATH`가 커밋된 `_state/` 아래가 아님"만 단언했는데, **모듈 레벨 리다이렉트(#0)가 이미 이를 보장**하므로 per-test fixture를 꺼도 green이었다 (실증 확인).
→ 같은 대상을 두 겹으로 보호할 때는, 각 계층이 **고유하게 제공하는 것**을 단언해야 한다. 여기서는 per-test 격리이므로 "활성 경로가 import 시점 baseline과 다름"을 추가했다.

---

## 5. 검증 명령

```bash
# 격리 가드만
python3 -m pytest tests/test_suite_isolation_guard.py -q --no-cov

# fixture 실행/해제 순서 확인
python3 -m pytest tests/test_suite_isolation_guard.py --setup-show --no-cov -p no:randomly

# 전체 (랜덤 순서 — 기본)
python3 -m pytest tests/ -q --no-cov

# 전체 (고정 순서 — 순서 의존 버그 분리용)
python3 -m pytest tests/ -q --no-cov -p no:randomly

# 린트/타입
python3 -m ruff check scripts/ tests/
python3 -m ruff format --check scripts/ tests/
python3 -m basedpyright
```

작업 후 커밋된 트리가 깨끗한지 확인:

```bash
git status --short   # _state/, assets/images/generated/ 에 변경이 없어야 함
```

---

## 6. 자동 감시

규약 5의 falsifiability 검증은 `scripts/tools/guard_falsifiability.py`로 상주화되어 있다.

```bash
python scripts/tools/guard_falsifiability.py            # 표 출력
python scripts/tools/guard_falsifiability.py --json     # JSON
python scripts/tools/guard_falsifiability.py --check    # vacuous/미등록 시 exit 1
```

검증 대상은 두 종류다:

| 종류 | 개수 | mutation |
|---|---|---|
| 격리 fixture 가드 (`CASES`) | 8 | `autouse=True → False` (모듈 레벨은 import 를 비존재 모듈로) |
| 정적/설정 가드 (`STATIC_CASES`) | 11 | 가드가 막으려는 **위반을 실제로 주입** |

정적 케이스가 커버하는 가드: `test_state_path_anchoring`(cwd-상대 `_state` 주입, 탐지기 무력화, `__file__` 앵커 제거, 런타임 절대경로), `test_hermetic_test_writes_guard`(테스트의 프로덕션 `REPO_ROOT` import, `_BANNED_NAMES` 비움), `test_coverage_floor_guard`(하한 하향, 게이트 제거, 워크플로우 `--fail-under` 하향).

**앵커는 대상 파일에 정확히 1회만 나타나야 한다.** 여러 번 나타나면 `replace(..., 1)` 이 엉뚱한 줄을 바꾸고 가드가 정당하게 green 이 되어 VACUOUS 오탐이 난다 — 실제로 `fix_defi_tvl_history.py` 감사에서 `__file__` 앵커가 `sys.path.insert` 줄을 먼저 잡아 그렇게 됐다. 하네스는 이를 조용히 넘기지 않고 `AMBIGUOUS-ANCHOR` 로 실패시키며, `test_static_case_anchors_are_unique_in_their_targets` 가 PR 시점에 먼저 잡는다.

`.github/workflows/guard-falsifiability.yml`이 두 시점에 `--check`를 돌린다:

- 가드 본체 / 가드가 감시하는 설정(`pyproject.toml`, `code-quality.yml`) / 하네스 자체를 건드리는 **PR**
- 매주 월요일 05:00 UTC 스케줄

하네스는 `tests/conftest.py`를 덮어썼다 복원하므로:

- 대상 파일에 **미커밋 변경이 있으면 실행을 거부**한다 (중간에 죽으면 작업이 사라지므로)
- 워크플로우가 실행 후 `git status --porcelain`으로 **복원 실패를 별도 검증**한다

새 격리 fixture를 추가하면 `CASES` 레지스트리에도 등록해야 한다. 미등록 시 `UNMAPPED`로 `--check`가 실패하고, `tests/test_guard_falsifiability_tool.py::test_registry_matches_real_conftest`가 주간 잡을 기다리지 않고 **PR 시점에** 잡는다.
