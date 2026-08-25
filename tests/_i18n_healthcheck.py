"""Jekyll 프리뷰 헬스체크 — "아무도 안 듣고 있음" 과 "듣고 있는데 준비 안 됨" 을 구분한다.

## 왜 별도 모듈인가

로직 자체는 `tests/i18n/conftest.py` 의 세션 fixture 안에 있었다. conftest 는 이름으로
import 할 수 없어서 단위 테스트가 불가능했고, 그래서 30초짜리 대기 루프가 한 번도
검증된 적이 없었다. `tests/conftest.py` 가 `tests/` 를 `sys.path` 에 올리므로 여기
있는 밑줄 접두 헬퍼는 `tests/test_i18n_healthcheck.py` 에서 그대로 import 된다
(`_tree_write_guard` · `_golden` 과 같은 규약).

## 무엇을 고쳤나

이전 구현은 실패를 한 덩어리로 잡았다:

    except (urllib.error.URLError, ConnectionError, TimeoutError):

그래서 **포트에 아무도 안 붙어 있는 경우**(로컬에서 `jekyll serve` 를 안 띄운
경우)에도 30초를 꽉 채운 뒤에야 skip 했다. 실측 `16 skipped in 30.43s`.

세 실패는 의미가 다르다:

| 예외 | 의미 | 재시도 가치 |
|---|---|---|
| `ConnectionRefusedError` | 포트에 바인드된 프로세스가 **없다** | 낮음 |
| `socket.timeout` / `TimeoutError` | 바인드는 됐는데 응답이 느리다 | 높음 |
| `HTTPError`(상태코드 있음) | 서버가 살아 있다 | 높음 |

그래서 **refused 만 연속으로 나오고** 유예 시간이 지나면 즉시 포기한다. refused 가
아닌 결과가 한 번이라도 나오면 `only_refused` 를 내리고 전체 예산을 그대로 쓴다.

즉시 포기가 아니라 유예를 두는 이유: `jekyll serve --detach` 는 셸 명령이 리턴한
**뒤에** 포트를 바인드한다. 다른 터미널에서 serve 를 막 띄우고 바로 pytest 를 돌리는
로컬 흐름이 실재한다.
"""

from __future__ import annotations

import os
import time
import urllib.error
import urllib.request
from typing import Callable, Mapping, NamedTuple

DEFAULT_BASE_URL = "http://127.0.0.1:4000"

#: 서버가 준비되기를 기다리는 전체 예산.
HEALTHCHECK_TIMEOUT_S = float(os.environ.get("I18N_E2E_HEALTHCHECK_TIMEOUT", "30"))

#: 폴링 간격.
HEALTHCHECK_INTERVAL_S = 0.5

#: refused 만 연속으로 나올 때 버티는 시간. 이 시간을 넘기면 "아무도 안 듣고 있다"로
#: 판정하고 즉시 포기한다. 기본 2.0s = 4회 시도 — `jekyll serve --detach` 가 포트를
#: 바인드하기까지의 지연을 흡수하기에 충분하고, 서버가 아예 없을 때 30초를 태우지는
#: 않는다. 0 이면 첫 refused 에 곧바로 포기한다.
FAST_FAIL_GRACE_S = float(os.environ.get("I18N_E2E_FAST_FAIL_GRACE", "2.0"))

#: 개별 요청 타임아웃.
REQUEST_TIMEOUT_S = 2

#: 판정 사유. skip/fail 메시지가 둘을 구분해서 말해야 로컬 개발자가 "Jekyll 을 안
#: 띄웠다" 와 "띄웠는데 느리다" 를 헷갈리지 않는다.
REASON_REFUSED = "refused"
REASON_DEADLINE = "deadline"
REASON_OK = "ok"


class Probe(NamedTuple):
    """헬스체크 결과."""

    ok: bool
    reason: str
    attempts: int
    last_error: BaseException | None = None


def resolve_base_url(env: Mapping[str, str] | None = None) -> str:
    source = os.environ if env is None else env
    return source.get("I18N_E2E_BASE_URL", DEFAULT_BASE_URL).rstrip("/")


