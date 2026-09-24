"""Every file this repo's own code reaches for, by path, either lives in the repo or is
named here on purpose as one that does not.

The repo is public. A reader who clones it should be able to tell the difference between a
path the code reaches for that is simply missing (a bug, an unfinished PR) and a path that
is kept out of git on purpose (a secret, a private label, unrecorded media). This test scans
the repo's own gates, guards, probes, pipeline, tools, evals and shoot scripts for every file
path they reference, and checks each one against the filesystem and against EXTERNAL, the
declared list of paths that are absent on purpose, each with its own one-line reason. A new
reference to a file nobody committed fails loud here instead of surfacing as a runtime
FileNotFoundError three layers down, and a declared-external entry that nothing references
any more fails too, so the list cannot quietly rot into fiction.

What counts as a reference, kept deliberately simple and line-based rather than a real parser:

  Rule 1, plain literals. Any run of path-safe characters (letters, digits, ``_ . - /``) that
  starts with one of the tracked directory prefixes (gates/, guards/, probes/, pipeline/,
  tools/, evals/, shoots/, docs/, assets/, races/, .githooks/) and is not itself preceded by
  another path-safe character, so a nested mention like ".../foo/gates/bar.py" is never
  misread as a top-level gates/ path. A trailing sentence period is stripped. A match that is
  immediately followed by ``< * $ {`` is a glob or an interpolated template, not a real path
  (``shoots/<batch>/landings.jsonl``, ``shoots/ads2-redo/canary-*.json``), and is dropped
  whole rather than truncated to whatever came before the special character.

  Rule 2, one variable hop. ``$SKILL/name``, ``$SK/name``, ``$DIR/name``, ``$P/name`` and
  ``$GATES/name`` in shell, and ``f"{SKILL}/name"`` or ``os.path.join(HERE, "name")`` (HERE,
  SKILL or ROOT) in Python, where name is a literal filename ending in .py, .sh, .txt or
  .json. The variable is resolved from that SAME file's own assignment: the shell form
  ``VAR="$(cd "$(dirname "$0")/<rel>" && pwd)"`` (or the BASH_SOURCE equivalent, or the bare
  ``VAR=$(dirname "$0")``), or the Python form ``VAR = os.path.dirname(os.path.abspath(
  __file__))`` (one dirname call resolves to the file's own directory, two to the repo root).
  A variable the file never assigns is left unresolved and the reference is skipped, never
  guessed at.

  Both rules skip any line whose first non-blank character is ``#``, so a header comment, a
  TODO, or a note about a file that used to exist never counts as a reference.

Scanned as "code": every *.py and *.sh under gates/, guards/, probes/, pipeline/, tools/,
evals/ (any depth), every *.sh under shoots/ (any depth; the data files living there do not
count), Makefile, .github/workflows/*.yml, and every file directly under .githooks/. .venv,
.reports, tests/ and __pycache__ are never read.
"""
import os
import re
import subprocess

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Declared on purpose: a path the code above reaches for that is not, and should not be, in
# the repo. Each entry needs the reason a stranger cloning this repo would need to hear.
EXTERNAL = {
    "tools/pii_context.txt": "the PII rule table, gitignored on purpose and written by CI from a secret",
    "tools/pii_names.txt": "the third-party name roster, gitignored on purpose and written by CI from a secret",
    "tools/pii_ci_armed": "an opt-in marker that arms the PII secrets requirement in CI, absent until the owner arms it",
    "guards/arrow_rejects.txt": "the private block-list of look and engine pairs that failed the arrow probe; it names private look ids",
}

# Of EXTERNAL, these two are gitignored rather than simply absent: a developer machine that
# has been armed for local PII testing may have them on disk, so "genuinely absent" for them
# means "not tracked by git", not "not on this filesystem".
GIT_CHECKED = {"tools/pii_context.txt", "tools/pii_names.txt"}

SKIP_DIR_NAMES = {".venv", ".reports", "tests", "__pycache__"}

PREFIXES = ("gates/", "guards/", "probes/", "pipeline/", "tools/", "evals/", "shoots/",
            "docs/", "assets/", "races/", ".githooks/")

