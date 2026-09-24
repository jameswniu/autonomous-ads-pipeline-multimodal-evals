"""The graph in pipeline/: its routing, its bounds, its two interrupts, the CLI, and dry runs.

Routing is tested through a scripted toolkit that hands each node a verdict from a queue,
so every path is exercised with no media, no keys and no spend. The gates themselves are
tested in test_gates.py; here the question is whether the graph sends each verdict where
the steps say it goes, and whether a person's answers and a run's record stay straight.
Several tests here exist because a mutation of the code they name survived the suite.
"""
import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

langgraph = pytest.importorskip("langgraph")

from langgraph.checkpoint.memory import InMemorySaver  # noqa: E402
from langgraph.types import Command  # noqa: E402

from pipeline import graph as G  # noqa: E402
from pipeline.ledger import fingerprint  # noqa: E402
from pipeline.steps import STEPS  # noqa: E402
from pipeline.toolkit import DryToolkit, Toolkit  # noqa: E402

PASS_GATES = {"caption": "pass", "drift": "pass", "mouth": "pass"}
REVIEW_FLAG = {**PASS_GATES, "mouth": "review"}
KEEP = {"verdict": "keep", "who": "test"}
APPROVE = {"verdict": "approve", "who": "t"}
FLAG = "EDGE CLIP: bright compact prop straddles the frame edge at right 0.5-0.7s. Look before shipping."


def withdraw(back_to, **fix):
    return {"verdict": "withdraw", "back_to": back_to, "reason": "a reason for the record", "who": "t", **fix}


class Scripted(Toolkit):
    """Each step pops its next verdict from a queue. An empty queue repeats the last one."""

    def __init__(self, run_dir, run_id=None, **script):
        super().__init__(run_dir, run_id)
        self.script = {k: list(v) for k, v in script.items()}
        self.last = {}
        self.calls = []     # (step, the changes it was handed), so tests read what a step received

    def _next(self, step, default, state=None):
        self.calls.append((step, dict((state or {}).get("changes") or {})))
        queue = self.script.get(step)
        if queue:
            self.last[step] = queue.pop(0)
        return dict(self.last.get(step, default))

    def board(self, state):
        return self._next("board", {"pass": True})

    def render(self, state):
        self.ledger.append("request", "render", request_id="req_scripted")
        return self._next("render", {}, state)

    def closer(self, state):
        return self._next("closer", {"pass": True}, state)

    def build(self, state):
        return self._next("build", {"pass": True, "artifacts": {"master": os.path.join(self.run_dir, "masters", "m.mp4")}},
                          state)

    def ad_gates(self, state):
        return self._next("ad_gates", PASS_GATES, state)

    def ship_gate(self, state):
        v = self._next("ship_gate", {"pass": True}, state)
        self.ledger.append("gate", "ship_gate", **v)
        return v

    def deliver(self, state):
        return {"delivered": True, "artifacts": {"delivered": os.path.join(self.run_dir, "delivered", "m.mp4")}}


def start(tmp_path):
    return {"board": "b", "spot": "s", "run_dir": str(tmp_path), "mode": "test",
            "attempts": {}, "verdict": {}, "artifacts": {}}


def run(tmp_path, eye=None, review=None, **script):
    """Run the graph on scripted verdicts. The eye takes its answers from `eye` in order and
    fails the test if it is asked without one; the review keeps every cut unless told. Every
    packet the run showed a person is kept on the toolkit for the test to read."""
    tk = Scripted(str(tmp_path), **script)
    g = G.compile_graph(checkpointer=InMemorySaver())
    config = {"configurable": {"toolkit": tk, "thread_id": "t"}}
    out = g.invoke(start(tmp_path), config)
    answers = {"eye": list(eye or []), "review": list(review or [])}
    tk.packets = []
    while "__interrupt__" in out:
        packet = out["__interrupt__"][0].value
        tk.packets.append(packet)
        kind = packet["kind"]
        if kind == "review" and not answers["review"]:
            answer = KEEP
        else:
            assert answers[kind], (f"the run stopped at the {kind} and the test gave it no answer: "
                                   f"{out['trail']} {packet.get('problem', '')}")
            answer = answers[kind].pop(0)
        out = g.invoke(Command(resume=answer), config)
    return out, tk


def hops(trail):
    return set(zip(trail, trail[1:], strict=False))


def handed(tk, step):
    return [changes for s, changes in tk.calls if s == step]


# structure

def test_every_step_is_a_node_and_every_node_is_a_step_or_says_why():
    nodes = set(G.NODES)
    steps = {s.node for s in STEPS}
    assert steps <= nodes, f"steps with no node: {steps - nodes}"
    # the nodes that are not steps: a person before shipping, a person after, and the record
    assert nodes - steps == {"eye", "review", "ledger"}, nodes - steps


