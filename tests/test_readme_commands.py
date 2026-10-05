"""A command the README tells a stranger to run is run here, so it cannot rot into a sentence.

The page says the graph runs and gives one dry run command. This reads that command off the
page, runs it with no keys in a scratch directory, and checks it stops before the first spend
and leaves a ledger. It also checks that every arrow in the page's figure is an edge the graph compiles.
If the page and the code drift apart, the suite fails, not a reader.
"""
import os
import re
import shlex
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
D2 = chr(45) * 2   # two hyphens, the way the command line flags start

# Anything that carries a key or the owner's pinned identity, so the run cannot lean on them.
SECRET_SUFFIXES = ("_KEY", "_TOKEN", "_SECRET")
IDENTITY_VARS = ("ELEVENLABS_VOICE_ID", "IDENTITY_PINS", "FAL_KEY", "HEYGEN_API_KEY")


def readme_dry_run_command():
    with open(os.path.join(ROOT, "README.md"), encoding="utf-8") as fh:
        text = fh.read()
    spans = [s for s in re.findall(r"`(python -m pipeline\.run [^`]+)`", text) if f"{D2}mode dry" in s]
    assert len(spans) == 1, f"the README should name exactly one dry run command, found {len(spans)}"
    return shlex.split(spans[0])


def test_the_dry_run_the_readme_names_runs_with_no_keys(tmp_path):
    pytest.importorskip("langgraph")
    argv = readme_dry_run_command()
    assert argv[:3] == ["python", "-m", "pipeline.run"], argv
    board = argv[argv.index(f"{D2}board") + 1]
    assert os.path.isfile(os.path.join(ROOT, board)), f"the README names a board that is not here: {board}"
    env = {k: v for k, v in os.environ.items() if not k.endswith(SECRET_SUFFIXES) and k not in IDENTITY_VARS}
    run_dir = tmp_path / "run"
    r = subprocess.run([sys.executable] + argv[1:] + [f"{D2}run-dir", str(run_dir)], cwd=ROOT, env=env,
                       capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "stopped before the first spend" in r.stdout, r.stdout
    assert (run_dir / "ledger.jsonl").is_file(), "the dry run left no ledger"


ARROW = chr(45) * 2 + ">"
FIGURE_IDS = {"B": "board", "R": "render", "C": "closer", "BU": "build", "AG": "ad_gates", "EYE": "eye",
              "SG": "ship_gate", "D": "deliver", "RV": "review", "L": "ledger"}


def figure_edges():
    """Every arrow the README's Mermaid figure draws, as (from, to) step names. The invisible links are not arrows."""
    with open(os.path.join(ROOT, "README.md"), encoding="utf-8") as fh:
        text = fh.read()
    run = text.split("```mermaid")[1].split("```")[0].split("subgraph RUN[")[1].split("\n    end")[0]
    drawn = set()
    for line in run.splitlines():
        if ARROW not in line and "-.->" not in line:
            continue
        ids = re.findall(rf"(?:^|{ARROW}|-\.->)\s*(\w+)", line.strip())
        drawn.update(zip(ids, ids[1:]))
    return {(FIGURE_IDS[a], FIGURE_IDS[b]) for a, b in drawn}


def test_the_figure_draws_only_edges_the_graph_compiles():
    if ROOT not in sys.path:
        sys.path.insert(0, ROOT)
    graph = pytest.importorskip("pipeline.graph")
    drawn = figure_edges()
    assert len(drawn) >= 9, f"the figure parse found too few arrows to trust: {sorted(drawn)}"
    extra = drawn - graph.edges()
    assert not extra, f"the README figure draws arrows the graph does not compile: {sorted(extra)}"
