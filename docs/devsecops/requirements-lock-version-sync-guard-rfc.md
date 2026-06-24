# RFC: requirements 락 버전-동기 가드 (해소 버전 대조)

> 상태: **RFC (제안, 미구현)** · 작성 2026-06-24
> 관련: `docs/devsecops/requirements-lock-autosync-design.md`, `.github/workflows/supply-chain-lock.yml`,
> `tests/test_requirements_lock_coverage.py`, 위키 `공급망 락 (requirements.lock) — 가드·차단승격·헬퍼·재현 실증`

## 1. 동기 (메우려는 사각지대)

현 가드 2종은 **이름 기반**이라 *기존 의존성의 버전 bump* 를 잡지 못한다(설계 문서 1.1):

- `tests/test_requirements_lock_coverage.py` — 직접 의존성 **이름** ⊆ 락 핀 이름 + 해시 presence.
- `supply-chain-lock.yml` — `--require-hashes` 내부 일관성 + 동일 이름 커버리지.

→ 봇/사람이 `requirements.txt` 에서 `requests==2.33.1 → 2.34.0` 으로 올리고 락을 재생성하지
않으면, 두 가드 모두 green 인데 락은 `requests==2.33.1` 을 핀한 채로 남는다. 런타임 12개
워크플로우는 `pip install -r requirements.txt` 로 **2.34.0** 을 받고, 무결성 검증은 **2.33.1**
을 확인한다 → 검증 대상과 설치 대상의 괴리. 2026-07-06 차단 승격 후 이 stale 은 잠재 리스크.

## 2. 제안: 단일 불변식 — "락 핀이 txt 명세를 만족한다"

직접 의존성마다 **락의 핀 버전이 requirements.txt 의 PEP 508 specifier 를 만족**해야 한다.
`packaging.specifiers.SpecifierSet.contains()` 한 줄로 두 제약 클래스를 동시에 커버한다.

```python
from packaging.specifiers import SpecifierSet
from packaging.version import Version
# 예: txt "requests==2.34.0", lock "requests==2.33.1"
SpecifierSet("==2.34.0").contains(Version("2.33.1"))  # → False  ⇒ stale 차단 ✓
# 예: txt "boto3>=1.40,<2", lock "boto3==1.43.36"
SpecifierSet(">=1.40,<2").contains(Version("1.43.36"))  # → True   ⇒ 통과 ✓
```

### 2.1 두 클래스에서의 동작

| txt 제약 | lock 핀 | `contains` | 판정 | 의미 |
|----------|---------|:--:|------|------|
| `requests==2.34.0` | `2.33.1` | False | **FAIL** | 정확 핀 bump 후 락 미갱신 (핵심 케이스) |
| `requests==2.33.1` | `2.33.1` | True | PASS | 동기 상태 |
| `boto3>=1.44,<2` | `1.43.36` | False | **FAIL** | 범위 floor 상향이 락 핀을 벗어남 |
| `boto3>=1.40,<2` | `1.43.36` | True | PASS | 락이 범위 내 — **stale 아님**(앵커 결정성, 의도된 동작) |

핵심: 범위 제약에서 "범위 내 더 최신 버전이 있는데 락이 안 가졌다"는 **stale 이 아니다**
(in-place 앵커로 범위 내 고정 = 우리가 원하는 결정성). 가드는 *진짜 불일치*에만 발화한다.

## 3. 구현 (network 없음, stdlib + packaging)

- `packaging==26.2` 가 이미 락의 전이 의존성으로 존재(검증 2026-06-24) → import 가능, 신규
  직접 의존성 추가 불필요.
- 기존 `tests/test_requirements_lock_coverage.py` 는 **stdlib-only** 를 표방. 충돌을 피해
  **별도 테스트 파일** `tests/test_requirements_lock_version_sync.py` 로 추가(packaging 의존
  격리). 또는 동일 파일에 `pytest.importorskip("packaging")` 가드로 추가.
- 파서: txt 의 `name SPECIFIER` 분해는 `packaging.requirements.Requirement` 사용(extras/마커
  안전). 락의 핀은 기존 정규식(`^name(?:[extra])?==ver`) 재사용.