def test_every_compiled_edge_is_reachable_by_some_run(tmp_path):
    """A dead edge is a claim about the pipeline that no run can make true, so each edge
    the compiler holds must be walked by at least one scripted sequence of verdicts."""
    scenarios = [
        dict(),                                                              # the straight path
        dict(board=[{"pass": False}]),                                       # board -> ledger
        dict(render=[{"failed": ["a"]}, {}]),                                # render -> render
        dict(render=[{"failed": ["a"]}, {"failed": ["a"]}]),                 # render -> ledger
        dict(closer=[{"pass": False}]),                                      # closer -> ledger
        dict(build=[{"pass": False}]),                                       # build -> ledger
        dict(ad_gates=[{**PASS_GATES, "mouth": "fail"}]),                    # ad_gates -> ledger
        dict(ship_gate=[{"pass": False, "cause": "loudness"}]),              # ship_gate -> ledger
        dict(eye=[APPROVE], ad_gates=[REVIEW_FLAG]),                         # ad_gates -> eye -> ship_gate
        dict(eye=[{"verdict": "reject", "cause": "scene", "scene": "a"}, APPROVE],
             ad_gates=[REVIEW_FLAG, REVIEW_FLAG]),                           # eye -> render
        dict(eye=[{"verdict": "reject", "cause": "lag", "nudge": -0.12}],
             ad_gates=[{**PASS_GATES, "lag_s": -0.16}, PASS_GATES]),        # eye -> build
        dict(eye=[{"verdict": "reject", "cause": "closer", "look": "new"}],
             ad_gates=[REVIEW_FLAG, PASS_GATES]),                            # eye -> closer
        dict(eye=[{"verdict": "reject", "cause": "other"}], ad_gates=[REVIEW_FLAG]),  # eye -> ledger
        dict(eye=[APPROVE], ship_gate=[{"pass": False, "cause": "directional"}, {"pass": True}]),
        dict(review=[withdraw("render", scene="a"), KEEP]),
        dict(review=[withdraw("closer", look="new"), KEEP]),
        dict(review=[withdraw("build", nudge=0.1), KEEP]),
        dict(review=[withdraw("build")] * 4),                                # review -> ledger, bound
    ]
    walked = set()
    for i, sc in enumerate(scenarios):
        eye, review = sc.pop("eye", None), sc.pop("review", None)
        out, _ = run(tmp_path / str(i), eye=eye, review=review, **sc)
        walked |= hops(out["trail"])
    dead = G.edges() - walked
    assert not dead, f"compiled edges no run can take: {sorted(dead)}"


def test_the_straight_path_is_the_seven_steps_in_order(tmp_path):
    out, _ = run(tmp_path)
    assert out["trail"] == [s.node for s in STEPS] + ["review", "ledger"], out["trail"]
    assert out["outcome"] == "delivered"


# the order the repo never enforced before

def test_deliver_is_unreachable_unless_the_ship_gate_passed(tmp_path):
    """Both gate receipts in this repo went unread, because the script that read them
    never shipped. This is the first thing that makes the order binding. Every failure
    stops the run, except the two flags a person reads, and a rejection of those stops too."""
    for i, cause in enumerate(("loudness", "peak", "letterbox", "unreadable", "held")):
        out, _ = run(tmp_path / str(i), ship_gate=[{"pass": False, "cause": cause}])
        assert "deliver" not in out["trail"], (cause, out["trail"])
        assert out["outcome"] == "stopped at ship_gate", out["outcome"]
    for cause in ("directional", "replay"):
        out, _ = run(tmp_path / cause, eye=[{"verdict": "reject", "cause": "other", "who": "t"}],
                     ship_gate=[{"pass": False, "cause": cause}])
        assert "deliver" not in out["trail"] and out["outcome"] == "stopped at eye", out["trail"]


def test_every_delivery_follows_a_passing_ship_gate(tmp_path):
    """Walk the trails of runs that deliver, including through the eye, and check the step
    before each delivery is a ship gate that passed."""
    tk_runs = [
        run(tmp_path / "a"),
        run(tmp_path / "b", eye=[APPROVE], ship_gate=[{"pass": False, "cause": "directional"}, {"pass": True}]),
        run(tmp_path / "c", review=[withdraw("build"), KEEP]),
    ]
    for out, tk in tk_runs:
        trail = out["trail"]
        rows = tk.ledger.rows()
        deliveries = [i for i, step in enumerate(trail) if step == "deliver"]
        assert deliveries, trail
        assert all(trail[i - 1] == "ship_gate" for i in deliveries), trail
        # read the gate rows in order: the one each delivery follows must have passed
        verdicts = [r["pass"] for r in rows if r["kind"] == "gate" and r["step"] == "ship_gate"]
        gate_steps = [i for i, step in enumerate(trail) if step == "ship_gate"]
        assert len(verdicts) == len(gate_steps), (verdicts, trail)
        for i in deliveries:
            assert verdicts[gate_steps.index(i - 1)] is True, (verdicts, trail)


# bounds

def test_the_bounds_are_the_numbers_the_page_states():
    """The loop tests below compare against the constants, so on their own a loosened
    bound loosens its test with it, which a break test caught. The numbers are pinned
    here, to what the step table and the source say, so raising one is a deliberate
    edit in two places rather than a quiet one."""
    from pipeline.steps import BY_NODE
    assert G.MAX_SCENE_REROLLS == 1 and "once" in BY_NODE["render"].fails, (
        "the source says re-roll visible breakage once, and the step table repeats it")
    assert G.MAX_BUILDS == 3, "three builds on the eye's nudges, then a person"
    assert G.MAX_EYE_REJECTS == 1, "one scene or closer sent back by the eye per run"
    assert G.MAX_WITHDRAWALS == 3, "the three withdrawals ads7 took to land its v4 cuts"
    assert G.LAG_FIX == 0.12, "the source's threshold for a closer nudge"


