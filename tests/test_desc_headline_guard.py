"""영어 헤드라인 누출 방지 장치가 조용히 풀리는 것을 막는 회귀 가드.

수집기들은 `description_ko` 를 최상위 항목의 헤드라인으로 시작한다. 그 헤드라인이
영어로 남으면 한국어 포스트의 description 이 영어로 끝나고, 이 결함은 사이트가
정상으로 보이기 때문에 `scripts/check_description_quality.py` 리포트에서만 드러난다.
막는 장치는 세 겹이고, 각 겹은 서로 다른 방식으로 조용히 무력화될 수 있다:

1. **임계값 SSoT** — 리포트가 자체 임계값 리터럴을 되살리면, 리포트가 세는 기준과
   수집기가 강제하는 기준이 갈라진다. 리포트는 여전히 green 을 낸다.
2. **fail-open 재판정** — `common/translator.py` 의 `translate_to_korean` 은 실패 시
   입력을 **그대로** 돌려준다. `select_korean_headline` 이 그 반환값을 다시 판정하지
   않으면 영어 원문이 "번역 결과" 로 통과한다. 예외도, 로그도 남지 않는다.
3. **호출부 커버리지** — 헬퍼가 멀쩡해도 수집기가 부르지 않으면 아무 일도 없다.
   새 수집기가 옛 `title_ko or title` 관용구를 복사해 오는 경로가 여기다.

## 가드가 소스를 읽는 이유

1번과 3번은 **런타임 값이 아니라 코드의 형태**를 지킨다. 임계값은 리터럴을 다시
써도 값이 같으면 런타임으로는 구별되지 않고, import 는 지워도 다른 관용구로
대체되면 동작이 바뀔 뿐 예외가 나지 않는다. 그래서 AST/소스 수준에서 확인한다.

## 호출부 가드의 범위

`description_ko` 를 헤드라인으로 시작하는 수집기 6개를 모두 고정한다. 새 수집기가
같은 패턴을 쓰면서 목록에 빠지면 이 가드는 잡지 못하므로, 수집기를 추가할 때
목록도 함께 늘려야 한다.
"""

from __future__ import annotations

import re
from pathlib import Path
from unittest.mock import patch

import check_description_quality as cdq
import pytest

from common import summary_quality
from common.headline import select_korean_headline

# 프로덕션 모듈의 경로 상수를 import 하지 않는다 — hermetic 가드가 그 import 를
# 저장소 앵커링으로 보고 실패시킨다. 테스트 파일 자신의 위치에서 도출한다.
_SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"

_ENGLISH_HEADLINE = "Treasury Sec Bessent Speaks"

# 임계값이 이 이름으로 import 되어야 한다. 리터럴 재도입은 값이 같아도 SSoT 를 깬다.
_THRESHOLD_LITERAL_RE = re.compile(r"(?<![\w.])0\.70?(?![\d\w])")
_THRESHOLD_IMPORT_RE = re.compile(
    r"^from common\.summary_quality import \(?[\s\S]{0,400}?\bASCII_RATIO_THRESHOLD\b",
    re.MULTILINE,
)

# `from common.headline import select_korean_headline` — 줄 번호가 아니라
# import 문 자체에 고정한다. 파일이 재정렬돼도(ruff isort) 그대로 유효하다.
_HEADLINE_IMPORT_RE = re.compile(
    r"^from common\.headline import \(?[\s\S]{0,200}?\bselect_korean_headline\b",
    re.MULTILINE,
)

_HEADLINE_COLLECTORS = [
    pytest.param("collect_fmp_calendar.py", id="fmp_calendar"),
    pytest.param("collect_political_trades.py", id="political_trades"),
    pytest.param("collect_crypto_news.py", id="crypto_news"),
    pytest.param("collect_geopolitical.py", id="geopolitical"),
    pytest.param("collect_worldmonitor_news.py", id="worldmonitor_news"),
    pytest.param("collect_social_media.py", id="social_media"),
]


