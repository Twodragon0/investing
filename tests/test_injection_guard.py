"""Regression guard: no CWE-94 (OWASP A03:2021 - Injection) code-injection sites
where a bash variable is interpolated DIRECTLY into a `python3 -c "..."` /
`python -c "..."` program body, or into an unquoted heredoc fed to a
code-executing interpreter.

## Ported from claudesec

This guard is a port of
`claudesec/scanner/tests/test_ci_no_code_injection_regression.py`, adapted to
scan investing's shell/workflow surface (`.claude/hooks/**/*.sh`,
`scripts/**/*.sh`, any other `*.sh`, and `.github/workflows/*.yml`/`*.yaml`)
instead of claudesec's `scanner/lib`/`scanner/checks`/`hooks` layout. It is
FULLY SELF-CONTAINED: `strip_comment_lines` (originally shared via
claudesec's `_ci_guard_util`, which does not exist in this repo) is inlined
below rather than imported.

## THE RISK

`python3 -c "... $VAR ... "` splices the shell variable's *text* into the
Python source before it is parsed. If that value can ever contain a quote,
backslash, or other Python-meaningful character (attacker-controlled input, a
path with unexpected characters, a stray `'` in upstream data), the
interpolation breaks out of its intended literal and executes as arbitrary
Python -- a classic CWE-94 code-injection bug, catalogued under OWASP
A03:2021 (Injection): https://owasp.org/Top10/A03_2021-Injection/. The safe
fix is to pass the value through `argv`, `stdin`, or the process ENVIRONMENT
(`VAR="$value" python3 -c "..."` + `os.environ['VAR']` inside the program) so
the `-c` argument text is a constant with no `$` in it.

`.claude/hooks/yaml-syntax-check.sh` was exactly this shape (`python3 -c
"import yaml,sys; yaml.safe_load(open('$FILE_PATH'))"`) until it was fixed on
investing's `main` (#1051) to pass the path as `argv` instead
(`... "$FILE_PATH"` after the `-c` program, read via `sys.argv[1]`). This
guard pins that fix as a regression baseline: `KNOWN_INJECTION_SITES` is the
empty `set()`, and any new interpolated site fails the guard immediately.

## Detection rule: "any unescaped `$`"

Inside a bash double-quoted string, an unescaped `$` ALWAYS begins an
expansion -- there is no double-quoted context where a bare `$` is inert.
That covers not just the named/braced/command-substitution forms (`$NAME`,
`${...}`, `$(...)`) but every positional and special parameter too: `$1`..`$9`,
`$0`, `$@`, `$*`, `$#`, `$?`, `$$`, `$!`, `$-`. `has_unescaped_dollar`
implements this single rule; a backslash-escaped literal dollar sign is
correctly excluded.

## Regression-pin semantics

The computed violation set (`"relpath:construct"`, one entry per offending
site, `construct` being the sorted, comma-joined distinct `$`-expansions found
in that body) must EQUAL the baseline `KNOWN_INJECTION_SITES` -- currently the
empty `set()`. A NEW site fails the guard immediately (not silently
mergeable); shrinking the baseline without fixing the site would also fail
(keeps the allowlist honest). Adding an entry back to `KNOWN_INJECTION_SITES`
must be accompanied by a one-line justification comment.

## Unquoted-heredoc-into-interpreter

Beyond the `-c "..."` form, this guard ALSO covers an UNQUOTED heredoc whose
body is fed as the stdin PROGRAM of a code-executing interpreter (`python3
<<EOF`, `bash <<EOF`, `sh <<EOF`, `awk <<EOF`, `perl <<EOF`, `node <<EOF`,
`ruby <<EOF`; matched on the BASENAME of the command word). A bare (unquoted)
heredoc delimiter does NOT disable expansion, so any unescaped `$` in the
body is interpolated by bash into the interpreter's source before it runs --
same risk as the `-c "..."` form. A QUOTED delimiter (`<<'EOF'` / `<<"EOF"`)
is SAFE and not flagged. A heredoc feeding a NON-interpreter command (`cat`,
`tee`, `kubectl`, `gh api`, ...) is never flagged even if its body contains
`$`, because that body is DATA, not code the shell hands to an interpreter.

## Out of scope

* `python3 -c '...'` (SINGLE-quoted `-c` argument) is SAFE and NOT flagged.
* Values passed as `argv`, `stdin`, or the environment are the SAFE patterns
  this guard's fix moves callers toward, and are never flagged.
* `awk -v var=... '...'` and interpreter invocations not covered by the two
  forms above are OUT OF SCOPE.
* A `-c` argument built from adjacent CONCATENATED bash segments (quoted and
  unquoted back to back with no space) is covered on a best-effort basis by
  `find_concatenated_c_bodies` -- it does NOT content-check the UNQUOTED
  portions of a concatenated run.

stdlib-only. No repo-src import. No network, no subprocess. Runs under
pytest (this repo's CI runner).
"""