def test_a_caption_or_placement_fault_stops_instead_of_rebuilding_the_same_inputs(tmp_path):
    """The build is deterministic, so a rebuild with nothing changed repeats the fault. A
    person changes the build and resumes the run from it, which is how August fixed these.
    A placement nobody could measure stops the same way."""
    for i, gates in enumerate(({**PASS_GATES, "caption": "fail"}, {**PASS_GATES, "drift": "fail"},
                               {**PASS_GATES, "drift": "unreadable"})):
        out, _ = run(tmp_path / str(i), ad_gates=[gates])
        assert out["trail"].count("build") == 1, (gates, out["trail"])
        assert out["outcome"] == "stopped at ad_gates", (gates, out["outcome"])


def test_a_broken_scene_rerolls_once_then_stops(tmp_path):
    out, _ = run(tmp_path, render=[{"failed": ["a"]}])
    assert out["trail"].count("render") == 1 + G.MAX_SCENE_REROLLS, out["trail"]
    assert out["outcome"] == "stopped at render"


def test_each_broken_scene_gets_its_own_reroll(tmp_path):
    """One counter for the whole run let scene a's re-roll use up scene b's, so b, broken
    once, stopped the run unretried. The source allows one re-roll per broken scene."""
    out, tk = run(tmp_path, render=[{"failed": ["a"]}, {"failed": ["b"]}, {}])
    assert out["trail"].count("render") == 3 and out["outcome"] == "delivered", out["trail"]


def test_a_scene_broken_twice_stops_even_when_another_breaks_for_the_first_time(tmp_path):
    """The check is that every broken scene is within its budget, not that any one is. Any
    would re-roll scene a a third time because scene b still had its retry."""
    out, _ = run(tmp_path, render=[{"failed": ["a"]}, {"failed": ["a", "b"]}, {}])
    assert out["trail"].count("render") == 2 and out["outcome"] == "stopped at render", out["trail"]


def test_a_request_that_may_have_been_billed_stops_the_run(tmp_path):
    """Whatever else came back, a request the vendor never confirmed stops the run for a person
    instead of being retried, since a retry could pay for it twice."""
    out, _ = run(tmp_path, render=[{"unconfirmed": ["b"], "failed": ["a"]}])
    assert out["trail"].count("render") == 1 and out["outcome"] == "stopped at render", out["trail"]


def test_a_mouth_that_does_not_track_stops_instead_of_rerendering(tmp_path):
    """The source's fix for a look that cannot carry the line is a new look, because the
    same look and audio render the same mouth again, and look generation stays outside
    this repository. So FAIL and no face stop the run rather than spend on a replay."""
    for i, mouth in enumerate(("fail", "noface")):
        out, _ = run(tmp_path / str(i), ad_gates=[{**PASS_GATES, "mouth": mouth}])
        assert out["trail"].count("closer") == 1, out["trail"]
        assert out["outcome"] == "stopped at ad_gates"


def test_ship_gate_failures_do_not_loop(tmp_path):
    """A remaster repeats the same loudnorm pass and a re-render the same letterbox, so
    neither is retried."""
    for i, cause in enumerate(("loudness", "letterbox")):
        out, _ = run(tmp_path / str(i), ship_gate=[{"pass": False, "cause": cause}])
        assert out["trail"].count("build") == 1 and out["trail"].count("closer") == 1, out["trail"]


def test_withdrawals_are_bounded_and_each_is_on_the_record(tmp_path):
    back = withdraw("closer", look="another look", reason="the look reads as a void")
    out, tk = run(tmp_path, review=[back] * (G.MAX_WITHDRAWALS + 1))
    assert out["trail"].count("review") == G.MAX_WITHDRAWALS + 1, out["trail"]
    assert out["outcome"] == "withdrawn, with no withdrawal left to fix it", out["outcome"]
    pulled = [r for r in tk.ledger.rows() if r["kind"] == "withdrawn"]
    assert len(pulled) == G.MAX_WITHDRAWALS + 1 and all(r["reason"] for r in pulled), pulled
    assert all(r["master"] == "delivered/m.mp4" for r in pulled), "a withdrawal names what it pulled, relative to the run"


def test_the_eye_sends_a_scene_or_the_closer_back_once_per_run(tmp_path):
    """Both kinds of rejection count against one budget. A second one stops the run for a
    person, whether it names a scene or the closer."""
    out, tk = run(tmp_path, eye=[{"verdict": "reject", "cause": "scene", "scene": "a", "who": "t"},
                                 {"verdict": "reject", "cause": "closer", "look": "L2", "who": "t"}],
                  ad_gates=[REVIEW_FLAG])
    assert out["outcome"] == "stopped at eye", out["trail"]
    assert out["trail"].count("closer") == 2 and out["trail"].count("render") == 2, out["trail"]


def test_the_eye_can_ask_for_three_builds_and_no_more(tmp_path):
    lag = {"verdict": "reject", "cause": "lag", "nudge": -0.14, "who": "t"}
    out, _ = run(tmp_path, eye=[lag, lag, lag], ad_gates=[{**PASS_GATES, "lag_s": -0.2}])
    assert out["trail"].count("build") == G.MAX_BUILDS, out["trail"]
    assert out["outcome"] == "stopped at eye", out["outcome"]


# the eye

def test_a_review_stops_the_run_until_a_person_answers(tmp_path):
    tk = Scripted(str(tmp_path), ad_gates=[REVIEW_FLAG])
    g = G.compile_graph(checkpointer=InMemorySaver())
    config = {"configurable": {"toolkit": tk, "thread_id": "t"}}
    out = g.invoke(start(tmp_path), config)
    assert "__interrupt__" in out, "a REVIEW went on without anyone looking"
    assert "ship_gate" not in out["trail"]
    out = g.invoke(Command(resume={"verdict": "approve", "who": "test"}), config)
    assert out["__interrupt__"][0].value["kind"] == "review", "a delivery went unreviewed"
    out = g.invoke(Command(resume=KEEP), config)
    assert out["outcome"] == "delivered"
    eye_rows = [r for r in tk.ledger.rows() if r["kind"] == "eye"]
    assert eye_rows and eye_rows[0]["who"] == "test", "the ledger does not say who approved"


