"""tests/test_verify_action_pins.py — verify_action_pins 단위 테스트.

이 모듈은 0% 커버리지였다. 오프라인 가드 두 개(핀이 40-hex 인가, 라벨이 있는가)가
못 보는 것을 보는 유일한 도구라 — SHA 가 라벨이 주장하는 버전이 **실제로** 맞는지 —
조용히 깨지면 잘못된 `# vX` 라벨이 리뷰를 통과한다.

네트워크는 절대 타지 않는다. `_api` 자체를 검증할 때만 `urlopen` 을 가짜로 바꾸고,
그 위층은 `_api` 를 통째로 대체한다. `WORKFLOWS_DIR`/`ACTIONS_DIR` 는 프로덕션
상수이므로 monkeypatch 로 tmp 를 주입한다.
"""

from __future__ import annotations

import io
import json
import urllib.error

import pytest
import verify_action_pins as vap

SHA_A = "a" * 40
SHA_B = "b" * 40
SHA_C = "c" * 40


def _pin(ref="actions/checkout", sha=SHA_A, label="v4"):
    return vap.Pin(ref=ref, sha=sha, label=label)


# ---------------------------------------------------------------------------
# Pin
# ---------------------------------------------------------------------------


class TestPin:
    def test_repo_is_owner_slash_name(self):
        assert _pin(ref="actions/checkout").repo == "actions/checkout"

    def test_repo_drops_sub_action_path(self):
        assert _pin(ref="actions/cache/restore").repo == "actions/cache"

    def test_repo_drops_deep_sub_path(self):
        assert _pin(ref="github/codeql-action/upload-sarif").repo == "github/codeql-action"

    def test_is_hashable_for_dedup(self):
        assert len({_pin(), _pin()}) == 1


# ---------------------------------------------------------------------------
# collect_pins
# ---------------------------------------------------------------------------


class TestCollectPins:
    @pytest.fixture
    def dirs(self, tmp_path, monkeypatch):
        workflows = tmp_path / "workflows"
        actions = tmp_path / "actions"
        workflows.mkdir()
        actions.mkdir()
        monkeypatch.setattr(vap, "WORKFLOWS_DIR", workflows)
        monkeypatch.setattr(vap, "ACTIONS_DIR", actions)
        return workflows, actions

    def test_parses_ref_sha_and_label(self, dirs):
        workflows, _ = dirs
        (workflows / "a.yml").write_text(f"      - uses: actions/checkout@{SHA_A}  # v4\n", encoding="utf-8")

        assert vap.collect_pins() == [vap.Pin(ref="actions/checkout", sha=SHA_A, label="v4")]

    def test_label_is_optional(self, dirs):
        workflows, _ = dirs
        (workflows / "a.yml").write_text(f"      - uses: actions/checkout@{SHA_A}\n", encoding="utf-8")

        assert vap.collect_pins()[0].label is None

    def test_skips_local_actions(self, dirs):
        workflows, _ = dirs
        (workflows / "a.yml").write_text(
            f"      - uses: ./.github/actions/x@{SHA_A}  # v1\n      - uses: actions/checkout@{SHA_B}  # v4\n",
            encoding="utf-8",
        )

        assert [p.ref for p in vap.collect_pins()] == ["actions/checkout"]

    def test_ignores_non_sha_refs(self, dirs):
        """40-hex 가 아닌 태그 핀은 이 도구의 대상이 아니다(별도 가드가 잡는다)."""
        workflows, _ = dirs
        (workflows / "a.yml").write_text("      - uses: actions/checkout@v4\n", encoding="utf-8")

        assert vap.collect_pins() == []

    def test_ignores_prose_mentioning_uses(self, dirs):
        """앵커가 YAML 키에 걸려 있어 주석 산문은 매칭되면 안 된다."""
        workflows, _ = dirs
        (workflows / "a.yml").write_text(
            f"# this workflow uses: actions/checkout@{SHA_A}  # v4\n",
            encoding="utf-8",
        )

        assert vap.collect_pins() == []

    def test_scans_composite_action_files(self, dirs):
        _, actions = dirs
        sub = actions / "python-collect"
        sub.mkdir()
        (sub / "action.yml").write_text(f"    - uses: actions/setup-python@{SHA_B}  # v7\n", encoding="utf-8")

        assert [p.ref for p in vap.collect_pins()] == ["actions/setup-python"]

    def test_deduplicates_identical_pins_across_files(self, dirs):
        workflows, _ = dirs
        line = f"      - uses: actions/checkout@{SHA_A}  # v4\n"
        (workflows / "a.yml").write_text(line, encoding="utf-8")
        (workflows / "b.yml").write_text(line, encoding="utf-8")

        assert len(vap.collect_pins()) == 1

    def test_same_sha_with_conflicting_labels_stays_two_pins(self, dirs):
        """라벨이 엇갈리면 둘 다 보고돼야 한다 — 하나로 접으면 모순이 숨는다."""
        workflows, _ = dirs
        (workflows / "a.yml").write_text(
            f"      - uses: actions/checkout@{SHA_A}  # v4\n      - uses: actions/checkout@{SHA_A}  # v6\n",
            encoding="utf-8",
        )

        assert [p.label for p in vap.collect_pins()] == ["v4", "v6"]

    def test_result_is_sorted_deterministically(self, dirs):
        workflows, _ = dirs
        (workflows / "a.yml").write_text(
            f"      - uses: zzz/last@{SHA_A}  # v1\n      - uses: aaa/first@{SHA_B}  # v2\n",
            encoding="utf-8",
        )

        assert [p.ref for p in vap.collect_pins()] == ["aaa/first", "zzz/last"]

    def test_empty_dirs_yield_no_pins(self, dirs):
        assert vap.collect_pins() == []


