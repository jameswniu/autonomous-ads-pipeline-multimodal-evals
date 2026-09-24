"""The pipeline as a LangGraph: seven steps, their gates as conditional edges, and a person twice.

This is the compiled form of the agent loop that ran the August shoots. That loop was
a model reading a long, dated doctrine file and deciding each next step, with Claude
Code hooks as the gates. Once the runs converged on one path, the path became this
graph: the step order and the gates are edges and plain code, the parts that vary per
brief stay inside fixed nodes, and the two places a person decides are LangGraph
interrupts. The eye answers what a gate cannot rule on before anything ships, a mouth
REVIEW, a lag worth a nudge, a prop the edge probe saw cut by the frame, a directional
scene or a replay. The review comes after delivery, where the August ledgers show the
author actually looked: a delivered cut can be withdrawn and sent back to the step that
fixes it, because delivery is reversible.

The graph does not claim to be what ran in August, it is what that run became.
pipeline/replay.py checks every transition the August ledgers recorded against the
edges below and prints what those ledgers never recorded.

Routing is here, in plain functions, and nowhere else. The nodes do the work through
a toolkit (pipeline/toolkit.py) and report a verdict; the functions below read the
verdict and pick the next step. Every stop, from any gate, closes the run in the ledger,
so a run that halted is on the record the same way a run that shipped is.
"""
import operator
from typing import Annotated, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from pipeline.steps import BY_NODE

# Bounds on every loop. An unattended run that can loop can spend without end, so each
# loop has a ceiling, and hitting it stops the run for a person instead of retrying.
#
# The scene re-roll count is the source's own number: "re-roll ONLY visible breakage,
# once." Here the render step re-rolls only what failed to come back at all, a refusal, a
# rejection or no video, and each broken scene gets that one retry. The eye may send a
# scene or the closer back once per run. The source set no number for rebuilds: in August
# a person directed up to seven builds of one spot by hand. MAX_BUILDS bounds the rebuilds
# the eye can ask for with a nudge, so a lag three builds have not fixed stops for a
# person, since it is not a nudge's to fix. Rebuilds after delivery are counted as
# withdrawals instead: three is what ads7 took to land its v4 cuts, each one a person's
# call, so the bound admits the worst run on the record and stops a fourth.
MAX_SCENE_REROLLS = 1
MAX_BUILDS = 3
MAX_EYE_REJECTS = 1
MAX_WITHDRAWALS = 3

# The source fixes a closer lag of 0.12 s or more with a nudge in the build, measured on the
# raw take. The graph measures the built master instead, where the probe scatters by about
# 60 ms from build to build, so this is the same number applied later and read more loosely.
# The probe PASSes lags up to 0.20 s, so without this the eye would never see them. It sends
# them to a person rather than nudging on its own: the probe misread lively faces by 0.2 s on
# 2026-08-29 and the automatic nudge shipped the desync it meant to fix.
LAG_FIX = 0.12

# What a person's answer may change for the steps that follow it. Anything else in an answer is
# recorded and ignored, so an answer cannot, for example, carry a directional override forward
# onto a master nobody has read.
CHANGE_KEYS = ("scene", "prompt", "reason", "look", "engine", "nudge")

# A scene, its prompt and the reason for redoing it travel together and are spent by the render
# that redoes them. An answer naming a scene replaces all three, so a prompt written for one
# scene is never paid for on another.
SCENE_KEYS = ("scene", "prompt", "reason")

# Overrides a person gives for one master. A new build or a withdrawal drops them, so an
# override never outlives the master it was read on.
APPROVALS = ("arrow_ok", "replay_ok")

# Every edge the README figure leaves out, declared so a test can check the figure
# against the compiled graph minus exactly these. Stops are left out to keep the loop
# readable, and the prose under the figure says so.
STOP = "ledger"


class ShootState(TypedDict, total=False):
    board: str            # path to the boards.json the spot is read from
    spot: str             # the spot's key inside the board
    run_dir: str          # where this run writes its ledger and artifacts
    mode: str             # "dry" stops before the first spend, "live" spends
    attempts: dict        # loop name -> times taken
    verdict: dict         # step -> the last verdict that step reported
    artifacts: dict       # artifact name -> path
    changes: dict         # what people asked for that still holds: a scene to redo, a nudge, a look
    outcome: str          # set by the ledger step when the run closes
    trail: Annotated[list, operator.add]  # every step entered, in order