def test_a_lag_the_probe_passes_still_goes_to_the_eye(tmp_path):
    """The probe PASSes a lag up to 0.20 s and the source fixes anything from 0.12 s. The
    automatic nudge shipped a desync once, so a person sets it, and the build receives it."""
    out, tk = run(tmp_path, eye=[{"verdict": "reject", "cause": "lag", "nudge": -0.14, "who": "t"}],
                  ad_gates=[{**PASS_GATES, "lag_s": -0.14}, PASS_GATES])
    assert out["trail"][:7] == ["board", "render", "closer", "build", "ad_gates", "eye", "build"], out["trail"]
    builds = handed(tk, "build")
    assert builds[0].get("nudge") is None and builds[1]["nudge"] == -0.14, builds


def test_the_lag_threshold_is_inclusive(tmp_path):
    """The source fixes a lag of 0.12 s or more, so exactly 0.12 goes to the eye and just
    under it ships."""
    out, _ = run(tmp_path / "at", eye=[APPROVE], ad_gates=[{**PASS_GATES, "lag_s": G.LAG_FIX}])
    assert "eye" in out["trail"], out["trail"]
    out, _ = run(tmp_path / "under", ad_gates=[{**PASS_GATES, "lag_s": -(G.LAG_FIX - 0.01)}])
    assert "eye" not in out["trail"], out["trail"]


def test_a_directional_flag_is_read_and_the_override_is_on_the_record(tmp_path):
    out, tk = run(tmp_path, eye=[{"verdict": "approve", "who": "reader"}],
                  ship_gate=[{"pass": False, "cause": "directional"}, {"pass": True}])
    gates = handed(tk, "ship_gate")
    assert "arrow_ok" not in gates[0] and gates[1]["arrow_ok"] == "reader", gates
    eye = [r for r in tk.ledger.rows() if r["kind"] == "eye"][0]
    assert eye["asked_by"] == "ship_gate" and eye["who"] == "reader", eye


def test_a_directional_flag_is_read_once_per_master(tmp_path):
    """After a person approved the direction, the same flag on the rerun stops the run
    rather than asking again, since the gate was told the arrow is read."""
    out, _ = run(tmp_path, eye=[APPROVE], ship_gate=[{"pass": False, "cause": "directional"}] * 2)
    assert out["trail"].count("eye") == 1 and out["outcome"] == "stopped at ship_gate", out["trail"]


def test_a_new_master_drops_the_overrides_read_on_the_old_one(tmp_path):
    """The eye read the direction on one master, then sent a replay back for a nudge. The
    rebuilt master is a different file, so the direction has to be read again on it."""
    lag = {"verdict": "reject", "cause": "lag", "nudge": -0.1, "who": "t"}
    out, tk = run(tmp_path, eye=[APPROVE, lag, APPROVE],
                  ship_gate=[{"pass": False, "cause": "directional"}, {"pass": False, "cause": "replay"},
                             {"pass": False, "cause": "directional"}, {"pass": True}])
    gates = handed(tk, "ship_gate")
    assert gates[1]["arrow_ok"] == "t" and "arrow_ok" not in gates[2], gates
    assert out["outcome"] == "delivered", out["trail"]


def test_approving_an_ad_gate_question_overrides_nothing_at_the_ship_gate(tmp_path):
    out, tk = run(tmp_path, eye=[APPROVE], ad_gates=[REVIEW_FLAG])
    assert all("arrow_ok" not in g and "replay_ok" not in g for g in handed(tk, "ship_gate")), handed(tk, "ship_gate")
    eye = [r for r in tk.ledger.rows() if r["kind"] == "eye"][0]
    assert eye["asked_by"] == "ad_gates", eye


def test_a_replay_is_read_at_the_eye_and_its_reason_is_the_override(tmp_path):
    """Visibility of a replay is declared by someone who read the scan, never preset. An
    approval with no reason is asked again and not recorded; the reason given is what the
    gate is rerun with."""
    out, tk = run(tmp_path, eye=[{"verdict": "approve", "who": "r"},
                                 {"verdict": "approve", "who": "r", "reason": "a still interior, nothing moves"}],
                  ship_gate=[{"pass": False, "cause": "replay", "replay_turn_s": 20.0}, {"pass": True}])
    assert out["outcome"] == "delivered", out["trail"]
    gates = handed(tk, "ship_gate")
    assert "replay_ok" not in gates[0], gates
    assert gates[1]["replay_ok"] == "a still interior, nothing moves, read at the eye by r", gates
    assert "problem" in tk.packets[1] and tk.packets[1]["cause"] == "replay", tk.packets
    assert len([r for r in tk.ledger.rows() if r["kind"] == "eye"]) == 1, "the refused answer reached the ledger"


def test_the_eye_is_shown_the_evidence_the_flags_and_what_is_in_force(tmp_path):
    lag = {"verdict": "reject", "cause": "lag", "nudge": -0.14, "who": "t"}
    out, tk = run(tmp_path, eye=[lag, APPROVE], ad_gates=[{**PASS_GATES, "lag_s": -0.2, "corr": 0.4},
                                                          {**PASS_GATES, "lag_s": -0.13, "corr": 0.41}])
    first, second = tk.packets[0], tk.packets[1]
    assert first["asked_by"] == "ad_gates" and first["evidence"]["lag_s"] == -0.2, first
    assert second["in_force"] == {"nudge": -0.14} and second["evidence"]["lag_s"] == -0.13, second
    assert first["master"].endswith("masters/m.mp4"), first