# ---------------------------------------------------------------------------
# _segment / _repo_path
# ---------------------------------------------------------------------------


class TestSegmentEncoding:
    def test_plain_value_is_unchanged(self):
        assert vap._segment("v5.0.5") == "v5.0.5"

    def test_slash_is_encoded(self):
        assert vap._segment("a/b") == "a%2Fb"

    def test_query_delimiters_are_encoded(self):
        assert vap._segment("v1?x=1") == "v1%3Fx%3D1"
        assert vap._segment("v1#frag") == "v1%23frag"

    def test_dots_survive_encoding(self):
        """`..` 는 unreserved 라 여기서 막히지 않는다 — `_api` 가 막는다."""
        assert vap._segment("..") == ".."

    def test_repo_path_keeps_the_separating_slash(self):
        assert vap._repo_path("actions/checkout") == "actions/checkout"

    def test_repo_path_encodes_within_each_half(self):
        assert vap._repo_path("own er/che?kout") == "own%20er/che%3Fkout"


# ---------------------------------------------------------------------------
# _api
# ---------------------------------------------------------------------------


class _FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False


class TestApi:
    @pytest.fixture
    def captured(self, monkeypatch):
        """urlopen 을 가로채 요청 객체를 기록하고 고정 payload 를 돌려준다."""
        seen: dict[str, object] = {}

        def fake_urlopen(request, timeout=None):
            seen["request"] = request
            seen["timeout"] = timeout
            return _FakeResponse(json.dumps({"ok": True}).encode())

        monkeypatch.setattr(vap.urllib.request, "urlopen", fake_urlopen)
        return seen

    def test_returns_decoded_json(self, captured):
        assert vap._api("/repos/actions/checkout/tags") == {"ok": True}

    def test_uses_the_repo_timeout_convention(self, captured):
        vap._api("/repos/actions/checkout/tags")
        assert captured["timeout"] == vap.REQUEST_TIMEOUT == 15

    def test_sends_api_version_and_user_agent(self, captured):
        vap._api("/x")
        headers = captured["request"].headers
        assert headers["Accept"] == "application/vnd.github+json"
        assert headers["X-github-api-version"] == "2022-11-28"
        assert headers["User-agent"] == "investing-verify-action-pins"

    def test_omits_authorization_without_a_token(self, captured, monkeypatch):
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        monkeypatch.delenv("GH_TOKEN", raising=False)
        vap._api("/x")
        assert "Authorization" not in captured["request"].headers

    def test_sends_bearer_token_when_present(self, captured, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "token-placeholder")
        vap._api("/x")
        assert captured["request"].headers["Authorization"] == "Bearer token-placeholder"

    def test_falls_back_to_gh_token(self, captured, monkeypatch):
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        monkeypatch.setenv("GH_TOKEN", "alt-placeholder")
        vap._api("/x")
        assert captured["request"].headers["Authorization"] == "Bearer alt-placeholder"

    @pytest.mark.parametrize("code", [404, 422])
    def test_absent_object_becomes_none(self, monkeypatch, code):
        def raising(request, timeout=None):
            raise urllib.error.HTTPError("u", code, "gone", {}, None)

        monkeypatch.setattr(vap.urllib.request, "urlopen", raising)
        assert vap._api("/x") is None

    @pytest.mark.parametrize("code", [403, 500])
    def test_other_http_errors_propagate(self, monkeypatch, code):
        """레이트리밋(403)·서버오류(500)를 None 으로 삼키면 '태그 없음' 으로 위장한다."""

        def raising(request, timeout=None):
            raise urllib.error.HTTPError("u", code, "boom", {}, None)

        monkeypatch.setattr(vap.urllib.request, "urlopen", raising)
        with pytest.raises(urllib.error.HTTPError):
            vap._api("/x")