_PATH_CHARS = r"[A-Za-z0-9_./-]"
_LITERAL_RE = re.compile(
    r"(?<![A-Za-z0-9_./-])(?:" + "|".join(re.escape(p) for p in PREFIXES) + r")" + _PATH_CHARS + "+"
)
_TEMPLATE_CHARS = set("<*${")

_NAME = r"[A-Za-z0-9_.-]+\.(?:py|sh|txt|json)"
_SHELL_USE_RE = re.compile(r"\$(SKILL|SK|DIR|P|GATES)/(" + _NAME + r")\b")
_PY_FSTRING_USE_RE = re.compile(r"f[\"']\{(HERE|SKILL|ROOT)\}/(" + _NAME + r")[\"']")
_PY_JOIN_USE_RE = re.compile(r"os\.path\.join\((HERE|SKILL|ROOT),\s*[\"'](" + _NAME + r")[\"']\)")

# VAR="$(cd "$(dirname "$0")/<rel>" && pwd)", the BASH_SOURCE equivalent, or the bare
# VAR=$(dirname "$0"). The gap before "dirname" excludes ; and = so a shorter assignment
# earlier on the same line (M=$1; CJ=$2; P="$(cd ...") never steals a later one's dirname call.
_SHELL_ASSIGN_RE = re.compile(
    r"([A-Za-z_][A-Za-z0-9_]*)=[^;=\n]{0,40}?"
    r"(?:cd\s+)?\"?\$\(dirname\s+\"(?:\$0|\$\{BASH_SOURCE\[0\]\})\"\)([^\")\s]*)\"?"
)
_PY_HERE_RE = re.compile(
    r"([A-Za-z_][A-Za-z0-9_]*)\s*=\s*os\.path\.dirname\(os\.path\.abspath\(__file__\)\)(?!\))"
)
_PY_ROOT_RE = re.compile(
    r"([A-Za-z_][A-Za-z0-9_]*)\s*=\s*os\.path\.dirname\(os\.path\.dirname\(os\.path\.abspath\(__file__\)\)\)"
)


def iter_source_files():
    """Every file this test treats as "code", per the scope in the module docstring."""
    for d in ("gates", "guards", "probes", "pipeline", "tools", "evals"):
        for dirpath, dirnames, filenames in os.walk(os.path.join(ROOT, d)):
            dirnames[:] = [n for n in dirnames if n not in SKIP_DIR_NAMES]
            for fn in filenames:
                if fn.endswith((".py", ".sh")):
                    yield os.path.join(dirpath, fn)
    for dirpath, dirnames, filenames in os.walk(os.path.join(ROOT, "shoots")):
        dirnames[:] = [n for n in dirnames if n not in SKIP_DIR_NAMES]
        for fn in filenames:
            if fn.endswith(".sh"):
                yield os.path.join(dirpath, fn)
    yield os.path.join(ROOT, "Makefile")
    workflows = os.path.join(ROOT, ".github", "workflows")
    for fn in sorted(os.listdir(workflows)):
        if fn.endswith((".yml", ".yaml")):
            yield os.path.join(workflows, fn)
    githooks = os.path.join(ROOT, ".githooks")
    for fn in sorted(os.listdir(githooks)):
        p = os.path.join(githooks, fn)
        if os.path.isfile(p):
            yield p


def _own_dir(path):
    """The scanned file's own directory, repo-relative, e.g. "gates" or "tools/reviewers"."""
    return os.path.relpath(os.path.dirname(path), ROOT)


def _resolve_shell_vars(path, text):
    base = _own_dir(path)
    resolved = {}
    for m in _SHELL_ASSIGN_RE.finditer(text):
        name, rel = m.group(1), m.group(2)
        target = os.path.join(base, rel.lstrip("/")) if rel else base
        resolved[name] = os.path.normpath(target).replace(os.sep, "/")
    return resolved


def _resolve_python_vars(path, text):
    base = _own_dir(path)
    resolved = {}
    for m in _PY_ROOT_RE.finditer(text):
        resolved[m.group(1)] = "."
    for m in _PY_HERE_RE.finditer(text):
        resolved.setdefault(m.group(1), base)
    return resolved