def test_an_edge_flag_goes_to_the_eye_once_and_a_new_one_goes_again(tmp_path):
    """The edge probe is a flagger, not a gate: it names the seconds and the eye rules. A
    flag a person has seen is not raised again on a rebuild, and a scene rendered again with
    a new flag is asked about again."""
    rendered = {"flags": {"b": FLAG}, "rendered": ["a", "b", "c"]}
    out, tk = run(tmp_path / "seen", eye=[APPROVE], render=[rendered], review=[withdraw("build"), KEEP])
    assert out["trail"].count("eye") == 1 and out["outcome"] == "delivered", out["trail"]
    assert tk.packets[0]["flags"] == {"b": FLAG}, tk.packets[0]
    again = {"flags": {"b": FLAG.replace("0.5-0.7", "2.1-2.4")}, "rendered": ["b"]}
    out, _ = run(tmp_path / "new", eye=[APPROVE, APPROVE], render=[rendered, again],
                 review=[withdraw("render", scene="b"), KEEP])
    assert out["trail"].count("eye") == 2, out["trail"]


def test_a_seen_flag_is_seen_on_one_scene_and_one_take(tmp_path):
    """Approving a flag clears it for the take it was raised on. The same words on another
    scene, or on a new take of the same scene, go to the eye again. A take reused as it stood
    does not."""
    first = {"flags": {"b": FLAG}, "rendered": ["a", "b", "c"]}
    cases = (("other-scene", "c", {"flags": {"c": FLAG}, "rendered": ["c"], "fresh": ["c"]}, 2),
             ("new-take", "b", {"flags": {"b": FLAG}, "rendered": ["b"], "fresh": ["b"]}, 2),
             ("same-take", "b", {"flags": {"b": FLAG}, "rendered": ["b"], "fresh": []}, 1))
    for name, scene, second, eyes in cases:
        out, _ = run(tmp_path / name, eye=[APPROVE, APPROVE], render=[first, second],
                     review=[withdraw("render", scene=scene), KEEP])
        assert out["trail"].count("eye") == eyes, (name, out["trail"])
    # A second approval adds to what was seen, so a rebuild after it asks about neither flag.
    second = {"flags": {"c": FLAG.replace("0.5-0.7", "2.1-2.4")}, "rendered": ["c"], "fresh": ["c"]}
    out, _ = run(tmp_path / "both-seen", eye=[APPROVE, APPROVE, APPROVE], render=[first, second],
                 review=[withdraw("render", scene="c"), withdraw("build"), KEEP])
    assert out["trail"].count("eye") == 2, out["trail"]


def test_an_answer_cannot_carry_anything_but_the_fix_it_asks_for(tmp_path):
    lag = {"verdict": "reject", "cause": "lag", "nudge": -0.12, "who": "t", "arrow_ok": "smuggled",
           "replay_ok": "smuggled", "flags_seen": ["smuggled"]}
    out, tk = run(tmp_path, eye=[lag], ad_gates=[{**PASS_GATES, "lag_s": -0.2}, PASS_GATES])
    rebuilt = handed(tk, "build")[1]
    assert rebuilt == {"nudge": -0.12}, rebuilt


def test_a_scene_and_its_prompt_travel_together_and_are_spent_by_the_render(tmp_path):
    """A prompt written for scene b must never be paid for on scene a, and a scene redone once
    is not redone again by a later answer that names another."""
    out, tk = run(tmp_path, eye=[{"verdict": "reject", "cause": "scene", "scene": "b", "prompt": "P for b", "who": "t"}],
                  ad_gates=[REVIEW_FLAG, PASS_GATES], review=[withdraw("render", scene="a"), KEEP])
    renders = handed(tk, "render")
    assert renders[1]["scene"] == "b" and renders[1]["prompt"] == "P for b", renders
    assert renders[2]["scene"] == "a" and "prompt" not in renders[2], renders
    closes = [r for r in tk.ledger.rows() if r["kind"] == "close"]
    assert closes and "scene" not in (closes[-1].get("because") or {}), closes[-1]


def test_a_scene_a_failed_render_owes_is_kept_for_its_retry(tmp_path):
    """If the scene a person asked for fails to come back, the automatic retry still sends
    the prompt they wrote, not the board's."""
    out, tk = run(tmp_path, eye=[{"verdict": "reject", "cause": "scene", "scene": "b", "prompt": "P", "who": "t"}],
                  ad_gates=[REVIEW_FLAG, PASS_GATES], render=[{}, {"failed": ["b"]}, {}])
    renders = handed(tk, "render")
    assert renders[1]["prompt"] == "P" and renders[2]["prompt"] == "P", renders