class TestApiRefusesOffHostAndTraversal:
    @pytest.fixture(autouse=True)
    def _no_network(self, monkeypatch):
        monkeypatch.setattr(
            vap.urllib.request,
            "urlopen",
            lambda *a, **k: pytest.fail("거부돼야 할 URL 이 실제로 요청됐다"),
        )

    def test_rejects_userinfo_host_splice(self, monkeypatch):
        monkeypatch.setattr(vap, "API_ROOT", "https://api.github.com@evil.example.com")
        with pytest.raises(ValueError, match="off-host"):
            vap._api("/x")

    def test_rejects_suffix_host_splice(self, monkeypatch):
        monkeypatch.setattr(vap, "API_ROOT", "https://api.github.com.evil.example.com")
        with pytest.raises(ValueError, match="off-host"):
            vap._api("/x")

    def test_rejects_non_https_scheme(self, monkeypatch):
        monkeypatch.setattr(vap, "API_ROOT", "http://api.github.com")
        with pytest.raises(ValueError, match="off-host"):
            vap._api("/x")

    def test_rejects_path_traversal(self):
        with pytest.raises(ValueError, match="traversing"):
            vap._api("/repos/../../secret")


# ---------------------------------------------------------------------------
# version_parts / labels_compatible
# ---------------------------------------------------------------------------


class TestVersionParts:
    @pytest.mark.parametrize(
        ("label", "expected"),
        [
            ("v5", (5,)),
            ("V5", (5,)),
            ("5", (5,)),
            ("v5.0.5", (5, 0, 5)),
            ("v10.20.30", (10, 20, 30)),
        ],
    )
    def test_parses_dotted_numerics(self, label, expected):
        assert vap.version_parts(label) == expected

    @pytest.mark.parametrize("label", ["codeql-bundle-v2", "v", "", "v1.2.x", "latest", "v1..2"])
    def test_non_numeric_tags_are_none(self, label):
        assert vap.version_parts(label) is None


class TestLabelsCompatible:
    def test_identical_labels_match(self):
        assert vap.labels_compatible("v5", "v5")

    def test_floating_major_accepts_concrete_patch(self):
        assert vap.labels_compatible("v5", "v5.0.5")

    def test_order_does_not_matter(self):
        assert vap.labels_compatible("v5.0.5", "v5")

    def test_different_major_is_incompatible(self):
        assert not vap.labels_compatible("v4", "v6.0.2")

    def test_different_minor_is_incompatible(self):
        assert not vap.labels_compatible("v5.1", "v5.0.5")

    def test_non_numeric_tags_compare_exactly(self):
        assert vap.labels_compatible("codeql-bundle-v2", "codeql-bundle-v2")
        assert not vap.labels_compatible("codeql-bundle-v2", "codeql-bundle-v3")

    def test_numeric_against_non_numeric_is_incompatible(self):
        assert not vap.labels_compatible("v5", "codeql-bundle-v5")


# ---------------------------------------------------------------------------
# _deref_to_commit
# ---------------------------------------------------------------------------


def _stub_api(monkeypatch, routes: dict[str, object]):
    """`_api` 를 경로->payload 표로 대체한다. 미등록 경로는 None(=404)."""
    calls: list[str] = []

    def fake(path: str):
        calls.append(path)
        return routes.get(path)

    monkeypatch.setattr(vap, "_api", fake)
    return calls