def _tools(config):
    return config["configurable"]["toolkit"]


def _merge(state, key, update):
    out = dict(state.get(key) or {})
    out.update(update)
    return out


def _bump(state, loop):
    attempts = dict(state.get("attempts") or {})
    attempts[loop] = attempts.get(loop, 0) + 1
    return attempts


def _left(state, loop, ceiling):
    return (state.get("attempts") or {}).get(loop, 0) < ceiling


def _without(changes, keys):
    return {k: v for k, v in (changes or {}).items() if k not in keys}


def _apply(changes, answer):
    """Fold what an answer asks for into what is already asked. A nudge, a look or an engine
    replaces the one before it. A scene brings its own prompt and reason, or none."""
    out = dict(changes or {})
    if answer.get("scene"):
        out = _without(out, SCENE_KEYS)
        out.update({k: answer[k] for k in SCENE_KEYS if answer.get(k)})
    out.update({k: answer[k] for k in CHANGE_KEYS if k not in SCENE_KEYS and k in answer})
    return out


def unseen_flags(state):
    """Edge-clip flags on the scenes as they stand that no person has looked at yet. The probe
    that raises them is a flagger, not a gate: it names the seconds and the eye rules. A flag is
    seen on one scene's take, so the same words on another scene, or on a new take of the same
    scene, are asked about again."""
    flags = ((state.get("verdict") or {}).get("render") or {}).get("flags") or {}
    seen = (state.get("changes") or {}).get("flags_seen")
    seen = seen if isinstance(seen, dict) else {}
    return {scene: text for scene, text in flags.items() if seen.get(scene) != text}


def answer_problem(packet, answer):
    """Why an answer cannot be acted on, or None. The graph asks again rather than guessing
    what a person meant, and nothing is recorded until the answer is one it can act on."""
    if not isinstance(answer, dict):
        return "an answer is a JSON object"
    verdict, cause = answer.get("verdict"), answer.get("cause")
    if packet.get("kind") == "eye":
        if verdict == "approve":
            if packet.get("cause") == "replay" and not answer.get("reason"):
                return "approving a replay needs a reason, what in the scene keeps it from showing"
            return None
        if verdict != "reject":
            return 'the eye answers "approve" or "reject"'
        if cause not in ("scene", "closer", "lag", "other"):
            return 'a rejection names its cause, "scene", "closer", "lag" or "other"'
        if cause == "scene" and not answer.get("scene"):
            return "a scene rejection names the scene to redo"
        if cause == "closer" and not (answer.get("look") or answer.get("engine")):
            return "a closer rejection names a new look or engine, since the same ones render the same mouth"
        if cause == "lag" and not isinstance(answer.get("nudge"), (int, float)):
            return "a lag rejection gives the nudge in seconds"
        return None
    if packet.get("kind") == "review":
        if verdict == "keep":
            return None
        if verdict != "withdraw":
            return 'the review answers "keep" or "withdraw"'
        back = answer.get("back_to")
        if back not in ("render", "closer", "build"):
            return 'a withdrawal names the step that fixes it, "render", "closer" or "build"'
        if not answer.get("reason"):
            return "a withdrawal says why, for the record"
        if back == "render" and not answer.get("scene"):
            return "a withdrawal to the render names the scene to redo"
        if back == "closer" and not (answer.get("look") or answer.get("engine")):
            return "a withdrawal to the closer names a new look or engine"
        return None
    return None


def _ask(packet):
    """Interrupt for a person, and ask again with the problem named until the answer is one the
    graph can act on. The node re-runs from its start on every resume, so nothing with a side
    effect may come before this returns."""
    answer = interrupt(packet)
    problem = answer_problem(packet, answer)
    while problem:
        answer = interrupt(dict(packet, problem=problem))
        problem = answer_problem(packet, answer)
    return answer