def _read(filename: str) -> str:
    path = _SCRIPTS_DIR / filename
    assert path.is_file(), f"가드가 참조하는 파일이 없다: {path}"
    return path.read_text(encoding="utf-8")


class TestThresholdSingleSourceOfTruth:
    """리포트와 수집기 가드가 같은 ASCII 임계값을 봐야 한다."""

    def test_report_reuses_the_shared_threshold_object(self) -> None:
        assert cdq._ASCII_RATIO_THRESHOLD is summary_quality.ASCII_RATIO_THRESHOLD, (
            "check_description_quality 의 임계값이 common.summary_quality 의 객체가 아니다 — "
            "리터럴을 다시 정의하면 값이 같아도 한쪽만 움직일 수 있다"
        )

    def test_report_imports_the_threshold_by_name(self) -> None:
        source = _read("check_description_quality.py")
        assert _THRESHOLD_IMPORT_RE.search(source), (
            "check_description_quality.py 가 common.summary_quality 에서 ASCII_RATIO_THRESHOLD 를 import 하지 않는다"
        )

    def test_report_does_not_redefine_the_threshold_literal(self) -> None:
        source = _read("check_description_quality.py")
        offenders = [
            line.strip()
            for line in source.splitlines()
            if _THRESHOLD_LITERAL_RE.search(line) and not line.lstrip().startswith("#")
        ]
        assert not offenders, (
            "check_description_quality.py 에 ASCII 임계값 리터럴이 되살아났다. "
            f"common.summary_quality.ASCII_RATIO_THRESHOLD 를 쓸 것: {offenders}"
        )

    def test_report_reuses_the_shared_detector(self) -> None:
        assert cdq._is_ascii_ratio_high is summary_quality.is_ascii_heavy, (
            "리포트가 자체 ASCII 판정기를 되살렸다 — 임계값이 같아도 판정 규칙이 갈라진다"
        )


class TestTranslationFailOpenIsRejudged:
    """`translate_to_korean` 의 fail-open 반환을 번역 성공으로 착각하면 안 된다."""

    def test_unchanged_translation_yields_empty_string(self) -> None:
        with patch("common.headline.translate_to_korean", side_effect=lambda t: t) as mock_tr:
            result = select_korean_headline({"title": _ENGLISH_HEADLINE})

        mock_tr.assert_called_once_with(_ENGLISH_HEADLINE)
        assert result == "", (
            "translate_to_korean 이 입력을 그대로 돌려줬는데(common/translator.py 의 fail-open) "
            f"select_korean_headline 이 그것을 한국어로 통과시켰다: {result!r}"
        )

    def test_empty_translation_yields_empty_string(self) -> None:
        with patch("common.headline.translate_to_korean", return_value=""):
            assert select_korean_headline({"title": _ENGLISH_HEADLINE}) == ""

    def test_short_english_is_rejected_too(self) -> None:
        """리포트용 판정기(`is_ascii_heavy`)는 30자 미만을 건너뛴다.

        헤드라인은 짧아도 영어면 영어이므로 길이 무관 판정기를 써야 한다. 여기서
        길이 가드가 있는 쪽으로 되돌아가면 짧은 영어 헤드라인이 다시 샌다.
        """
        with patch("common.headline.translate_to_korean", side_effect=lambda t: t):
            assert select_korean_headline({"title": "Fed holds rates"}) == ""


class TestHeadlineCallSiteCoverage:
    """헬퍼가 있어도 수집기가 부르지 않으면 아무것도 막지 못한다."""

    @pytest.mark.parametrize("filename", _HEADLINE_COLLECTORS)
    def test_collector_imports_the_shared_selector(self, filename: str) -> None:
        source = _read(filename)
        assert _HEADLINE_IMPORT_RE.search(source), (
            f"{filename} 이 common.headline.select_korean_headline 을 import 하지 않는다. "
            "description_ko 헤드라인은 이 헬퍼를 거쳐야 영어가 새지 않는다"
        )