from __future__ import annotations

import re
from pathlib import Path

# tests/this_file -> parent.parent == repo root (tests/ is directly under
# repo root in investing).
REPO_ROOT = Path(__file__).resolve().parent.parent

# Directories never worth walking for shell/workflow scans.
_EXCLUDED_DIR_NAMES = {".git", "node_modules", "__pycache__", ".venv"}


def non_comment_lines(text: str) -> list:
    """The lines of `text` with whole-line `#` comments dropped."""
    return [line for line in text.splitlines() if not line.lstrip().startswith("#")]


def strip_comment_lines(text: str) -> str:
    """`text` with whole-line `#` comments removed, so a token living only in a
    comment cannot satisfy a presence check. Inlined from claudesec's shared
    `_ci_guard_util.strip_comment_lines` -- that module is claudesec-specific
    and does not exist in this repo."""
    return "\n".join(non_comment_lines(text))


# Matches a `python3 -c "..."` / `python -c "..."` invocation whose `-c`
# argument is DOUBLE-quoted, capturing the program text up to the matching
# unescaped closing `"`. re.DOTALL so the body can span multiple lines.
_PYC_RE = re.compile(r'python3?\s+-c\s+"((?:\\.|[^"\\])*)"', re.DOTALL)

# The ACTUAL violation condition: any `$` in the captured body that is NOT
# immediately preceded by a backslash.
_UNESCAPED_DOLLAR_RE = re.compile(r"(?<!\\)\$")

# Recognizable expansion TOKEN shapes, used only to render a readable
# `relpath:construct` string in the violation report -- NOT the detection
# condition (that is `_UNESCAPED_DOLLAR_RE`/`has_unescaped_dollar`, above).
_DOLLAR_TOKEN_RE = re.compile(r"(?<!\\)\$(?:\{[^}]*\}|\([^)]*\)|[A-Za-z_][A-Za-z0-9_]*|[0-9@*#?$!-])")

# Regression baseline. MUST be empty -- the one former site
# (`.claude/hooks/yaml-syntax-check.sh`) was already fixed on main (#1051)
# to pass the path via argv instead of interpolating it into the -c body.
KNOWN_INJECTION_SITES: set = set()


def find_double_quoted_c_bodies(text: str) -> list:
    """The captured program-body text of every double-quoted `python3 -c "..."`
    / `python -c "..."` site in `text`, in document order."""
    return _PYC_RE.findall(text)


def has_unescaped_dollar(body: str) -> bool:
    """True if `body` contains ANY unescaped `$` -- the actual violation
    condition. Subsumes named vars, `${...}`, `$(...)`, and every
    positional/special parameter in one rule."""
    return bool(_UNESCAPED_DOLLAR_RE.search(body))


def violating_constructs(body: str) -> list:
    """The recognizable `$`-expansion TOKENS found in one captured `-c`
    program body -- used only to render a human-readable `relpath:construct`
    report string. Does NOT decide whether the site is a violation."""
    return _DOLLAR_TOKEN_RE.findall(body)


# Safe shell-terminator characters: if a `-c` argument's closing `"` is
# immediately followed by one of these, the shell word/command genuinely ends
# there. Anything else glued on with no separating whitespace is bash
# CONCATENATING more text onto the same word.
_SAFE_TERMINATOR_CHARS = set(" \t\n|&;)<>`")


