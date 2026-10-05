"""A live run spends nothing on a board until a person has scored its four judgment rows.

The judgment rows are hook, realism, absurdity and logic, the questions gates/board_probe.py
prints for a person to score from 0 to 3, since no free check can read an idea. A spot carries
its scores on its board, with scored_by naming who gave them, and a live run goes past the
board only when every row is 2 or more and someone is named. These tests run the toolkit that
spends, pipeline/live.py, with every vendor call and repo script replaced by a fake, and check
where the graph sends the run from the board.

Words used below. A spot is one short ad film and its board is the written plan for it, a
boards.json file. The graph (pipeline/graph.py) is the LangGraph state machine that runs a
spot from its board to delivery. The ledger is the append-only log of every vendor request and
what came back. A spot can shoot its scenes as a chain, each from the last frame of the one
before, and the first-frame judge is a paid check that reads the still the chain starts from
for the props the board names.

The fakes, the scored boards and the live fixture are the ones tests/test_live.py uses for the
rest of the toolkit that spends, imported from there rather than copied.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

from test_live import (  # noqa: E402
    CHAIN_BOARD,
    CT,
    MUG,
    SCORED,
    SHOTS_BOARD,
    Vendor,
    graph,
    scored,
    scripts,
)

# A pytest fixture, imported under its own name so pytest finds it in this module too.
from test_live import live as live  # noqa: E402

from pipeline import live as L  # noqa: E402

# the board's four judgment rows, a person's read of the idea, which a live run needs before it spends

def test_a_live_run_on_a_board_nobody_scored_stops_at_the_board_before_any_request(live, monkeypatch, tmp_path):
    """The free checks cannot read an idea, so a live run spends nothing until a person has scored the
    board's four judgment rows, each 2 or more, and named themselves. A board with no scores, one row under
    2, one row missing, or no name goes back from the board with the reason on the ledger, through the graph
    the way pipeline.run starts a live run. Nothing is sent to a vendor, no render request is written, and
    the first-frame judge, which is paid, is never asked."""
    _, state = live
    G = graph()
    from langgraph.checkpoint.memory import InMemorySaver
    vendor, asked = Vendor(), []

    def judge(args):
        asked.append(args)
        return 0, CT.first_frame_line(1, 1, [], "PASS")
    monkeypatch.setattr(L, "http", vendor)
    monkeypatch.setattr(L.LiveToolkit, "script", scripts(first_frame=judge))
    rows = SCORED["scores"]
    cases = {
        "nobody scored it": (dict(scores=None, scored_by=None),
                             {"hook": "missing", "realism": "missing", "absurdity": "missing", "logic": "missing",
                              "scored_by": "missing"}),
        "one row under 2": (dict(scores={**rows, "realism": 1}), {"realism": "under 2"}),
        "one row missing": (dict(scores={k: v for k, v in rows.items() if k != "logic"}), {"logic": "missing"}),
        "nobody named": (dict(scored_by=""), {"scored_by": "missing"}),
    }
    for i, (case, (spot, unmet)) in enumerate(cases.items()):
        run_dir = tmp_path / f"run-{i}"
        tk = L.LiveToolkit(str(run_dir))
        st = dict(state, board=scored(CHAIN_BOARD, tmp_path, f"unscored-{i}.json", props=[MUG], **spot),
                  run_dir=str(run_dir), mode="live")
        out = G.compile_graph(checkpointer=InMemorySaver()).invoke(st, {"configurable": {"toolkit": tk, "thread_id": case}})
        assert out["trail"] == ["board", "ledger"] and out["outcome"] == "stopped at board", (case, out["trail"])
        written = tk.ledger.rows()
        gate = [r for r in written if r["kind"] == "gate" and r["step"] == "board"]
        assert len(gate) == 1 and gate[0]["pass"] is False and gate[0]["failed"] == [], (case, gate)
        assert gate[0]["scores"]["unmet"] == unmet, (case, gate[0]["scores"])
        reason = gate[0]["reason"]
        assert reason.startswith("a live run spends nothing until the four judgment rows, hook, realism, absurdity "
                                 "and logic, are each scored 2 or more and scored_by names who scored them"), reason
        assert reason.endswith('Score them on the spot as "scores" and "scored_by", the way pipeline/DOCTRINE.md shows'), reason
        assert written[-1]["kind"] == "close" and written[-1]["because"]["reason"] == reason, (case, written[-1])
        assert not [r for r in written if r["kind"] == "request"], f"{case}: a render request was written"
    assert vendor.calls == [] and asked == [], "something was sent, or the paid judge asked, for a board nobody scored"


def test_a_live_board_scored_by_someone_named_goes_on_and_its_row_says_what_was_scored(live, monkeypatch, tmp_path):
    """Scored in full, 2 or more on every row with the reader named, the same board goes on to render, and
    the board's own row carries what was scored and by whom. The scores never lift a failed check, so the
    same scored board with a hook the film does not open on still goes back."""
    tk, state = live
    monkeypatch.setattr(L, "http", Vendor())
    monkeypatch.setattr(L.LiveToolkit, "script", scripts())
    st = dict(state, board=scored(SHOTS_BOARD, tmp_path), spot="zai")
    v = tk.board(st)
    assert v["pass"] is True and "reason" not in v and v["failed"] == [], v
    gate = [r for r in tk.ledger.rows() if r["kind"] == "gate" and r["step"] == "board"][-1]
    assert gate["scores"] == {"rows": SCORED["scores"], "scored_by": SCORED["scored_by"], "unmet": {}}, gate
    assert graph().after_board(dict(st, verdict={"board": v})) == "render"
    late = dict(st, board=scored(SHOTS_BOARD, tmp_path, "late-hook.json", hook="b"))
    v = tk.board(late)
    assert v["pass"] is False and v["failed"] == ["hook_first"] and "reason" not in v, v
    assert v["why"]["hook_first"].startswith("hook names scene b, but the film opens on scene a"), v["why"]