# nodes: each does its step through the toolkit and reports a verdict

def board(state, config):
    v = _tools(config).board(state)
    return {"verdict": _merge(state, "verdict", {"board": v}), "trail": ["board"]}


def render(state, config):
    v = _tools(config).render(state)
    # Flags stand per scene. A scene rendered again replaces its own and keeps the others'.
    before = ((state.get("verdict") or {}).get("render") or {}).get("flags") or {}
    flags = {s: t for s, t in before.items() if s not in set(v.get("rendered") or [])}
    flags.update(v.get("flags") or {})
    v = dict(v, flags=flags)
    changes = dict(state.get("changes") or {})
    # A new take is a new picture, so what a person saw on the old one no longer counts. A toolkit
    # that does not say which takes are new has every scene it rendered read as new.
    fresh = set(v["fresh"] if "fresh" in v else v.get("rendered") or [])
    if isinstance(changes.get("flags_seen"), dict) and fresh:
        changes["flags_seen"] = {s: t for s, t in changes["flags_seen"].items() if s not in fresh}
    if changes.get("scene") and changes["scene"] not in (v.get("failed") or []):
        changes = _without(changes, SCENE_KEYS)    # spent: the scene a person asked for came back
    out = {"verdict": _merge(state, "verdict", {"render": v}), "trail": ["render"], "changes": changes,
           "artifacts": _merge(state, "artifacts", v.get("artifacts", {}))}
    if v.get("failed"):
        attempts = dict(state.get("attempts") or {})
        for scene in v["failed"]:
            attempts[f"reroll:{scene}"] = attempts.get(f"reroll:{scene}", 0) + 1
        out["attempts"] = attempts
    return out


def closer(state, config):
    v = _tools(config).closer(state)
    return {"verdict": _merge(state, "verdict", {"closer": v}), "trail": ["closer"],
            "artifacts": _merge(state, "artifacts", v.get("artifacts", {}))}


def build(state, config):
    v = _tools(config).build(state)
    return {"verdict": _merge(state, "verdict", {"build": v}), "trail": ["build"],
            "attempts": _bump(state, "build"), "changes": _without(state.get("changes"), APPROVALS),
            "artifacts": _merge(state, "artifacts", v.get("artifacts", {}))}


def ad_gates(state, config):
    v = _tools(config).ad_gates(state)
    return {"verdict": _merge(state, "verdict", {"ad_gates": v}), "trail": ["ad_gates"]}


def eye(state, config):
    """A person rules on what a gate could not, before anything ships.

    The resume value is {"verdict": "approve" | "reject", "cause": "scene" | "closer" | "lag" |
    "other", "who": "<name>"}, with "scene" (and optionally "prompt") naming the scene to redo,
    "look" or "engine" what a new closer renders on, or "nudge" the seconds to shift the closer
    in the build. Approving a replay needs a "reason", what in the scene keeps the replay from
    showing, which is the logged override the ship gate's REPLAYOK stands for. Approving a
    directional scene is the override its --arrow-ok stands for. The packet carries the
    evidence of the gate that asked, the edge flags nobody has seen, and the fixes already in
    force, so the person judges the flag the gate raised and not a fresh impression.
    """
    asked_by = (state.get("trail") or ["?"])[-1]
    evidence = (state.get("verdict") or {}).get(asked_by) or {}
    flags = unseen_flags(state)
    changes = dict(state.get("changes") or {})
    packet = {"kind": "eye", "asked_by": asked_by, "master": (state.get("artifacts") or {}).get("master"),
              "evidence": evidence, "flags": flags,
              "in_force": {k: changes[k] for k in ("nudge", "look", "engine") if k in changes}}
    if asked_by == "ship_gate":
        packet["cause"] = evidence.get("cause")
    answer = _ask(packet)
    _tools(config).record_eye(state, dict(answer, asked_by=asked_by))
    out = {"verdict": _merge(state, "verdict", {"eye": answer}), "trail": ["eye"]}
    if answer["verdict"] == "approve":
        who = answer.get("who", "unknown")
        if packet.get("cause") == "directional":
            changes["arrow_ok"] = who
        if packet.get("cause") == "replay":
            changes["replay_ok"] = f"{answer['reason']}, read at the eye by {who}"
        if flags:
            seen = changes.get("flags_seen")
            changes["flags_seen"] = {**(seen if isinstance(seen, dict) else {}), **flags}
    else:
        changes = _apply(changes, answer)
        if answer.get("cause") in ("scene", "closer"):
            out["attempts"] = _bump(state, "eye_reject")
    out["changes"] = changes
    return out