def _scan_quoted_segment(text: str, pos: int):
    """`text[pos]` must be an opening `"`. Returns `(body, end_pos)` where
    `body` is the escaped-aware content up to the matching unescaped closing
    `"`, and `end_pos` is the index just past that closing quote (or
    `len(text)` if the quote is unterminated)."""
    i = pos + 1
    n = len(text)
    buf = []
    while i < n:
        c = text[i]
        if c == "\\" and i + 1 < n:
            buf.append(text[i : i + 2])
            i += 2
            continue
        if c == '"':
            return "".join(buf), i + 1
        buf.append(c)
        i += 1
    return "".join(buf), i


def find_concatenated_c_bodies(text: str) -> list:
    """Concatenation-aware capture of `python3 -c "..."` argument bodies
    (best-effort). Identical to `find_double_quoted_c_bodies` when the `-c`
    argument is a single double-quoted segment; when the segment's closing
    `"` is immediately followed by a non-terminator character, keeps
    consuming directly-adjacent double-quoted segments and concatenates
    their bodies before returning."""
    results = []
    n = len(text)
    for m in _PYC_RE.finditer(text):
        bodies = [m.group(1)]
        pos = m.end()
        while pos < n and text[pos] not in _SAFE_TERMINATOR_CHARS:
            if text[pos] == '"':
                seg_body, pos = _scan_quoted_segment(text, pos)
                bodies.append(seg_body)
            else:
                start = pos
                while pos < n and text[pos] not in _SAFE_TERMINATOR_CHARS and text[pos] != '"':
                    pos += 1
                if pos == start:  # defensive: never spin without progress
                    break
        results.append("".join(bodies))
    return results


# Matches an heredoc OPENER: `<<DELIM`, `<<-DELIM`, `<<'DELIM'`, `<<"DELIM"`.
# Group 1 = the optional `-` (leading-tab-stripping form). Groups 2/3 = the
# delimiter when single-/double-quoted (SAFE -- expansion disabled). Group 4 =
# the delimiter when UNQUOTED (expansion active -- the risk this guard
# checks).
_HEREDOC_OPEN_RE = re.compile(
    r"<<(-?)\s*(?:'([A-Za-z_][A-Za-z0-9_]*)'|\"([A-Za-z_][A-Za-z0-9_]*)\"|([A-Za-z_][A-Za-z0-9_]*))"
)

# Interpreter allowlist for the heredoc check: commands that EXECUTE their
# stdin as code. Matched on the basename of the leading command word.
_HEREDOC_INTERPRETER_RE = re.compile(r"^(?:.*/)?(python3?|sh|bash|awk|perl|node|ruby)$")

# Assignment prefix (`VAR=`) on a command word.
_LEADING_ASSIGN_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")


def _strip_leading_noise(s: str) -> str:
    """Strip leading whitespace, `VAR=` assignment prefixes, quote chars
    (`"`/`'`), subshell/group openers (`$(`, `(`, `{`), and a standalone `!`
    (negation) -- repeatedly, in that priority order -- so that a command
    word glued directly onto one of these with no whitespace
    (`pyout="$(python3`) still resolves to the real leading command
    (`python3`), not the assignment/opener noise in front of it."""
    while True:
        stripped = s.lstrip()
        if stripped != s:
            s = stripped
            continue
        m = _LEADING_ASSIGN_RE.match(s)
        if m:
            s = s[m.end() :]
            continue
        if s[:2] == "$(":
            s = s[2:]
            continue
        if s[:1] in ("(", "{", '"', "'"):
            s = s[1:]
            continue
        if s[:1] == "!" and (len(s) == 1 or s[1].isspace()):
            s = s[1:]
            continue
        break
    return s


def _heredoc_owner_word(lines: list, idx: int, match) -> str:
    """The leading command word of the logical (backslash-continuation-joined)
    command line that owns the heredoc opener `match` found on `lines[idx]`."""
    start = idx
    while start > 0 and lines[start - 1].endswith("\\"):
        start -= 1
    parts = [lines[k][:-1] if lines[k].endswith("\\") else lines[k] for k in range(start, idx)]
    parts.append(lines[idx][: match.start()])
    joined = _strip_leading_noise(" ".join(parts).strip())
    return joined.split()[0] if joined else ""