def is_connection_refused(exc: BaseException) -> bool:
    """예외가 "포트에 아무도 없음" 인지 판정한다.

    `urlopen` 은 원 예외를 `URLError.reason` 에 감싸 넣는다. 다만 `HTTPError` 의
    `reason` 은 문자열(HTTP reason phrase)이므로 `isinstance` 검사가 그대로 안전하다.
    감싸지 않고 올라오는 경로도 있어 양쪽을 모두 본다.
    """
    if isinstance(exc, ConnectionRefusedError):
        return True
    return isinstance(getattr(exc, "reason", None), ConnectionRefusedError)


def wait_for_server(
    url: str,
    timeout_s: float = HEALTHCHECK_TIMEOUT_S,
    grace_s: float = FAST_FAIL_GRACE_S,
    *,
    interval_s: float = HEALTHCHECK_INTERVAL_S,
    opener: Callable[..., object] = urllib.request.urlopen,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
) -> Probe:
    """홈페이지가 응답할 때까지 폴링한다. refused 만 이어지면 `grace_s` 후 포기.

    `opener` / `sleep` / `monotonic` 이 주입 가능한 이유는 단위 테스트 때문이다 —
    실제 대기 없이 유예 로직과 예산 로직을 각각 검증할 수 있어야 한다.
    """
    start = monotonic()
    only_refused = True
    attempts = 0
    last_error: BaseException | None = None

    while monotonic() - start < timeout_s:
        attempts += 1
        try:
            with opener(url + "/", timeout=REQUEST_TIMEOUT_S) as resp:  # noqa: S310
                if 200 <= resp.status < 500:
                    return Probe(True, REASON_OK, attempts)
            # 응답은 왔다 — 포트에 누가 있다는 뜻이므로 fast-fail 대상이 아니다.
            only_refused = False
        except (urllib.error.URLError, ConnectionError, TimeoutError, OSError) as exc:
            last_error = exc
            if not is_connection_refused(exc):
                only_refused = False

        if only_refused and monotonic() - start >= grace_s:
            return Probe(False, REASON_REFUSED, attempts, last_error)

        sleep(interval_s)

    return Probe(False, REASON_DEADLINE, attempts, last_error)


def unreachable_message(url: str, probe: Probe) -> str:
    """서버에 못 붙었을 때 사람이 읽을 메시지. 사유별로 다른 행동을 지시한다."""
    if probe.reason == REASON_REFUSED:
        return (
            f"{url} 에서 연결이 거부됐다 — 포트에 아무것도 붙어 있지 않다 "
            f"({probe.attempts}회 시도). `bundle exec jekyll serve --port 4000` 으로 "
            "프리뷰를 띄우거나 I18N_E2E_BASE_URL 을 설정할 것."
        )
    return (
        f"{url} 이 {HEALTHCHECK_TIMEOUT_S:g}s 안에 준비되지 않았다 "
        f"({probe.attempts}회 시도, 마지막 오류: {probe.last_error!r}). 서버는 살아 있으나 "
        "응답이 느리다 — I18N_E2E_HEALTHCHECK_TIMEOUT 으로 예산을 늘릴 수 있다."
    )


def should_fail_hard(env: Mapping[str, str] | None = None) -> bool:
    """CI 에서는 서버 부재를 skip 이 아니라 **실패**로 다룬다.

    `i18n-e2e.yml` 은 pytest 앞에 `curl` 루프로 서버를 보장하지만, 그 체크와 pytest
    사이에 서버가 죽으면 16건이 skip 되고 **잡은 green 으로 끝난다.** 창은 좁지만
    실재하고, 실패가 red 로 드러나지 않는 종류다. 로컬에서는 지금처럼 skip 이 맞다 —
    Jekyll 을 안 띄운 채 단위 스위트를 돌리는 건 정상적인 흐름이다.
    """
    source = os.environ if env is None else env
    return bool(source.get("CI"))