@pytest.mark.parametrize("packet,answer,ok", [
    ({"kind": "eye"}, {"verdict": "approve"}, True),
    ({"kind": "eye", "cause": "replay"}, {"verdict": "approve"}, False),
    ({"kind": "eye", "cause": "replay"}, {"verdict": "approve", "reason": "still"}, True),
    ({"kind": "eye"}, {"verdict": "maybe"}, False),
    ({"kind": "eye"}, {"verdict": "reject"}, False),
    ({"kind": "eye"}, {"verdict": "reject", "cause": "scene"}, False),
    ({"kind": "eye"}, {"verdict": "reject", "cause": "closer"}, False),
    ({"kind": "eye"}, {"verdict": "reject", "cause": "closer", "engine": "avatar_iv"}, True),
    ({"kind": "eye"}, {"verdict": "reject", "cause": "lag", "nudge": "a lot"}, False),
    ({"kind": "eye"}, {"verdict": "reject", "cause": "other"}, True),
    ({"kind": "review"}, {"verdict": "keep"}, True),
    ({"kind": "review"}, {"verdict": "withdraw", "back_to": "board", "reason": "r"}, False),
    ({"kind": "review"}, {"verdict": "withdraw", "back_to": "build"}, False),
    ({"kind": "review"}, {"verdict": "withdraw", "back_to": "render", "reason": "r"}, False),
    ({"kind": "review"}, {"verdict": "withdraw", "back_to": "closer", "reason": "r"}, False),
    ({"kind": "review"}, {"verdict": "withdraw", "back_to": "build", "reason": "r"}, True),
    ({"kind": "review"}, "keep", False),
])
def test_an_answer_the_graph_cannot_act_on_is_named(packet, answer, ok):
    assert (G.answer_problem(packet, answer) is None) is ok, G.answer_problem(packet, answer)


# the ledger

def test_every_run_closes_on_the_record_shipped_or_stopped(tmp_path):
    for i, sc in enumerate([dict(), dict(board=[{"pass": False}]), dict(build=[{"pass": False}])]):
        out, tk = run(tmp_path / str(i), **sc)
        rows = tk.ledger.rows()
        assert rows and rows[-1]["kind"] == "close", rows[-1:]
        assert rows[-1]["outcome"] == out["outcome"]
        assert [r["seq"] for r in rows] == list(range(1, len(rows) + 1)), "seq is not append-only"


def test_the_close_row_is_relative_and_says_why(tmp_path):
    out, tk = run(tmp_path)
    close = tk.ledger.rows()[-1]
    assert close["artifacts"]["master"] == "masters/m.mp4", close["artifacts"]
    assert close["because"]["verdict"] == "keep", close
    assert str(tmp_path) not in json.dumps(tk.ledger.rows()), "an absolute path reached the ledger"


def test_the_review_is_shown_the_cut_that_was_delivered(tmp_path):
    out, tk = run(tmp_path)
    assert tk.packets[-1] == {"kind": "review", "delivered": os.path.join(str(tmp_path), "delivered", "m.mp4")}


def test_a_look_named_in_an_answer_reaches_the_ledger_only_as_its_fingerprint(tmp_path):
    look = "LOOKID0123456789ABCDEF"
    out, tk = run(tmp_path, eye=[{"verdict": "reject", "cause": "closer", "look": look, "who": "t"}],
                  ad_gates=[REVIEW_FLAG, PASS_GATES], review=[withdraw("closer", look=look), KEEP])
    text = open(tk.ledger.path).read()
    assert look not in text, "a raw look id reached the ledger"
    assert fingerprint(look) in text


def test_an_answer_may_not_overwrite_a_rows_own_fields(tmp_path):
    out, tk = run(tmp_path, eye=[{"verdict": "approve", "who": "t", "seq": 99, "ts": "then", "spot": "x"}],
                  ad_gates=[REVIEW_FLAG])
    rows = tk.ledger.rows()
    assert [r["seq"] for r in rows] == list(range(1, len(rows) + 1)), "an answer rewrote a row's seq"
    eye = [r for r in rows if r["kind"] == "eye"][0]
    assert eye["spot"] == "s" and eye["answer"]["spot"] == "x", eye


def test_the_ledger_refuses_a_field_that_would_overwrite_its_own(tmp_path):
    from pipeline.ledger import Ledger
    ledger = Ledger(str(tmp_path))
    for field in ("seq", "ts", "run", "schema"):
        with pytest.raises(ValueError):
            ledger.append("eye", "eye", **{field: "forged"})
    assert ledger.rows() == [], "a refused row was written"


# dry runs on the committed boards

def dry(tmp_path, board, spot):
    tk = DryToolkit(str(tmp_path))
    g = G.compile_graph(checkpointer=InMemorySaver())
    out = g.invoke({"board": os.path.join(ROOT, board), "spot": spot, "run_dir": str(tmp_path),
                    "mode": "dry", "attempts": {}, "verdict": {}, "artifacts": {}},
                   {"configurable": {"toolkit": tk, "thread_id": "t"}})
    return out, tk.ledger.rows()


def test_a_dry_run_stops_before_the_first_spend_and_prices_it(tmp_path):
    out, rows = dry(tmp_path, "shoots/ads7-real/boards.json", "gemini")
    assert out["trail"] == ["board", "render", "ledger"], out["trail"]
    assert out["outcome"] == "dry: stopped before the first spend"
    requests = [r for r in rows if r["kind"] == "request"]
    assert requests and all(r["dry"] for r in requests)
    assert all(r["request_id"].startswith("req_") for r in requests), "request ids are placeholders"
    board = json.load(open(os.path.join(ROOT, "shoots/ads7-real/boards.json")))
    first = board["spots"]["gemini"]["scenes"]["a"]
    assert requests[0]["prompt"] == first + "\n\n" + board["guard"], (
        "the dry run would send a different prompt than the one the August shoots sent")
    est = [r for r in rows if r["kind"] == "estimate"][0]
    assert est["est_usd"] == round(sum(r["est_usd"] for r in requests), 2)