def find_interpreter_heredoc_sites(text: str) -> list:
    """Every heredoc in `text` whose owning command is a code-executing
    INTERPRETER (see `_HEREDOC_INTERPRETER_RE`), quoted or unquoted. Returns a
    list of `(interpreter, quoted, body)` tuples in document order."""
    lines = text.splitlines()
    n = len(lines)
    sites = []
    i = 0
    while i < n:
        m = _HEREDOC_OPEN_RE.search(lines[i])
        if not m:
            i += 1
            continue
        dash = m.group(1) == "-"
        quoted = m.group(2) is not None or m.group(3) is not None
        delim = m.group(2) or m.group(3) or m.group(4)
        j = i + 1
        body_lines = []
        while j < n:
            candidate = lines[j].lstrip("\t") if dash else lines[j]
            if candidate == delim:
                break
            body_lines.append(lines[j])
            j += 1
        word = _heredoc_owner_word(lines, i, m)
        if _HEREDOC_INTERPRETER_RE.match(word):
            sites.append((word, quoted, "\n".join(body_lines)))
        i = j + 1
    return sites


def _production_files() -> list:
    """Every shell/workflow file this guard scans: all `*.sh` anywhere in the
    repo (covers `.claude/hooks/**/*.sh` and `scripts/**/*.sh` plus any other
    `*.sh`), and every `.github/workflows/*.yml` / `*.yaml`."""
    files = []
    for p in REPO_ROOT.rglob("*.sh"):
        if not any(part in _EXCLUDED_DIR_NAMES for part in p.relative_to(REPO_ROOT).parts):
            files.append(p)
    workflows_dir = REPO_ROOT / ".github" / "workflows"
    if workflows_dir.is_dir():
        files += sorted(workflows_dir.glob("*.yml"))
        files += sorted(workflows_dir.glob("*.yaml"))
    return sorted(files)


def compute_violations(files) -> tuple:
    """Returns (violations, total_sites) -- `violations` is the union of the
    `"relpath:construct"` (`python3 -c` sites, concatenation-aware) and
    `"relpath:heredoc:<interpreter>:construct"` (unquoted interpreter heredoc
    sites) violation sets; `total_sites` is the count of ALL double-quoted
    `python3 -c` sites scanned (violating or not), for the non-vacuity check."""
    violations: set = set()
    total_sites = 0
    for f in files:
        text = strip_comment_lines(Path(f).read_text(encoding="utf-8"))
        for body in find_concatenated_c_bodies(text):
            total_sites += 1
            if has_unescaped_dollar(body):
                rel = str(Path(f).resolve().relative_to(REPO_ROOT))
                tokens = violating_constructs(body)
                construct = ",".join(sorted(set(tokens))) if tokens else "$<unrecognized-shape>"
                violations.add(f"{rel}:{construct}")
        for interpreter, quoted, body in find_interpreter_heredoc_sites(text):
            if quoted:
                continue  # quoted delimiter disables expansion -- SAFE
            if has_unescaped_dollar(body):
                rel = str(Path(f).resolve().relative_to(REPO_ROOT))
                tokens = violating_constructs(body)
                construct = ",".join(sorted(set(tokens))) if tokens else "$<unrecognized-shape>"
                violations.add(f"{rel}:heredoc:{interpreter}:{construct}")
    return violations, total_sites


def _count_interpreter_heredoc_sites(files) -> int:
    """Count of ALL interpreter-owned heredoc sites (quoted + unquoted)
    across `files`, for the heredoc-scan non-vacuity canary."""
    total = 0
    for f in files:
        text = strip_comment_lines(Path(f).read_text(encoding="utf-8"))
        total += len(find_interpreter_heredoc_sites(text))
    return total


# -- Regression tests against the real repo corpus --------------------------


def test_scan_set_nonempty():
    # If no shell/workflow files were found, the path assumptions broke --
    # fail loudly rather than vacuously passing the injection scan below.
    files = _production_files()
    assert files, (
        "No shell/workflow files found to scan -- check the *.sh / "
        ".github/workflows path assumptions in _production_files()."
    )


