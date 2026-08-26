"""tests/test_continuous_improvement_loop.py — continuous_improvement_loop 단위 테스트.

이 모듈은 0% 커버리지였다. 시간 스탬프를 제외하면 전부 순수 빌더/렌더러라
테스트 비용이 낮은데, 매시간 도는 개선 루프의 출력 형식을 정의한다 —
`_state/continuous-improvement-loop*.txt` 를 읽는 하류(Slack 게시)가 형식에
의존하므로 조용한 변경이 아프다.

격리 규칙: `POSTS_DIR`/`WORKFLOWS_DIR`/`ROOT` 는 프로덕션 상수라 import 하지 않고
monkeypatch 로 tmp 경로를 주입한다. `main()` 은 기본값이 `ROOT/_state/` 이므로
항상 명시 경로를 넘겨 저장소 트리에 쓰지 않게 한다.
"""

import continuous_improvement_loop as loop
import pytest


@pytest.fixture
def sample():
    items = loop.build_priorities(recent_posts=3, workflow_count=54)
    roles = loop.build_role_prompts(recent_posts=3, workflow_count=54)
    return items, roles


# ---------------------------------------------------------------------------
# count_recent_posts / count_workflows
# ---------------------------------------------------------------------------


class TestCountRecentPosts:
    def test_counts_only_markdown(self, tmp_path, monkeypatch):
        (tmp_path / "a.md").write_text("x", encoding="utf-8")
        (tmp_path / "b.md").write_text("x", encoding="utf-8")
        (tmp_path / "c.txt").write_text("x", encoding="utf-8")
        monkeypatch.setattr(loop, "POSTS_DIR", tmp_path)

        assert loop.count_recent_posts() == 2

    def test_excludes_posts_older_than_window(self, tmp_path, monkeypatch):
        import os
        import time

        fresh = tmp_path / "fresh.md"
        stale = tmp_path / "stale.md"
        fresh.write_text("x", encoding="utf-8")
        stale.write_text("x", encoding="utf-8")
        # 10일 전으로 mtime 을 밀어 창 밖으로 보낸다.
        old = time.time() - 10 * 24 * 3600
        os.utime(stale, (old, old))
        monkeypatch.setattr(loop, "POSTS_DIR", tmp_path)

        assert loop.count_recent_posts(days=2) == 1

    def test_days_argument_widens_window(self, tmp_path, monkeypatch):
        import os
        import time

        stale = tmp_path / "stale.md"
        stale.write_text("x", encoding="utf-8")
        old = time.time() - 5 * 24 * 3600
        os.utime(stale, (old, old))
        monkeypatch.setattr(loop, "POSTS_DIR", tmp_path)

        assert loop.count_recent_posts(days=2) == 0
        assert loop.count_recent_posts(days=30) == 1

    def test_empty_directory_returns_zero(self, tmp_path, monkeypatch):
        monkeypatch.setattr(loop, "POSTS_DIR", tmp_path)
        assert loop.count_recent_posts() == 0


class TestCountWorkflows:
    def test_counts_yml_only(self, tmp_path, monkeypatch):
        (tmp_path / "a.yml").write_text("x", encoding="utf-8")
        (tmp_path / "b.yml").write_text("x", encoding="utf-8")
        (tmp_path / "c.yaml").write_text("x", encoding="utf-8")
        (tmp_path / "d.md").write_text("x", encoding="utf-8")
        monkeypatch.setattr(loop, "WORKFLOWS_DIR", tmp_path)

        assert loop.count_workflows() == 2

    def test_empty_directory_returns_zero(self, tmp_path, monkeypatch):
        monkeypatch.setattr(loop, "WORKFLOWS_DIR", tmp_path)
        assert loop.count_workflows() == 0


# ---------------------------------------------------------------------------
# build_priorities / build_role_prompts
# ---------------------------------------------------------------------------


