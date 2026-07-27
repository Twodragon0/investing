"""tests/test_check_relative_imports.py — check_relative_imports 단위 테스트.

``scripts/common/`` 내부의 절대 ``scripts.*`` import(PR #773 회귀)를 AST로
탐지하는 pre-commit 훅. 정상/위반/읽기 오류/구문 오류 경로와 CLI 종료 코드를
결정적으로 구동한다.
"""

import check_relative_imports as cri

# ---------------------------------------------------------------------------
# _check_file
# ---------------------------------------------------------------------------


class TestCheckFile:
    def test_clean_file_has_no_violations(self, tmp_path):
        f = tmp_path / "clean.py"
        f.write_text("from .config import setup_logging\nimport os\n", encoding="utf-8")
        assert cri._check_file(str(f)) == []

    def test_detects_import_from_scripts(self, tmp_path):
        f = tmp_path / "bad.py"
        f.write_text("from scripts.common.config import x\n", encoding="utf-8")
        violations = cri._check_file(str(f))
        assert len(violations) == 1
        assert "from scripts.common.config import" in violations[0]

    def test_detects_plain_import_scripts(self, tmp_path):
        f = tmp_path / "bad2.py"
        f.write_text("import scripts.common.utils\n", encoding="utf-8")
        violations = cri._check_file(str(f))
        assert len(violations) == 1
        assert "import scripts.common.utils" in violations[0]

    def test_unreadable_file_reports_error(self, tmp_path):
        missing = tmp_path / "ghost.py"
        violations = cri._check_file(str(missing))
        assert len(violations) == 1
        assert "could not read file" in violations[0]

    def test_syntax_error_is_ignored(self, tmp_path):
        f = tmp_path / "broken.py"
        f.write_text("def (:\n", encoding="utf-8")  # invalid syntax
        assert cri._check_file(str(f)) == []

    def test_docstring_example_not_flagged(self, tmp_path):
        # docstring 안의 예시는 AST import 노드가 아니므로 위반 아님.
        f = tmp_path / "doc.py"
        f.write_text('"""example: from scripts.common.x import y"""\n', encoding="utf-8")
        assert cri._check_file(str(f)) == []


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


class TestMain:
    def test_clean_returns_0(self, tmp_path):
        f = tmp_path / "clean.py"
        f.write_text("from .config import x\n", encoding="utf-8")
        assert cri.main(["prog", str(f)]) == 0

    def test_violation_returns_1(self, tmp_path, capsys):
        f = tmp_path / "bad.py"
        f.write_text("from scripts.common.config import x\n", encoding="utf-8")
        assert cri.main(["prog", str(f)]) == 1
        err = capsys.readouterr().err
        assert "absolute 'scripts.*' imports found" in err
        assert "Fix: use relative imports" in err

    def test_no_files_returns_0(self):
        assert cri.main(["prog"]) == 0