def test_parsed_non_trivial_number_of_sites():
    # Canary: if the `-c "..."` regex/paths broke, this would silently find
    # zero sites and test_no_new_injection_site below would vacuously pass.
    # The live corpus has ~22 double-quoted `python3 -c "..."` sites (mostly
    # in .github/workflows/*.yml) as of this writing.
    _, total_sites = compute_violations(_production_files())
    assert total_sites > 10, (
        'Parsed suspiciously few `python3 -c "..."` sites across the repo '
        "-- the detection regex or file paths likely broke."
    )


def test_parsed_non_trivial_number_of_heredoc_sites():
    # Canary for the heredoc-extension machinery: if the heredoc-opener
    # regex or the interpreter allowlist broke, this would silently find
    # zero interpreter-owned heredocs (the repo has several QUOTED
    # `python3 - <<'PY'` sites in .github/workflows already) and
    # test_no_new_injection_site would vacuously pass on the heredoc half
    # of the check.
    count = _count_interpreter_heredoc_sites(_production_files())
    assert count > 0, (
        "Parsed zero interpreter-owned heredoc sites across the repo -- "
        "the heredoc opener regex or interpreter allowlist likely broke "
        "(expected to find the existing quoted `python3 - <<'PY'` sites in "
        ".github/workflows)."
    )


def test_no_new_injection_site():
    violations, _ = compute_violations(_production_files())
    new_violations = violations - KNOWN_INJECTION_SITES
    assert not new_violations, (
        "NEW CWE-94 code-injection site(s) -- a bash variable is "
        'interpolated directly into a `python3 -c "..."` program body '
        f"(OWASP A03:2021): {sorted(new_violations)}. Fix by passing the "
        "value through argv, stdin, or the environment "
        '(`VAR="$val" python3 -c "..."` + `os.environ[\'VAR\']` inside the '
        "program) instead of splicing `$VAR`/`${...}`/`$(...)` into the "
        "program text."
    )


def test_no_stale_allowlist_entry():
    violations, _ = compute_violations(_production_files())
    stale = KNOWN_INJECTION_SITES - violations
    assert not stale, (
        f"KNOWN_INJECTION_SITES lists site(s) that are no longer "
        f"violations: {sorted(stale)} (fixed, or file removed/changed). "
        "Drop them from KNOWN_INJECTION_SITES so the baseline stays honest."
    )


def test_real_repo_baseline_matches():
    violations, _ = compute_violations(_production_files())
    assert violations == KNOWN_INJECTION_SITES, (
        f"Live scan violations {sorted(violations)} do not match KNOWN_INJECTION_SITES {sorted(KNOWN_INJECTION_SITES)}."
    )


# -- Mutation self-tests: detector must FIRE on unsafe forms and stay QUIET
# -- on safe argv/env-var/single-quoted/quoted-heredoc forms. -------------


def test_fires_on_dollar_var():
    body = "\n".join(["import json, os", "print(open('$OUTPUT_DIR/f.json'))"])
    assert has_unescaped_dollar(body), "Mutation FAILED: a bare `$VAR` interpolation was not detected."


def test_fires_on_braced_var():
    body = "print('${CONTEXT}')"
    assert has_unescaped_dollar(body), "Mutation FAILED: a `${VAR}` interpolation was not detected."


def test_fires_on_command_substitution():
    body = "print('$(date)')"
    assert has_unescaped_dollar(body), "Mutation FAILED: a `$(...)` command substitution was not detected."


def test_fires_on_positional_param():
    body = "print('$1')"
    assert has_unescaped_dollar(body), "Mutation FAILED: positional parameter `$1` was not detected."


def test_fires_on_special_param_at():
    body = "print('$@')"
    assert has_unescaped_dollar(body), "Mutation FAILED: special parameter `$@` was not detected."


def test_quiet_on_escaped_dollar():
    body = "print('\\$5.00')"
    assert not has_unescaped_dollar(body), "False positive: an escaped `\\$` (literal dollar) was flagged."