class TestBuildPriorities:
    def test_every_item_is_fully_populated(self, sample):
        items, _ = sample
        assert items, "우선순위가 비면 리포트가 빈 목록이 된다"
        for item in items:
            assert item.stage and item.priority and item.title and item.detail

    def test_covers_all_three_stages(self, sample):
        items, _ = sample
        assert {i.stage for i in items} == {
            "ULTRAWORKER_SCAN",
            "SISYPHUS_EXECUTE",
            "LOOP_VERIFY",
        }

    def test_priorities_are_ordered_p0_first(self, sample):
        items, _ = sample
        ranks = [int(i.priority[1:]) for i in items]
        assert ranks == sorted(ranks), (
            f"우선순위가 오름차순이 아니다: {ranks}. render_slack_message 가 앞의 4건만 "
            "보내므로 정렬이 깨지면 P0 가 Slack 에서 잘려 나간다."
        )

    def test_signals_are_embedded_in_verify_item(self):
        items = loop.build_priorities(recent_posts=7, workflow_count=54)
        verify = [i for i in items if i.stage == "LOOP_VERIFY"]
        assert len(verify) == 1
        assert "7" in verify[0].detail and "54" in verify[0].detail


class TestBuildRolePrompts:
    def test_role_names_are_unique(self, sample):
        _, roles = sample
        names = [r.role for r in roles]
        assert len(names) == len(set(names)), f"역할 이름이 중복된다: {names}"

    def test_every_role_has_focus_and_prompts(self, sample):
        _, roles = sample
        for role in roles:
            assert role.focus, f"{role.role} 에 focus 가 없다"
            assert role.prompts, f"{role.role} 에 프롬프트가 없다"

    def test_covers_the_eight_documented_axes(self, sample):
        _, roles = sample
        # CLAUDE.md 의 "개선 포럼 축" 과 동기 — 축이 조용히 빠지면 그 관점이 매시간
        # 루프에서 통째로 사라진다.
        assert {r.role for r in roles} == {
            "ops",
            "security",
            "uiux",
            "monitoring",
            "performance",
            "code-quality",
            "content-quality",
            "design",
        }

    def test_signals_are_embedded_in_uiux_prompts(self):
        roles = loop.build_role_prompts(recent_posts=9, workflow_count=54)
        uiux = next(r for r in roles if r.role == "uiux")
        assert any("recent_posts_48h=9" in p and "workflows=54" in p for p in uiux.prompts)


# ---------------------------------------------------------------------------
# render_report
# ---------------------------------------------------------------------------


class TestRenderReport:
    def test_has_required_sections(self, sample):
        report = loop.render_report(*sample)
        for heading in (
            "# Continuous Improvement Loop Report",
            "## Priorities",
            "## Multi-Agent Forum",
            "## Execution Rules",
        ):
            assert heading in report, f"{heading!r} 섹션이 사라졌다"

    def test_lists_every_priority_item(self, sample):
        items, roles = sample
        report = loop.render_report(items, roles)
        for item in items:
            assert f"[{item.priority}] {item.stage} | {item.title}" in report

    def test_lists_every_role_and_prompt(self, sample):
        items, roles = sample
        report = loop.render_report(items, roles)
        for role in roles:
            assert f"role={role.role}" in report
            for prompt in role.prompts:
                assert prompt in report

    def test_ends_with_single_trailing_newline(self, sample):
        report = loop.render_report(*sample)
        assert report.endswith("\n") and not report.endswith("\n\n")

    def test_empty_inputs_still_render_skeleton(self):
        report = loop.render_report([], [])
        assert "## Priorities" in report and "## Execution Rules" in report


# ---------------------------------------------------------------------------
# render_slack_message / render_role_slack_messages
# ---------------------------------------------------------------------------


class TestRenderSlackMessage:
    def test_truncates_to_first_four_items(self, sample):
        items, roles = sample
        message = loop.render_slack_message(items, roles)
        assert items[4].title not in message, (
            "Slack 메시지는 앞 4건만 보낸다. 이 상한이 조용히 늘거나 줄면 게시 길이가 "
            "바뀐다 — 바꾼다면 이 단언도 함께 갱신할 것."
        )
        for item in items[:4]:
            assert item.title in message

    def test_includes_role_thread_list(self, sample):
        items, roles = sample
        message = loop.render_slack_message(items, roles)
        assert "role_threads:" in message
        for role in roles:
            assert role.role in message

    def test_omits_role_line_when_no_roles(self, sample):
        items, _ = sample
        message = loop.render_slack_message(items, [])
        assert "role_threads:" not in message

    def test_always_ends_with_next_step(self, sample):
        message = loop.render_slack_message(*sample)
        assert message.rstrip().endswith("execute highest P0 in current run and report evidence")