def ship_gate(state, config):
    v = _tools(config).ship_gate(state)
    return {"verdict": _merge(state, "verdict", {"ship_gate": v}), "trail": ["ship_gate"]}


def deliver(state, config):
    v = _tools(config).deliver(state)
    return {"verdict": _merge(state, "verdict", {"deliver": v}), "trail": ["deliver"],
            "artifacts": _merge(state, "artifacts", v.get("artifacts", {}))}


def review(state, config):
    """The person on the loop, after delivery. The run waits here for their word.

    The resume value is {"verdict": "keep" | "withdraw", "back_to": "render" | "closer" |
    "build", "reason": "<why>", "who": "<name>"}, plus what the fix needs, a scene to redo,
    a look or an engine for the closer, or a nudge. A withdrawal goes on the record with its
    reason before the run goes back, which is what the August withdrawals wrote by hand.
    """
    artifacts = state.get("artifacts") or {}
    packet = {"kind": "review", "delivered": artifacts.get("delivered") or artifacts.get("master")}
    answer = _ask(packet)
    _tools(config).record_review(state, answer)
    out = {"verdict": _merge(state, "verdict", {"review": answer}), "trail": ["review"]}
    if answer.get("verdict") == "withdraw":
        out["attempts"] = _bump(state, "withdrawal")
        # What was asked for earlier still holds, a nudge the eye set is not lost to a scene fix,
        # and an override never outlives the master it was given for.
        out["changes"] = _apply(_without(state.get("changes"), APPROVALS), answer)
    return out


def ledger(state, config):
    """Close the run on the record, shipped or stopped, with the reason."""
    outcome = _tools(config).close(state)
    return {"outcome": outcome, "trail": ["ledger"]}


# routing: the gates, as plain functions over the verdicts

def after_board(state):
    return "render" if state["verdict"]["board"]["pass"] else STOP


def after_render(state):
    v = state["verdict"]["render"]
    if v.get("dry"):
        return STOP
    # A request the vendor never confirmed may have been billed. Nothing is sent again until a
    # person has looked, so the run stops, whatever else came back.
    if v.get("unconfirmed"):
        return STOP
    if not v.get("failed"):
        return "closer"
    # Each broken scene gets its own re-roll; one still broken after it stops the run.
    attempts = state.get("attempts") or {}
    within = all(attempts.get(f"reroll:{s}", 0) <= MAX_SCENE_REROLLS for s in v["failed"])
    return "render" if within else STOP


def after_closer(state):
    return "build" if state["verdict"]["closer"]["pass"] else STOP


def after_build(state):
    return "ad_gates" if state["verdict"]["build"]["pass"] else STOP


def after_ad_gates(state):
    """A caption or placement fault stops the run. The build is deterministic, cues and
    placement come from the same script and read-back every time, so rebuilding the same
    inputs repeats the fault; August fixed these by changing the build and rebuilding, which
    is a person's edit and then a run resumed from the build. A mouth that does not track its
    audio at all, FAIL or no face, also stops: the same look and audio render the same mouth,
    and a new look is made outside this repository. A reading nobody could take stops too.
    A REVIEW, a lag, or an edge flag nobody has seen goes to the eye."""
    v = state["verdict"]["ad_gates"]
    if v.get("unreadable") or "unreadable" in (v.get("caption"), v.get("drift"), v.get("mouth")):
        return STOP
    if v["caption"] == "fail" or v["drift"] == "fail":
        return STOP
    if v["mouth"] in ("fail", "noface"):
        return STOP
    if v["mouth"] == "review" or abs(v.get("lag_s") or 0) >= LAG_FIX or unseen_flags(state):
        return "eye"
    return "ship_gate"