def test_the_board_gate_refuses_a_board_that_shipped_in_august(tmp_path):
    """A real finding, pinned so it cannot be forgotten. The ads5 board predates the
    centre-crop rule, so today's gate stops it at the board even though it shipped. The
    ruler moved after the shoot, which is what the relabel edge is for."""
    out, rows = dry(tmp_path, "shoots/ads5/boards.json", "orchard")
    assert out["trail"] == ["board", "ledger"], out["trail"]
    gate = [r for r in rows if r["kind"] == "gate"][0]
    assert "crop_clause" in gate["failed"], gate


# A run that waits for a person survives the process ending

def test_a_run_waiting_at_the_review_resumes_from_disk_in_a_new_process(tmp_path):
    """The review can take days, so a live run checkpoints to SQLite. Stop at the review,
    drop every in-memory object, reopen the checkpoint with a fresh toolkit, and finish: the
    run keeps its id, the ledger keeps counting, and the answer lands on the record."""
    from langgraph.checkpoint.sqlite import SqliteSaver
    db = str(tmp_path / "checkpoint.sqlite")
    with SqliteSaver.from_conn_string(db) as saver:
        tk = Scripted(str(tmp_path))
        run_id = tk.ledger.run_id
        config = {"configurable": {"toolkit": tk, "thread_id": run_id}}
        out = G.compile_graph(checkpointer=saver).invoke(start(tmp_path), config)
        assert out["__interrupt__"][0].value["kind"] == "review", out.get("trail")
        rows_before = len(tk.ledger.rows())
    del tk, out, config
    with SqliteSaver.from_conn_string(db) as saver:
        tk = Scripted(str(tmp_path), run_id=run_id)
        config = {"configurable": {"toolkit": tk, "thread_id": run_id}}
        graph = G.compile_graph(checkpointer=saver)
        assert graph.get_state(config).next == ("review",)
        out = graph.invoke(Command(resume={"verdict": "keep", "who": "later"}), config)
    assert out["outcome"] == "delivered"
    rows = tk.ledger.rows()
    assert len(rows) > rows_before and {r["run"] for r in rows} == {run_id}
    assert [r["seq"] for r in rows] == list(range(1, len(rows) + 1))
    assert [r for r in rows if r["kind"] == "review"][0]["who"] == "later"


# the CLI

def cli(monkeypatch, *scripts, cls=Scripted):
    """Point pipeline.run at scripted toolkits, one per process start, and keep them."""
    from pipeline import run as R
    made, queue = [], list(scripts)

    def toolkit(mode, run_dir, run_id):
        tk = cls(run_dir, run_id=run_id, **(queue.pop(0) if queue else {}))
        made.append(tk)
        return tk
    monkeypatch.setattr(R, "make_toolkit", toolkit)
    return R, made


def test_the_cli_waits_for_a_person_then_finishes_on_resume(tmp_path, monkeypatch):
    R, made = cli(monkeypatch)
    run_dir = str(tmp_path / "shoot")
    code = R.main(["--board", "b.json", "--spot", "s", "--mode", "live", "--run-dir", run_dir])
    assert R.WAITING == 3 and code == 3, "with nobody at a terminal the run must wait, not guess an answer"
    assert os.path.exists(os.path.join(run_dir, "checkpoint.sqlite"))
    waiting = [r for r in made[0].ledger.rows() if r["kind"] == "waiting"]
    assert waiting and waiting[-1]["trail"][-1] == "review", waiting
    code = R.main(["--resume", run_dir, "--answer", '{"verdict": "keep"}', "--who", "reviewer"])
    assert code == 0
    assert [r for r in made[1].ledger.rows() if r["kind"] == "review"][-1]["who"] == "reviewer"
    code = R.main(["--resume", run_dir, "--answer", '{"verdict": "keep"}'])
    assert code == 1, "a finished run is not waiting for anyone"


def test_the_cli_will_not_start_a_run_over_another(tmp_path, monkeypatch):
    R, made = cli(monkeypatch)
    run_dir = str(tmp_path / "shoot")
    assert R.main(["--board", "b.json", "--spot", "s", "--mode", "live", "--run-dir", run_dir]) == 3
    meta = open(os.path.join(run_dir, "run.json")).read()
    assert R.main(["--board", "b.json", "--spot", "s", "--mode", "live", "--run-dir", run_dir]) == 1
    assert open(os.path.join(run_dir, "run.json")).read() == meta, "a second start rewrote the first run's id"
    with pytest.raises(SystemExit):
        R.main(["--board", "b.json", "--spot", "s", "--from", "build"])


def test_an_answer_the_cli_cannot_act_on_is_refused_before_it_is_used(tmp_path, monkeypatch):
    R, made = cli(monkeypatch)
    run_dir = str(tmp_path / "shoot")
    assert R.main(["--board", "b.json", "--spot", "s", "--mode", "live", "--run-dir", run_dir]) == 3
    bad = '{"verdict": "withdraw", "back_to": "render", "reason": "r"}'
    assert R.main(["--resume", run_dir, "--answer", bad]) == 3
    assert not [r for r in made[1].ledger.rows() if r["kind"] == "review"], "a refused answer was recorded"
    assert R.main(["--resume", run_dir, "--answer", '{"verdict": "keep"}']) == 0