class TestRenderRoleSlackMessages:
    def test_one_message_per_role(self, sample):
        _, roles = sample
        messages = loop.render_role_slack_messages(roles, 3, 54)
        assert set(messages) == {r.role for r in roles}

    def test_message_carries_focus_signals_and_prompts(self, sample):
        _, roles = sample
        messages = loop.render_role_slack_messages(roles, 3, 54)
        ops = messages["ops"]
        assert ops.startswith("[multi-agent-forum] OPS forum")
        assert "recent_posts_48h=3, workflows=54" in ops
        for prompt in next(r for r in roles if r.role == "ops").prompts:
            assert prompt in ops

    def test_no_roles_yields_empty_mapping(self):
        assert loop.render_role_slack_messages([], 0, 0) == {}


class TestWriteRoleMessages:
    def test_creates_directory_and_files(self, tmp_path):
        target = tmp_path / "nested" / "dir"
        loop.write_role_messages(target, {"ops": "hello", "design": "world"})

        assert (target / "continuous-improvement-loop-ops.txt").read_text(encoding="utf-8") == "hello"
        assert (target / "continuous-improvement-loop-design.txt").read_text(encoding="utf-8") == "world"

    def test_overwrites_existing_file(self, tmp_path):
        loop.write_role_messages(tmp_path, {"ops": "first"})
        loop.write_role_messages(tmp_path, {"ops": "second"})
        assert (tmp_path / "continuous-improvement-loop-ops.txt").read_text(encoding="utf-8") == "second"


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


class TestMain:
    @pytest.fixture(autouse=True)
    def _isolate(self, tmp_path, monkeypatch):
        """저장소 트리 대신 tmp 를 보게 한다 — 기본 인자가 ROOT/_state 를 가리킨다."""
        posts = tmp_path / "_posts"
        workflows = tmp_path / "workflows"
        posts.mkdir()
        workflows.mkdir()
        (posts / "2026-08-26-x.md").write_text("x", encoding="utf-8")
        (workflows / "a.yml").write_text("x", encoding="utf-8")
        monkeypatch.setattr(loop, "POSTS_DIR", posts)
        monkeypatch.setattr(loop, "WORKFLOWS_DIR", workflows)

    def test_writes_report_and_slack_files(self, tmp_path, monkeypatch, capsys):
        report = tmp_path / "out" / "report.md"
        slack = tmp_path / "out" / "slack.txt"
        monkeypatch.setattr(
            "sys.argv",
            ["continuous_improvement_loop.py", "--report-path", str(report), "--slack-path", str(slack)],
        )

        assert loop.main() == 0

        assert "# Continuous Improvement Loop Report" in report.read_text(encoding="utf-8")
        assert "[ultrawork-loop]" in slack.read_text(encoding="utf-8")
        out = capsys.readouterr().out
        assert str(report) in out and str(slack) in out

    def test_role_slack_dir_is_opt_in(self, tmp_path, monkeypatch):
        report = tmp_path / "report.md"
        slack = tmp_path / "slack.txt"
        role_dir = tmp_path / "roles"
        monkeypatch.setattr(
            "sys.argv",
            ["continuous_improvement_loop.py", "--report-path", str(report), "--slack-path", str(slack)],
        )
        assert loop.main() == 0
        assert not role_dir.exists(), "--role-slack-dir 없이 역할 디렉토리가 생기면 안 된다"

    def test_role_slack_dir_emits_one_file_per_role(self, tmp_path, monkeypatch):
        report = tmp_path / "report.md"
        slack = tmp_path / "slack.txt"
        role_dir = tmp_path / "roles"
        monkeypatch.setattr(
            "sys.argv",
            [
                "continuous_improvement_loop.py",
                "--report-path",
                str(report),
                "--slack-path",
                str(slack),
                "--role-slack-dir",
                str(role_dir),
            ],
        )

        assert loop.main() == 0

        expected = {f"continuous-improvement-loop-{r.role}.txt" for r in loop.build_role_prompts(0, 0)}
        assert {p.name for p in role_dir.iterdir()} == expected