def after_eye(state):
    v = state["verdict"]["eye"]
    if v.get("verdict") == "approve":
        return "ship_gate"
    if v.get("cause") in ("scene", "closer") and _left(state, "eye_reject", MAX_EYE_REJECTS + 1):
        return "render" if v["cause"] == "scene" else "closer"
    if v.get("cause") == "lag" and _left(state, "build", MAX_BUILDS):
        return "build"
    return STOP


def after_ship_gate(state):
    """The last check before anything leaves fails closed.

    Nothing here loops. A remaster would repeat the same loudnorm pass, and a boxed frame on
    an ad master is boxed b-roll, since the closer is only its tail and renders to cover, so
    loudness, peak, a boxed frame or unreadable input stop the run for a person. Two flags
    the source hands to a reader instead. A directional scene: "READ the slit-scan before
    --arrow-ok". A replay: visibility "is DECLARED, never inferred", by someone who has read
    the scan around the turn. Each goes to the eye once, and an approval re-runs the gate with
    the override on the record. The time-of-day check is waived for ad fiction on every run
    and logged by the toolkit, per the source.
    """
    v = state["verdict"]["ship_gate"]
    if v["pass"]:
        return "deliver"
    changes = state.get("changes") or {}
    if v.get("cause") == "directional" and not changes.get("arrow_ok"):
        return "eye"
    if v.get("cause") == "replay" and not changes.get("replay_ok"):
        return "eye"
    return STOP


def after_review(state):
    """Kept closes the run delivered. A withdrawal goes back to the step its reason names."""
    v = state["verdict"]["review"]
    if v.get("verdict") != "withdraw" or not _left(state, "withdrawal", MAX_WITHDRAWALS + 1):
        return STOP
    return v["back_to"] if v.get("back_to") in ("render", "closer", "build") else STOP


# The graph's edges, declared as data so the README figure and the tests read the same
# map the compiler does. Each gate lists every place it can send a run.
ROUTES = {
    "board": (after_board, ["render", STOP]),
    "render": (after_render, ["render", "closer", STOP]),
    "closer": (after_closer, ["build", STOP]),
    "build": (after_build, ["ad_gates", STOP]),
    "ad_gates": (after_ad_gates, ["ship_gate", "eye", STOP]),
    "eye": (after_eye, ["ship_gate", "render", "closer", "build", STOP]),
    "ship_gate": (after_ship_gate, ["deliver", "eye", STOP]),
    "review": (after_review, ["render", "closer", "build", STOP]),
}

NODES = {"board": board, "render": render, "closer": closer, "build": build,
         "ad_gates": ad_gates, "eye": eye, "ship_gate": ship_gate,
         "deliver": deliver, "review": review, "ledger": ledger}

# Edges the README figure leaves out, each for a stated reason. Everything else in the
# compiled graph must be drawn, and nothing may be drawn that is not compiled. The review
# closing a kept delivery is how a run normally ends, so the figure draws that one.
STOP_EDGES = {(src, STOP) for src, (_, targets) in ROUTES.items() if STOP in targets and src != "review"}
# Drawn but not compiled: the next run re-derives its thresholds from this run's ledger.
# It crosses a run boundary, so it is a dotted line in the figure and not an edge here.
CROSS_RUN_EDGES = {("ledger", "board")}


def build_graph():
    missing = set(BY_NODE) - set(NODES)
    assert not missing, f"steps with no node: {missing}"
    g = StateGraph(ShootState)
    for name, fn in NODES.items():
        g.add_node(name, fn)
    g.add_edge(START, "board")
    for src, (route, targets) in ROUTES.items():
        g.add_conditional_edges(src, route, {t: t for t in targets})
    g.add_edge("deliver", "review")
    g.add_edge("ledger", END)
    return g


def compile_graph(checkpointer=None):
    return build_graph().compile(checkpointer=checkpointer)


def edges():
    """The compiled graph's step-to-step edges, without the start and end markers."""
    g = compile_graph().get_graph()
    return {(e.source, e.target) for e in g.edges
            if e.source not in ("__start__", "__end__") and e.target not in ("__start__", "__end__")}