class TestDerefToCommit:
    def test_commit_type_is_returned_as_is(self, monkeypatch):
        calls = _stub_api(monkeypatch, {})
        assert vap._deref_to_commit("actions/checkout", SHA_A, "commit") == SHA_A
        assert calls == [], "commit 이면 API 를 부를 필요가 없다"

    def test_tag_object_is_unwrapped_one_layer(self, monkeypatch):
        _stub_api(
            monkeypatch,
            {f"/repos/actions/checkout/git/tags/{SHA_A}": {"object": {"sha": SHA_B}}},
        )
        assert vap._deref_to_commit("actions/checkout", SHA_A, "tag") == SHA_B

    def test_missing_tag_object_yields_none(self, monkeypatch):
        _stub_api(monkeypatch, {})
        assert vap._deref_to_commit("actions/checkout", SHA_A, "tag") is None

    def test_tag_without_object_yields_none(self, monkeypatch):
        _stub_api(monkeypatch, {f"/repos/actions/checkout/git/tags/{SHA_A}": {}})
        assert vap._deref_to_commit("actions/checkout", SHA_A, "tag") is None


# ---------------------------------------------------------------------------
# resolve_tag_names
# ---------------------------------------------------------------------------


class TestResolveTagNames:
    def test_annotated_tag_object_names_itself(self, monkeypatch):
        pin = _pin(ref="github/codeql-action/upload-sarif", sha=SHA_A, label="v4")
        calls = _stub_api(
            monkeypatch,
            {f"/repos/github/codeql-action/git/tags/{SHA_A}": {"tag": "v4"}},
        )

        assert vap.resolve_tag_names(pin) == ["v4"]
        assert len(calls) == 1, "태그 객체로 판정되면 matching-refs 를 부를 필요가 없다"

    def test_unlabeled_pin_stops_after_the_tag_lookup(self, monkeypatch):
        pin = _pin(label=None)
        _stub_api(monkeypatch, {})
        assert vap.resolve_tag_names(pin) == []

    def test_commit_pinned_directly_at_tag_object_sha(self, monkeypatch):
        pin = _pin(sha=SHA_A, label="v4")
        _stub_api(
            monkeypatch,
            {
                "/repos/actions/checkout/git/matching-refs/tags/v4": [
                    {"ref": "refs/tags/v4.1.0", "object": {"sha": SHA_A, "type": "tag"}}
                ]
            },
        )
        assert vap.resolve_tag_names(pin) == ["v4.1.0"]

    def test_commit_reached_by_dereferencing_the_tag(self, monkeypatch):
        pin = _pin(sha=SHA_A, label="v4")
        _stub_api(
            monkeypatch,
            {
                "/repos/actions/checkout/git/matching-refs/tags/v4": [
                    {"ref": "refs/tags/v4.1.0", "object": {"sha": SHA_B, "type": "tag"}}
                ],
                f"/repos/actions/checkout/git/tags/{SHA_B}": {"object": {"sha": SHA_A}},
            },
        )
        assert vap.resolve_tag_names(pin) == ["v4.1.0"]

    def test_unrelated_tags_are_excluded(self, monkeypatch):
        pin = _pin(sha=SHA_A, label="v4")
        _stub_api(
            monkeypatch,
            {
                "/repos/actions/checkout/git/matching-refs/tags/v4": [
                    {"ref": "refs/tags/v4.0.0", "object": {"sha": SHA_C, "type": "commit"}}
                ]
            },
        )
        assert vap.resolve_tag_names(pin) == []

    def test_ref_without_a_name_is_skipped(self, monkeypatch):
        pin = _pin(sha=SHA_A, label="v4")
        _stub_api(
            monkeypatch,
            {"/repos/actions/checkout/git/matching-refs/tags/v4": [{"ref": "", "object": {"sha": SHA_A}}]},
        )
        assert vap.resolve_tag_names(pin) == []

    def test_non_list_matching_refs_yields_empty(self, monkeypatch):
        pin = _pin(sha=SHA_A, label="v4")
        _stub_api(monkeypatch, {"/repos/actions/checkout/git/matching-refs/tags/v4": {"message": "Not Found"}})
        assert vap.resolve_tag_names(pin) == []

    def test_label_is_percent_encoded_in_the_url(self, monkeypatch):
        pin = _pin(sha=SHA_A, label="v4?x")
        calls = _stub_api(monkeypatch, {})
        vap.resolve_tag_names(pin)
        assert any("matching-refs/tags/v4%3Fx" in c for c in calls)