def test_a_preset_never_answers_what_a_person_has_to_look_at(tmp_path, monkeypatch):
    R, made = cli(monkeypatch, dict(ship_gate=[{"pass": False, "cause": "directional"}]),
                  dict(ad_gates=[REVIEW_FLAG]))
    first = str(tmp_path / "first")
    assert R.main(["--board", "b.json", "--spot", "s", "--mode", "live", "--run-dir", first, "--eye", "approve"]) == 3
    assert not [r for r in made[0].ledger.rows() if r["kind"] == "eye"], "a preset read a slit-scan nobody read"
    second = str(tmp_path / "second")
    assert R.main(["--board", "b.json", "--spot", "s", "--mode", "live", "--run-dir", second,
                   "--eye", "approve", "--review", "keep"]) == 0
    eye = [r for r in made[1].ledger.rows() if r["kind"] == "eye"][0]
    assert eye["preset"] is True and eye["answer"]["preset"] is True, eye


class Crashing(Scripted):
    def build(self, state):
        if self.script.get("crash"):
            raise RuntimeError("the crop assumed 1080p")
        return super().build(state)


def test_a_crash_inside_a_step_is_on_the_record_and_resume_says_how_to_re_enter(tmp_path, monkeypatch, capsys):
    R, made = cli(monkeypatch, dict(crash=[True]), dict(), dict(), cls=Crashing)
    run_dir = str(tmp_path / "shoot")
    assert R.main(["--board", "b.json", "--spot", "s", "--mode", "live", "--run-dir", run_dir]) == 1
    crashed = [r for r in made[0].ledger.rows() if r["kind"] == "crashed"]
    assert crashed and crashed[0]["step"] == "build" and "1080p" in crashed[0]["error"], crashed
    assert R.main(["--resume", run_dir, "--answer", '{"verdict": "keep"}']) == 1
    assert "--from build" in capsys.readouterr().out
    assert R.main(["--resume", run_dir, "--from", "build", "--reason", "crop fixed", "--review", "keep"]) == 0


def test_a_failed_step_is_re_entered_from_its_checkpoint_without_repeating_the_spend(tmp_path, monkeypatch):
    """The first live run died in the build on a defect since fixed. Re-entering from the
    checkpoint before the build must not render or voice anything again, since those cost
    money, and the ledger must say the run was re-entered and why."""
    R, made = cli(monkeypatch, dict(build=[{"pass": False}]))
    run_dir = str(tmp_path / "shoot")
    assert R.main(["--board", "b.json", "--spot", "s", "--mode", "live", "--run-dir", run_dir]) == 1
    renders_before = sum(1 for r in made[0].ledger.rows() if r["step"] == "render")
    code = R.main(["--resume", run_dir, "--from", "build", "--reason", "the crop was fixed", "--review", "keep"])
    assert code == 0
    rows = made[1].ledger.rows()
    assert sum(1 for r in rows if r["step"] == "render") == renders_before, "the resume rendered again"
    resumed = [r for r in rows if r["kind"] == "resumed"]
    assert resumed and resumed[0]["reason"] == "the crop was fixed" and resumed[0]["trail"][-1] == "closer"
    assert rows[-1]["kind"] == "close" and rows[-1]["outcome"] == "delivered"


def test_re_entry_starts_from_the_newest_checkpoint_before_the_step(tmp_path, monkeypatch):
    """A step that ran twice is re-entered where it last began. The oldest checkpoint would
    drop the nudge the eye asked for between the two builds."""
    lag = {**PASS_GATES, "lag_s": -0.2}
    R, made = cli(monkeypatch, dict(ad_gates=[lag]), dict(build=[{"pass": False}]), dict())
    run_dir = str(tmp_path / "shoot")
    assert R.main(["--board", "b.json", "--spot", "s", "--mode", "live", "--run-dir", run_dir]) == 3
    nudge = '{"verdict": "reject", "cause": "lag", "nudge": -0.14}'
    assert R.main(["--resume", run_dir, "--answer", nudge]) == 1
    assert R.main(["--resume", run_dir, "--from", "build", "--reason", "fixed", "--review", "keep"]) == 0
    assert handed(made[2], "build")[0]["nudge"] == -0.14, made[2].calls


def test_re_entering_a_waiting_run_says_which_wait_it_abandons(tmp_path, monkeypatch):
    R, made = cli(monkeypatch, dict(ship_gate=[{"pass": False, "cause": "replay"}]), dict())
    run_dir = str(tmp_path / "shoot")
    assert R.main(["--board", "b.json", "--spot", "s", "--mode", "live", "--run-dir", run_dir]) == 3
    assert R.main(["--resume", run_dir, "--from", "ship_gate", "--reason", "the gate changed", "--review", "keep"]) == 0
    resumed = [r for r in made[1].ledger.rows() if r["kind"] == "resumed"][0]
    assert resumed["abandoned"] == "eye" and resumed["reason"] == "the gate changed", resumed


def test_an_answer_with_no_name_is_refused(tmp_path, monkeypatch):
    """The ledger records who answered. With no account name to fall back on, an unnamed
    answer is refused rather than written as "unknown", which reads like a name."""
    R, made = cli(monkeypatch)
    monkeypatch.delenv("USER", raising=False)
    run_dir = str(tmp_path / "shoot")
    assert R.main(["--board", "b.json", "--spot", "s", "--mode", "live", "--run-dir", run_dir]) == 3
    assert R.main(["--resume", run_dir, "--answer", '{"verdict": "keep"}']) == 3
    assert R.main(["--resume", run_dir, "--answer", '{"verdict": "keep"}', "--who", "a person"]) == 0
    assert [r for r in made[-1].ledger.rows() if r["kind"] == "review"][-1]["who"] == "a person"