def test_quiet_on_argv_read():
    # The documented-safe fix used by yaml-syntax-check.sh: the value is
    # passed as argv after the -c program, not interpolated into it.
    text = 'python3 -c "import yaml,sys; yaml.safe_load(open(sys.argv[1]))" "$FILE_PATH"'
    bodies = find_double_quoted_c_bodies(text)
    assert len(bodies) == 1
    assert not has_unescaped_dollar(bodies[0]), "False positive: an argv-passed value was flagged."


def test_quiet_on_env_var_read():
    body = "\n".join(["import json, os", "print(open(os.environ['OUTPUT_DIR']))"])
    assert not has_unescaped_dollar(body), "False positive: a body reading os.environ (the safe fix) was flagged."


def test_quiet_on_single_quoted_c_argument():
    text = "python3 -c 'import os; print(os.environ[\"X\"])' 2>/dev/null"
    assert find_double_quoted_c_bodies(text) == [], (
        "False positive: a single-quoted `-c` argument was captured as a double-quoted site."
    )


def test_multiline_double_quoted_body_captured():
    text = "python3 -c \"\nimport os\nprint(os.environ['X'])\n\" 2>/dev/null"
    bodies = find_double_quoted_c_bodies(text)
    assert len(bodies) == 1
    assert "import os" in bodies[0]


def test_comment_only_reference_does_not_flag():
    text = "\n".join(
        [
            "# see $OUTPUT_DIR for context, not interpolated below",
            "python3 -c \"import os; print(os.environ['OUTPUT_DIR'])\"",
        ]
    )
    stripped = strip_comment_lines(text)
    bodies = find_double_quoted_c_bodies(stripped)
    assert len(bodies) == 1
    assert not has_unescaped_dollar(bodies[0])


def test_heredoc_fires_on_unquoted_python():
    text = 'python3 <<EOF\nprint("$HOME")\nEOF\n'
    sites = find_interpreter_heredoc_sites(text)
    assert len(sites) == 1
    interpreter, quoted, body = sites[0]
    assert interpreter == "python3"
    assert not quoted
    assert has_unescaped_dollar(body), "Mutation FAILED: unquoted `python3 <<EOF` interpolating `$HOME` not detected."


def test_heredoc_fires_on_unquoted_bash():
    text = "bash <<EOF\nrm $TARGET\nEOF\n"
    sites = find_interpreter_heredoc_sites(text)
    assert len(sites) == 1
    interpreter, quoted, body = sites[0]
    assert interpreter == "bash"
    assert not quoted
    assert has_unescaped_dollar(body), "Mutation FAILED: unquoted `bash <<EOF` interpolating `$TARGET` not detected."


def test_heredoc_quiet_on_quoted_delimiter():
    text = "python3 <<'EOF'\nprint(\"$HOME\")\nEOF\n"
    sites = find_interpreter_heredoc_sites(text)
    assert len(sites) == 1
    _, quoted, _ = sites[0]
    assert quoted, "False positive risk: `<<'EOF'` (quoted delimiter) was not recognized as quoted."


def test_heredoc_quiet_on_data_into_file():
    text = "cat <<EOF > out.txt\n$HOME\nEOF\n"
    sites = find_interpreter_heredoc_sites(text)
    assert sites == [], "False positive: a `cat <<EOF > file` (data, non-interpreter) heredoc was flagged."


def test_heredoc_quiet_on_non_interpreter_command():
    text = "kubectl apply -f - <<EOF\n  name: $x\nEOF\n"
    sites = find_interpreter_heredoc_sites(text)
    assert sites == [], "False positive: `kubectl apply -f - <<EOF` (non-interpreter) heredoc was flagged."


def test_concatenation_fires_when_split_across_quoted_segments():
    text = 'python3 -c "a""$b"'
    bodies = find_concatenated_c_bodies(text)
    assert len(bodies) == 1
    assert has_unescaped_dollar(bodies[0]), 'Mutation FAILED: concatenated `-c "a""$b"` `$b` segment not detected.'


def test_concatenation_quiet_on_normal_single_span():
    text = "python3 -c \"import os; print(os.environ['X'])\" 2>/dev/null"
    bodies = find_concatenated_c_bodies(text)
    assert len(bodies) == 1
    assert not has_unescaped_dollar(bodies[0])
    assert bodies == find_double_quoted_c_bodies(text)