# ---------------------------------------------------------------------------
# reverse_lookup_tags
# ---------------------------------------------------------------------------


class TestReverseLookupTags:
    def test_finds_the_tag_naming_the_sha(self, monkeypatch):
        pin = _pin(sha=SHA_A, label="v4")
        _stub_api(
            monkeypatch,
            {"/repos/actions/checkout/tags?per_page=100&page=1": [{"name": "v6.0.2", "commit": {"sha": SHA_A}}]},
        )
        assert vap.reverse_lookup_tags(pin) == ["v6.0.2"]

    def test_stops_at_the_first_empty_page(self, monkeypatch):
        pin = _pin(sha=SHA_A)
        calls = _stub_api(monkeypatch, {"/repos/actions/checkout/tags?per_page=100&page=1": []})
        assert vap.reverse_lookup_tags(pin) == []
        assert len(calls) == 1

    def test_paginates_up_to_the_declared_bound(self, monkeypatch):
        pin = _pin(sha=SHA_A)
        routes = {
            f"/repos/actions/checkout/tags?per_page=100&page={n}": [{"name": f"v{n}", "commit": {"sha": SHA_C}}]
            for n in range(1, vap._REVERSE_LOOKUP_PAGES + 2)
        }
        calls = _stub_api(monkeypatch, routes)

        vap.reverse_lookup_tags(pin)
        assert len(calls) == vap._REVERSE_LOOKUP_PAGES, (
            "역방향 조회는 최근 태그만 훑도록 페이지 수가 묶여 있다. 이 상한을 바꾸면 "
            "github/codeql-action 같은 저장소에서 호출 수가 폭증한다."
        )

    def test_collects_across_pages(self, monkeypatch):
        pin = _pin(sha=SHA_A)
        _stub_api(
            monkeypatch,
            {
                "/repos/actions/checkout/tags?per_page=100&page=1": [{"name": "v6", "commit": {"sha": SHA_A}}],
                "/repos/actions/checkout/tags?per_page=100&page=2": [{"name": "v6.0.2", "commit": {"sha": SHA_A}}],
                "/repos/actions/checkout/tags?per_page=100&page=3": [],
            },
        )
        assert vap.reverse_lookup_tags(pin) == ["v6", "v6.0.2"]

    def test_tags_without_a_name_are_skipped(self, monkeypatch):
        pin = _pin(sha=SHA_A)
        _stub_api(
            monkeypatch,
            {"/repos/actions/checkout/tags?per_page=100&page=1": [{"name": "", "commit": {"sha": SHA_A}}]},
        )
        assert vap.reverse_lookup_tags(pin) == []

    def test_non_list_payload_stops_the_scan(self, monkeypatch):
        pin = _pin(sha=SHA_A)
        calls = _stub_api(monkeypatch, {"/repos/actions/checkout/tags?per_page=100&page=1": {"message": "x"}})
        assert vap.reverse_lookup_tags(pin) == []
        assert len(calls) == 1


# ---------------------------------------------------------------------------
# verify
# ---------------------------------------------------------------------------