def scan_file(path):
    """Every reference rule 1 or rule 2 finds in one file, as [(path_as_written, lineno), ...]."""
    with open(path, encoding="utf-8", errors="replace") as fh:
        lines = fh.readlines()
    text = "".join(lines)
    is_shell = path.endswith(".sh") or os.path.basename(os.path.dirname(path)) == ".githooks"
    shell_vars = _resolve_shell_vars(path, text) if is_shell else {}
    py_vars = _resolve_python_vars(path, text) if path.endswith(".py") else {}

    found = []
    for lineno, line in enumerate(lines, 1):
        if line.lstrip().startswith("#"):
            continue

        for m in _LITERAL_RE.finditer(line):
            end = m.end()
            if end < len(line) and line[end] in _TEMPLATE_CHARS:
                continue  # a glob or a template, e.g. shoots/ads2-redo/canary-*.json
            ref = m.group(0).rstrip(".")
            if ref:
                found.append((ref, lineno))

        for m in _SHELL_USE_RE.finditer(line):
            var, name = m.groups()
            if var in shell_vars:
                found.append((f"{shell_vars[var]}/{name}", lineno))

        for use_re in (_PY_FSTRING_USE_RE, _PY_JOIN_USE_RE):
            for m in use_re.finditer(line):
                var, name = m.groups()
                if var in py_vars:
                    base = py_vars[var]
                    found.append((name if base == "." else f"{base}/{name}", lineno))

    return found


def collect_references():
    """{path_as_written: [(file_relative_to_root, lineno), ...]} across the whole repo."""
    refs = {}
    for path in iter_source_files():
        for ref, lineno in scan_file(path):
            refs.setdefault(ref, []).append((os.path.relpath(path, ROOT), lineno))
    return refs


@pytest.fixture(scope="module")
def refs():
    return collect_references()


def test_every_referenced_file_exists_or_is_declared_external(refs):
    offenders = []
    for ref, locations in sorted(refs.items()):
        if ref in EXTERNAL or os.path.exists(os.path.join(ROOT, ref)):
            continue
        offenders.extend(f"{relpath}:{lineno} -> {ref}" for relpath, lineno in locations)
    assert not offenders, "missing, and not declared in EXTERNAL:\n" + "\n".join(offenders)


def test_the_external_list_has_no_stale_entries(refs):
    stale = [ref for ref in EXTERNAL if ref not in refs]
    assert not stale, f"declared external but nothing in the scanned code references it any more: {stale}"


def test_the_external_files_really_are_absent():
    still_present = []
    for ref in EXTERNAL:
        if ref in GIT_CHECKED:
            tracked = subprocess.run(["git", "ls-files", "--error-unmatch", ref],
                                      cwd=ROOT, capture_output=True, text=True)
            if tracked.returncode == 0:
                still_present.append(f"{ref} (tracked by git)")
        elif os.path.exists(os.path.join(ROOT, ref)):
            still_present.append(f"{ref} (on disk)")
    assert not still_present, f"declared external but actually present, so it belongs in the repo: {still_present}"


def test_the_scanner_is_not_vacuous(tmp_path, refs):
    """A scanner that silently found nothing would make every test above pass for the wrong
    reason. Prove it reads code: a fabricated missing reference must be reported, and the
    real repo must yield a healthy number of real references."""
    decoy = tmp_path / "decoy.sh"
    decoy.write_text('python3 "gates/does_not_exist.py" "$1"\n')
    found = scan_file(str(decoy))
    assert ("gates/does_not_exist.py", 1) in found, found

    # The joined form is a rule of its own, and the literal decoy above never reaches it.
    decoy_py = tmp_path / "decoy.py"
    decoy_py.write_text('import os\nHERE = os.path.dirname(os.path.abspath(__file__))\n'
                        'x = os.path.join(HERE, "not_there_either.py")\n')
    joined = scan_file(str(decoy_py))
    assert any(ref.endswith("not_there_either.py") and line == 3 for ref, line in joined), joined

    assert len(refs) >= 30, f"only {len(refs)} distinct references found across the repo"