### 3.1 스케치

```python
from packaging.requirements import Requirement
from packaging.version import Version

def test_lock_pins_satisfy_requirements_specifiers():
    direct = parse_requirements(REQUIREMENTS_TXT.read_text())   # name -> SpecifierSet
    locked = parse_lock_pins(REQUIREMENTS_LOCK.read_text())      # name -> Version
    violations = []
    for name, spec in direct.items():
        pin = locked.get(name)
        if pin is None:
            continue  # 커버리지(이름 부재)는 기존 가드 책임 — 중복 검사 금지
        if not spec.contains(pin, prereleases=True):
            violations.append(f"{name}: txt '{spec}' ↛ lock '{pin}'")
    assert not violations, (
        "락 핀이 requirements.txt 명세를 만족하지 않음(버전 bump 후 락 미갱신?):\n"
        + "\n".join(violations)
        + "\n→ bash scripts/refresh_requirements_lock.sh 로 락 재생성."
    )
```

### 3.2 non-vacuous 보강 (기존 테스트 관례 준수)

- canary: 대상 파일 존재/비어있지 않음(기존 테스트와 동일).
- negative: 합성 입력(`requests==2.34.0` vs lock `2.33.1`)에서 violation 이 실제로 잡히는지.
- 파서 견고성: extras(`name[extra]`), 환경 마커(`; python_version<'3.12'`), 대소문자/언더스코어
  정규화(`_`↔`-`) 케이스.

## 4. 배치 결정 (어디서 도는가)

| 위치 | 장점 | 비고 |
|------|------|------|
| 매 PR pytest (Code Quality) | 모든 PR·로컬에서 즉시, 워크플로우 트리거 무관 | 권장 1순위 (기존 커버리지 가드와 동일 lane) |
| `supply-chain-lock.yml` 인라인 스텝 | 락/txt 변경 시 집중 검증 | 커버리지 검사처럼 pytest 와 **동일 불변식 미러링** 유지 |

권장: **pytest 가드로 추가**(매 PR green/red 즉시). `supply-chain-lock.yml` 에는 동일 로직을
인라인 미러(기존 "covers direct deps" 스텝 옆)로 두어 두 곳이 같은 불변식을 같은 방식으로
보게 한다(현 커버리지 가드의 정책과 일관).

## 5. 자동동기 파이프라인과의 관계

- 이 가드는 **탐지(detect)**, 자동동기 파이프라인은 **교정(remediate)**. 상호 보완.
- 토큰 확보 전(자동동기 미구현) 구간에서 이 가드가 *유일한* stale 차단선 → **즉시 도입 가치
  높음**(자동동기보다 선행 권장).
- 자동동기 도입 후에도 가드는 회귀 안전망으로 유지(파이프라인 실패/우회 시 최종 게이트).

## 6. 한계 / 비목표

- **범위 내 최신성**은 검사하지 않음(의도). "범위 내 더 최신이 있다"는 stale 이 아니라 결정성.
  전 패키지 최신화는 `lockFileMaintenance`/주기 재생성의 영역.
- **전이 의존성**의 버전은 검사하지 않음(직접 의존성만). 전이는 `--require-hashes` 무결성이 담당.
- prerelease 정책: `prereleases=True` 로 둘지 여부는 구현 시 결정(현 의존성에 prerelease 없음 →
  보수적으로 True 권장해 false-negative 방지).

## 7. 채택 체크리스트

1. `tests/test_requirements_lock_version_sync.py` 추가(canary + positive + negative + 파서 견고성).
2. `python3 -m pytest tests/test_requirements_lock_version_sync.py --no-cov -q` green.
3. 합성 stale(정확 핀 bump, 범위 floor 상향) 2케이스가 실제 red 가 되는지 확인(non-vacuous).
4. (선택) `supply-chain-lock.yml` 인라인 미러 스텝 추가 + actionlint.
5. 기존 커버리지 가드와 **검사 영역 중복 없음** 확인(이름 부재는 커버리지, 버전 불일치는 본 가드).
```