class TestVerify:
    def test_unlabeled_pin_is_no_label(self, monkeypatch):
        monkeypatch.setattr(vap, "resolve_tag_names", lambda _p: pytest.fail("라벨이 없으면 조회하지 않는다"))
        verdict, detail = vap.verify(_pin(label=None))
        assert verdict == "NO-LABEL"
        assert "nothing to verify" in detail

    def test_matching_tag_is_ok(self, monkeypatch):
        monkeypatch.setattr(vap, "resolve_tag_names", lambda _p: ["v4.1.0"])
        assert vap.verify(_pin(label="v4")) == ("OK", "v4.1.0")

    def test_multiple_matching_tags_are_all_reported(self, monkeypatch):
        monkeypatch.setattr(vap, "resolve_tag_names", lambda _p: ["v4", "v4.1.0"])
        verdict, detail = vap.verify(_pin(label="v4"))
        assert verdict == "OK"
        assert detail == "v4, v4.1.0"

    def test_incompatible_resolved_tag_is_mismatch(self, monkeypatch):
        monkeypatch.setattr(vap, "resolve_tag_names", lambda _p: ["v6.0.2"])
        monkeypatch.setattr(vap, "reverse_lookup_tags", lambda _p: pytest.fail("이미 이름을 알면 역방향 조회 불필요"))
        verdict, detail = vap.verify(_pin(label="v4"))
        assert verdict == "MISMATCH"
        assert "SHA is v6.0.2" in detail and "label claims v4" in detail

    def test_reverse_lookup_promotes_unverified_to_mismatch(self, monkeypatch):
        """라벨이 엉뚱한 메이저를 가리키면 라벨 기반 조회는 아무것도 못 찾는다."""
        monkeypatch.setattr(vap, "resolve_tag_names", lambda _p: [])
        monkeypatch.setattr(vap, "reverse_lookup_tags", lambda _p: ["v9.0.0"])
        verdict, detail = vap.verify(_pin(label="v7"))
        assert verdict == "MISMATCH"
        assert "SHA is v9.0.0" in detail

    def test_nothing_found_anywhere_is_unverified(self, monkeypatch):
        monkeypatch.setattr(vap, "resolve_tag_names", lambda _p: [])
        monkeypatch.setattr(vap, "reverse_lookup_tags", lambda _p: [])
        verdict, detail = vap.verify(_pin(label="v4"))
        assert verdict == "UNVERIFIED"
        assert "v4" in detail


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


class TestMain:
    @pytest.fixture(autouse=True)
    def _argv(self, monkeypatch):
        monkeypatch.setattr("sys.argv", ["verify_action_pins.py"])

    def test_no_pins_is_a_parser_failure_not_a_pass(self, monkeypatch):
        """핀이 0건이면 '전부 통과' 가 아니라 파서 고장이다 — green 으로 끝나면 안 된다."""
        monkeypatch.setattr(vap, "collect_pins", list)
        assert vap.main() == 1

    def test_all_ok_exits_zero(self, monkeypatch):
        monkeypatch.setattr(vap, "collect_pins", lambda: [_pin()])
        monkeypatch.setattr(vap, "verify", lambda _p: ("OK", "v4.1.0"))
        assert vap.main() == 0

    def test_mismatch_exits_one(self, monkeypatch):
        monkeypatch.setattr(vap, "collect_pins", lambda: [_pin()])
        monkeypatch.setattr(vap, "verify", lambda _p: ("MISMATCH", "SHA is v6"))
        assert vap.main() == 1

    @pytest.mark.parametrize("verdict", ["UNVERIFIED", "NO-LABEL"])
    def test_soft_verdicts_fail_by_default(self, monkeypatch, verdict):
        monkeypatch.setattr(vap, "collect_pins", lambda: [_pin()])
        monkeypatch.setattr(vap, "verify", lambda _p: (verdict, "x"))
        assert vap.main() == 1

    @pytest.mark.parametrize("verdict", ["UNVERIFIED", "NO-LABEL"])
    def test_allow_unverified_downgrades_soft_verdicts(self, monkeypatch, verdict):
        monkeypatch.setattr("sys.argv", ["verify_action_pins.py", "--allow-unverified"])
        monkeypatch.setattr(vap, "collect_pins", lambda: [_pin()])
        monkeypatch.setattr(vap, "verify", lambda _p: (verdict, "x"))
        assert vap.main() == 0

    def test_allow_unverified_still_fails_on_mismatch(self, monkeypatch):
        """소프트 판정만 완화한다 — 거짓 라벨은 어떤 플래그로도 통과하면 안 된다."""
        monkeypatch.setattr("sys.argv", ["verify_action_pins.py", "--allow-unverified"])
        monkeypatch.setattr(vap, "collect_pins", lambda: [_pin()])
        monkeypatch.setattr(vap, "verify", lambda _p: ("MISMATCH", "SHA is v6"))
        assert vap.main() == 1

    def test_mismatch_wins_when_mixed_with_ok(self, monkeypatch):
        pins = [_pin(ref="a/one"), _pin(ref="b/two")]
        verdicts = {"a/one": ("OK", "v4"), "b/two": ("MISMATCH", "SHA is v6")}
        monkeypatch.setattr(vap, "collect_pins", lambda: pins)
        monkeypatch.setattr(vap, "verify", lambda p: verdicts[p.ref])
        assert vap.main() == 1
