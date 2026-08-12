"""대조군 오염과 워크플로우 이름 조립을 자동 판정하는 가드.

## 막으려는 실패 두 개

**1. 대조군 오염.** `[4]` 의 대조군 비는 `regulatory 커밋 / 대조군 커밋` 이다. 파일럿을
다른 수집기로 확대하면서 그 수집기를 `CONTROL_COLLECTORS` 에서 빼지 않으면 분모도
함께 줄어 절감이 과소평가된다. 지금까지는 "사람이 챙긴다" 였다 — 이 파일이 액션
플래그(`skip-noop-state-commits`)를 읽어 자동 판정한다.

실패가 조용하다는 게 문제다. 워크플로우에 플래그 한 줄을 켜는 것은 diff 한 줄이고,
`CONTROL_COLLECTORS` 는 다른 파일에 있어서 리뷰에서 함께 보이지 않는다. 그리고 결과는
"절감이 생각보다 작네" 라는 잘못된 결론이지, 에러가 아니다.

**2. 워크플로우 이름 조립.** `f"collect-{collector}.yml"` 은 수집기 6개 중 2개에서만
맞는다 — `crypto` 는 `collect-crypto-news.yml`, `social` 은 `collect-social-media.yml`
이다. 어긋나면 `gh run list` 가 실패하고, `collect_run_timestamps` 는 설계대로
graceful degradation 해서 **실행당 커밋 지표가 조용히 사라진다.** 확대 시점에 정확히
터지는 함정이라 매핑 테이블과 그 테이블의 실존을 함께 강제한다.

## 방향

- 파일럿 대상은 실제로 플래그가 켜져 있어야 한다 (아래 non-vacuity 참조).
- 대조군은 플래그가 켜진 수집기를 하나도 포함하지 않아야 한다.
- 매핑된 워크플로우 파일은 실제로 존재해야 한다.

`test_pilot_target_flag_is_actually_on` 이 non-vacuity 를 보장한다. 이게 없으면
`pilot_enabled_collectors()` 가 항상 빈 집합을 돌려주는 버그가 있어도 오염 가드가
통과한다 — 공집합은 어떤 집합과도 교집합이 없다.
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).parent.parent
_TOOLS = _ROOT / "scripts" / "tools"
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))
if str(_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(_ROOT / "scripts"))

import check_pilot_observation as cpo  # noqa: E402

_WORKFLOWS = _ROOT / ".github" / "workflows"


# ---------------------------------------------------------------------------
# 매핑 테이블의 실존
# ---------------------------------------------------------------------------


def test_every_mapped_workflow_exists():
    """매핑이 실제 파일을 가리켜야 한다 — 어긋나면 gh 조회가 조용히 실패한다."""
    missing = {name: wf for name, wf in cpo.COLLECTOR_WORKFLOWS.items() if not (_WORKFLOWS / wf).is_file()}
    assert not missing, f"존재하지 않는 워크플로우를 가리키는 매핑: {missing}"


def test_all_referenced_collectors_are_mapped():
    """지표가 쓰는 모든 수집기 이름이 매핑에 있어야 한다."""
    referenced = {cpo.DEFAULT_COLLECTOR, *cpo.CONTROL_COLLECTORS}
    unmapped = referenced - set(cpo.COLLECTOR_WORKFLOWS)
    assert not unmapped, (
        f"매핑되지 않은 수집기: {sorted(unmapped)}. `COLLECTOR_WORKFLOWS` 에 추가하세요 — "
        "빠지면 그 수집기의 실행당 커밋 지표가 조용히 사라집니다."
    )


def test_workflow_for_uses_mapping_not_fstring():
    """`f"collect-{name}.yml"` 조립이면 crypto 에서 틀린다."""
    assert cpo.workflow_for("crypto") == "collect-crypto-news.yml"
    assert cpo.workflow_for("social") == "collect-social-media.yml"
    assert cpo.workflow_for("political") == "collect-political-trades.yml"


def test_workflow_for_unknown_collector_is_none():
    """모르는 수집기에 파일명을 지어내면 gh 가 조용히 실패한다."""
    assert cpo.workflow_for("no-such-collector") is None


# ---------------------------------------------------------------------------
# 플래그 판독 — non-vacuity 먼저
# ---------------------------------------------------------------------------


def test_pilot_target_flag_is_actually_on():
    """파일럿 대상에 플래그가 켜져 있어야 한다.

    이 단언이 오염 가드의 non-vacuity 를 떠받친다. `pilot_enabled_collectors()` 가
    항상 빈 집합을 돌려주는 버그가 있으면 오염 가드는 통과하지만 이 테스트는 red 다.
    """
    enabled = cpo.pilot_enabled_collectors()
    assert enabled is not None, "워크플로우에서 파일럿 플래그를 읽지 못했다"
    assert cpo.DEFAULT_COLLECTOR in enabled, (
        f"파일럿 대상 {cpo.DEFAULT_COLLECTOR!r} 에 skip-noop-state-commits 가 켜져 있지 않다. "
        f"켜진 수집기: {sorted(enabled)}. 파일럿이 꺼졌다면 관측 지표 전체가 무의미하다."
    )


def test_control_group_excludes_pilot_enabled_collectors():
    """대조군에 파일럿이 켜진 수집기가 있으면 분모도 함께 줄어 절감이 과소평가된다."""
    enabled = cpo.pilot_enabled_collectors()
    assert enabled is not None
    contaminated = set(cpo.CONTROL_COLLECTORS) & enabled
    assert not contaminated, (
        f"대조군이 오염됐다: {sorted(contaminated)}. 이 수집기들은 파일럿이 켜져 있으므로 "
        "`CONTROL_COLLECTORS` 에서 빼야 합니다. 안 빼면 분자와 분모가 같이 줄어 "
        "절감이 실제보다 작게 나옵니다."
    )


def test_control_group_is_not_empty():
    """대조군이 비면 `[4]` 의 대조군 비가 분모 0으로 조용히 소멸한다.

    오염 가드만으로는 이걸 못 잡는다 — 파일럿을 6개 전부로 확대하면서
    `CONTROL_COLLECTORS` 를 빈 튜플로 만들면 오염은 0이 되고(공집합) 가드는 통과한다.
    그런데 결과는 지표가 사라지는 것이지 에러가 아니다. 확대의 대가를 치르려면
    명시적으로 이 가드를 고쳐야 한다.

    2026-08-12 실측 기준 대조군 후보는 political·geopolitical 둘뿐이다. 나머지 7개
    수집기는 최근 창에서 no-op 커밋이 0건이라 파일럿에 반응할 수 없다.
    """
    assert cpo.CONTROL_COLLECTORS, (
        "`CONTROL_COLLECTORS` 가 비었다 — 대조군 비의 분모가 0이 되어 지표가 소멸한다. "
        "파일럿을 남은 수집기까지 확대했다면 그 지표를 버린다는 결정을 코드와 설계 문서에 "
        "함께 남겨야 한다."
    )


def test_every_mapped_collector_is_either_pilot_or_control():
    """매핑된 수집기는 파일럿이거나 대조군이어야 한다 — 제3의 상태가 없어야 한다.

    확대 후의 조용한 실패를 잡는다. crypto 의 `skip-noop-state-commits` 가 리베이스나
    워크플로우 정리에서 되돌아가면 그 수집기는 파일럿에서 빠지는데, 대조군에도 없으므로
    어느 지표에도 나타나지 않는다. 커밋이 다시 늘어나도 도구는 조용하다.

    상보성으로 단언하면 확대할 때마다 테스트를 고칠 필요가 없다 — 옮긴 이름이 한쪽에서
    빠지고 다른 쪽에 들어가면 그대로 통과한다.
    """
    enabled = cpo.pilot_enabled_collectors()
    assert enabled is not None, "워크플로우에서 파일럿 플래그를 읽지 못했다"

    mapped = set(cpo.COLLECTOR_WORKFLOWS)
    control = set(cpo.CONTROL_COLLECTORS)
    orphans = mapped - enabled - control
    assert not orphans, (
        f"파일럿도 대조군도 아닌 수집기: {sorted(orphans)}. 플래그가 되돌아갔거나 "
        "`CONTROL_COLLECTORS` 에서 빠뜨렸습니다. 어느 쪽이든 이 수집기는 지표에 "
        "나타나지 않습니다."
    )


# ---------------------------------------------------------------------------
# 플래그 파서 양방향
# ---------------------------------------------------------------------------


def test_flag_parser_reads_true(tmp_path, monkeypatch):
    wf = tmp_path / "collect-fake.yml"
    wf.write_text("        with:\n          skip-noop-state-commits: 'true'\n", encoding="utf-8")
    monkeypatch.setattr(cpo, "WORKFLOWS_DIR", tmp_path)
    monkeypatch.setattr(cpo, "COLLECTOR_WORKFLOWS", {"fake": "collect-fake.yml"})
    assert cpo.pilot_enabled_collectors() == frozenset({"fake"})


def test_flag_parser_reads_false(tmp_path, monkeypatch):
    wf = tmp_path / "collect-fake.yml"
    wf.write_text("        with:\n          skip-noop-state-commits: 'false'\n", encoding="utf-8")
    monkeypatch.setattr(cpo, "WORKFLOWS_DIR", tmp_path)
    monkeypatch.setattr(cpo, "COLLECTOR_WORKFLOWS", {"fake": "collect-fake.yml"})
    assert cpo.pilot_enabled_collectors() == frozenset()


def test_flag_parser_treats_absence_as_off(tmp_path, monkeypatch):
    wf = tmp_path / "collect-fake.yml"
    wf.write_text("        with:\n          python-version: '3.13'\n", encoding="utf-8")
    monkeypatch.setattr(cpo, "WORKFLOWS_DIR", tmp_path)
    monkeypatch.setattr(cpo, "COLLECTOR_WORKFLOWS", {"fake": "collect-fake.yml"})
    assert cpo.pilot_enabled_collectors() == frozenset()


def test_flag_parser_accepts_unquoted_true(tmp_path, monkeypatch):
    """YAML 은 `true` 도 `'true'` 도 허용한다 — 인용부호만 보면 놓친다."""
    wf = tmp_path / "collect-fake.yml"
    wf.write_text("        with:\n          skip-noop-state-commits: true\n", encoding="utf-8")
    monkeypatch.setattr(cpo, "WORKFLOWS_DIR", tmp_path)
    monkeypatch.setattr(cpo, "COLLECTOR_WORKFLOWS", {"fake": "collect-fake.yml"})
    assert cpo.pilot_enabled_collectors() == frozenset({"fake"})


def test_flag_parser_fails_closed_when_workflow_unreadable(tmp_path, monkeypatch):
    """못 읽은 워크플로우를 '꺼짐' 으로 치면 오염을 놓친다 — 판정을 보류해야 한다."""
    monkeypatch.setattr(cpo, "WORKFLOWS_DIR", tmp_path)
    monkeypatch.setattr(cpo, "COLLECTOR_WORKFLOWS", {"fake": "collect-missing.yml"})
    assert cpo.pilot_enabled_collectors() is None


# ---------------------------------------------------------------------------
# 런타임 경고 — 테스트만이 아니라 도구 자신도 오염을 알린다
# ---------------------------------------------------------------------------


def test_report_load_adjusted_warns_when_target_is_in_its_own_control(monkeypatch, caplog):
    """`--collector crypto` 는 대조군에 자기 자신을 넣는다 — 분모가 분자를 포함한다.

    가드 테스트는 기본 대상(`regulatory`)만 검사하므로 CLI 오버라이드는 런타임에서
    잡아야 한다. 실제로 `--collector crypto` 로 돌렸을 때(crypto 가 아직 대조군이던
    2026-08-12 이전) 대조군 비 분모 29건에 crypto 자신의 9건이 들어가 있었다.

    `CONTROL_COLLECTORS` 를 monkeypatch 하는 것은 이 테스트가 **경고 코드의 동작**을
    보기 때문이다. production 상수를 그대로 읽으면 확대할 때마다(대조군에서 이름이
    빠질 때마다) 이 테스트가 무관하게 red 가 된다 — 실제로 1차 확대에서 그렇게 깨졌다.
    """
    monkeypatch.setattr(cpo, "commit_log", lambda _days: "")
    monkeypatch.setattr(cpo, "collect_run_timestamps", lambda _wf, limit: ([], "테스트"))
    monkeypatch.setattr(cpo, "pilot_enabled_collectors", lambda: frozenset({"regulatory"}))
    monkeypatch.setattr(cpo, "CONTROL_COLLECTORS", ("political", "geopolitical"))

    from datetime import datetime, timedelta, timezone

    kst = timezone(timedelta(hours=9))
    pilot = datetime(2026, 8, 10, 13, 14, 51, tzinfo=kst)

    with caplog.at_level("WARNING"):
        cpo.report_load_adjusted(["political"], 7, {"political": pilot}, datetime(2026, 8, 20, 0, 0, tzinfo=kst))

    messages = [r.getMessage() for r in caplog.records]
    assert any("자기 자신" in m or "자기참조" in m for m in messages), f"자기참조 경고가 없다: {messages}"


def test_report_load_adjusted_warns_on_contaminated_control(monkeypatch, caplog):
    """대조군에 파일럿이 켜진 이름이 남아 있으면 도구 자신이 경고해야 한다.

    위와 같은 이유로 `CONTROL_COLLECTORS` 를 고정한다 — 오염된 상태를 테스트가 직접
    만들어야지, production 상수가 우연히 오염돼 있기를 기대하면 안 된다.
    """
    monkeypatch.setattr(cpo, "commit_log", lambda _days: "")
    monkeypatch.setattr(cpo, "collect_run_timestamps", lambda _wf, limit: ([], "테스트"))
    monkeypatch.setattr(cpo, "pilot_enabled_collectors", lambda: frozenset({"regulatory", "political"}))
    monkeypatch.setattr(cpo, "CONTROL_COLLECTORS", ("political", "geopolitical"))

    from datetime import datetime, timedelta, timezone

    kst = timezone(timedelta(hours=9))
    pilot = datetime(2026, 8, 10, 13, 14, 51, tzinfo=kst)

    with caplog.at_level("WARNING"):
        cpo.report_load_adjusted(["regulatory"], 7, {"regulatory": pilot}, datetime(2026, 8, 20, 0, 0, tzinfo=kst))

    assert any("오염" in r.message or "political" in str(r.args) for r in caplog.records), (
        f"오염 경고가 없다. 기록된 경고: {[r.getMessage() for r in caplog.records]}"
    )
