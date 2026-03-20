from pathlib import Path
import sys


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from verify_rendered_posts import _validate_target  # noqa: E402


class TestValidateTarget:
    def test_worldmonitor_card_layout_is_accepted_without_table(self):
        target = {
            "glob": "*daily-worldmonitor-briefing*.md",
            "must_table": False,
            "must_details": True,
            "required_any": [[r"<table", r"wm-issue-list"]],
            "forbid": [],
        }
        html = '<div class="wm-issue-list"></div><details>refs</details>'

        assert _validate_target(target, "worldmonitor.html", html) == []

    def test_missing_required_any_pattern_fails(self):
        target = {
            "glob": "*daily-worldmonitor-briefing*.md",
            "must_table": False,
            "must_details": True,
            "required_any": [[r"<table", r"wm-issue-list"]],
            "forbid": [],
        }
        html = "<details>refs</details>"

        failures = _validate_target(target, "worldmonitor.html", html)
        assert any(f.startswith("missing-required-any:") for f in failures)
