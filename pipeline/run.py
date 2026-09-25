"""Run one spot through the graph, or resume a run that is waiting for a person.

    python -m pipeline.run --board shoots/graph-zai-cast/boards.json --spot zai --mode dry
    python -m pipeline.run --board <boards.json> --spot <name> --mode live --run-dir shoots/<run>
    python -m pipeline.run --resume shoots/<run> --answer '{"verdict": "keep"}'
    python -m pipeline.run --resume shoots/<run> --from build --reason "<what was fixed>"

Dry mode needs no keys and spends nothing. The board gate runs for real, then the run records
the scene requests a live run would send, with their cost, and stops. Live mode spends, and
needs the environment listed at the top of pipeline/live.py, checked before anything starts.

A live run checkpoints every step to checkpoint.sqlite in its directory. When it reaches the
eye or the review and nobody is at a terminal to answer, it prints what the person needs to
see and exits 3, and the run waits there for as long as the person takes, until it is resumed
with an answer. An answer the graph could not act on is refused here, before it is used, and
the run keeps waiting. --eye and --review answer ahead of time, marked as presets on the
ledger, and never for a flag a person has to read off a picture: a directional scene, a
replay, or a prop the edge probe saw cut by the frame.

--from re-enters a run from its checkpoint just before a step, after a defect in that step is
fixed, without paying again for the steps before it. Re-entering is a person's decision to
spend again, so the loop budgets start from the checkpoint re-entered, and the resumed row
records them before and after, along with any wait the re-entry abandons.
"""
import argparse
import contextlib
import datetime as dt
import json
import os
import sys
import traceback
import uuid

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from pipeline.graph import answer_problem, compile_graph
from pipeline.toolkit import PLACEHOLDER, ROOT, DryToolkit, cast_ok, load_spot

WAITING = 3

EYE_PRESETS = {"approve": {"verdict": "approve"},
               "reject": {"verdict": "reject", "cause": "other"}}
REVIEW_PRESETS = {"keep": {"verdict": "keep"}}


def make_toolkit(mode, run_dir, run_id):
    if mode == "live":
        from pipeline.live import LiveToolkit  # only live needs the vendor clients
        return LiveToolkit(run_dir, run_id)
    return DryToolkit(run_dir, run_id)


@contextlib.contextmanager
def checkpointer(mode, run_dir):
    """A dry run never waits, so it keeps its state in memory. A live run can wait days for
    a person, so its state goes to disk after every step."""
    if mode == "dry":
        yield InMemorySaver()
        return
    from langgraph.checkpoint.sqlite import SqliteSaver
    with SqliteSaver.from_conn_string(os.path.join(run_dir, "checkpoint.sqlite")) as saver:
        yield saver


def needs_a_reader(packet):
    """A question whose evidence is a picture: only someone who has looked can answer it."""
    return packet["kind"] == "eye" and (packet.get("asked_by") == "ship_gate" or bool(packet.get("flags")))


def ask(packet):
    """A person at a terminal answers here, having been shown the packet. Anything else waits."""
    print(f"\nThe {packet['kind']} decides. What it is shown:")
    print(json.dumps(packet, indent=2, default=str))
    if packet["kind"] == "eye":
        hint = 'approve, or JSON such as {"verdict": "reject", "cause": "lag", "nudge": -0.12}'
    else:
        hint = 'keep, or JSON such as {"verdict": "withdraw", "back_to": "closer", "look": "...", "reason": "..."}'
    text = input(f"{hint}\n> ").strip()
    presets = EYE_PRESETS if packet["kind"] == "eye" else REVIEW_PRESETS
    return dict(presets[text]) if text in presets else json.loads(text)


def answer_for(packet, a, once):
    """The answer to give, with who gave it: the answer's own name, else --who, which defaults
    to the account at the terminal."""
    answer = None
    if once:
        answer = once.pop()
    elif not needs_a_reader(packet) and not packet.get("problem"):
        preset = EYE_PRESETS.get(a.eye) if packet["kind"] == "eye" else REVIEW_PRESETS.get(a.review)
        if preset:
            answer = dict(preset, preset=True)
    if answer is None and sys.stdin.isatty():
        answer = ask(packet)
    if isinstance(answer, dict):
        answer = dict(answer, who=answer.get("who") or a.who)
    return answer


def check(packet, answer, meta):
    """Why an answer cannot be acted on, or None: the graph's own rules, and a scene the board
    does not have. Checked before the answer is used, so a bad one costs nothing."""
    problem = answer_problem(packet, answer)
    if problem is None and not answer.get("who"):
        problem = "the ledger records who answered, so give --who"
    if problem or not answer.get("scene"):
        return problem
    try:
        _, spot_def = load_spot(os.path.join(ROOT, meta["board"]), meta["spot"])
    except (OSError, KeyError, ValueError):
        return None     # the toolkit checks the scene again before anything is sent
    scenes = spot_def.get("scenes", {})
    key = str(answer["scene"]).strip()
    key = key[len(meta["spot"]) + 1:] if key.startswith(meta["spot"] + "-") else key
    if key not in scenes:
        return f"the answer asks for scene {answer['scene']!r}; this spot's scenes are {', '.join(sorted(scenes))}"
    if answer.get("prompt") and not cast_ok(answer["prompt"]):
        return (f"the new prompt shows a person with no {PLACEHOLDER}, and every person on screen is the presenter, "
                f"so write {PLACEHOLDER} where she appears")
    return None


def invoke(graph, arg, config, thread, toolkit):
    """Run the graph. A crash inside a step still goes on the record, as a crashed row naming
    the step and the error, so a run that died is never mistaken for one that is waiting."""
    try:
        return graph.invoke(arg, config)
    except Exception as exc:  # noqa: BLE001, the record is written and the error re-shown below
        state = graph.get_state(thread)
        step = state.next[0] if state.next else "?"
        toolkit.ledger.append("crashed", step, error=toolkit.clean(f"{type(exc).__name__}: {exc}")[-600:],
                              trail=list((state.values or {}).get("trail", [])) + [step])
        traceback.print_exc()
        print(f"\nthe run stopped inside {step}. Once the cause is fixed, re-enter it with --from {step}.")
        return None


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--board")
    ap.add_argument("--spot")
    ap.add_argument("--mode", choices=("dry", "live"), default="dry")
    ap.add_argument("--run-dir", default=None)
    ap.add_argument("--resume", metavar="RUN_DIR", default=None, help="continue a run waiting for a person")
    ap.add_argument("--answer", default=None, help="JSON answer to the question the run is waiting on")
    ap.add_argument("--from", dest="from_step", default=None, metavar="STEP",
                    help="with --resume, re-enter the run from its checkpoint just before STEP")
    ap.add_argument("--reason", default="", help="why the run is being re-entered, for the ledger")
    ap.add_argument("--eye", choices=tuple(EYE_PRESETS), default=None)
    ap.add_argument("--review", choices=tuple(REVIEW_PRESETS), default=None)
    ap.add_argument("--who", default=os.environ.get("USER"), help="who is answering, for the ledger")
    a = ap.parse_args(argv)
    if a.from_step and not a.resume:
        ap.error("--from re-enters an existing run, so it needs --resume <run dir>")

    if a.resume:
        run_dir = a.resume
        with open(os.path.join(run_dir, "run.json")) as fh:
            meta = json.load(fh)
    else:
        if not (a.board and a.spot):
            ap.error("--board and --spot are required unless --resume is given")
        stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        # Dry runs are scratch and land in the ignored reports directory. A live run that is
        # meant to be kept names its own directory under shoots/ so its ledger is committed.
        run_dir = a.run_dir or os.path.join(ROOT, ".reports", "runs", f"{stamp}-{a.spot}-{a.mode}")
        if os.path.exists(os.path.join(run_dir, "run.json")):
            print(f"{run_dir} already holds a run. Resume it with --resume, or start a new one in its own directory.")
            return 1
        meta = {"run": uuid.uuid4().hex[:12], "board": os.path.relpath(os.path.abspath(a.board), ROOT),
                "spot": a.spot, "mode": a.mode}

    try:
        toolkit = make_toolkit(meta["mode"], run_dir, meta["run"])
    except RuntimeError as exc:
        print(f"the run cannot start: {exc}")
        return 1
    if not a.resume:
        with open(os.path.join(run_dir, "run.json"), "w") as fh:
            json.dump(meta, fh, indent=1)

    thread = {"configurable": {"toolkit": toolkit, "thread_id": meta["run"]}}
    once = [json.loads(a.answer)] if a.answer else []
    with checkpointer(meta["mode"], run_dir) as saver:
        graph = compile_graph(checkpointer=saver)
        if a.from_step:
            latest = graph.get_state(thread)
            # The newest checkpoint before the step, so a step that ran twice is re-entered
            # where it last began, not where it first did.
            target = next((c for c in graph.get_state_history(thread) if c.next == (a.from_step,)), None)
            if target is None:
                print(f"no checkpoint of this run stops before {a.from_step}")
                return 1
            pending = latest.tasks[0].interrupts if latest.next and latest.tasks else ()
            toolkit.ledger.append("resumed", a.from_step, reason=a.reason, trail=target.values.get("trail", []),
                                  abandoned=pending[0].value.get("kind") if pending else None,
                                  attempts_before=(latest.values or {}).get("attempts", {}),
                                  attempts_after=target.values.get("attempts", {}))
            result = invoke(graph, None, {"configurable": {**target.config["configurable"], "toolkit": toolkit}},
                            thread, toolkit)
        elif a.resume:
            waiting = graph.get_state(thread)
            if not waiting.next:
                print("this run is not waiting for anyone")
                return 1
            pending = waiting.tasks[0].interrupts if waiting.tasks else ()
            if not pending:
                step = waiting.next[0]
                print(f"this run stopped inside {step} and nothing is waiting for an answer. Once the cause is "
                      f"fixed, re-enter it with --from {step}.")
                return 1
            packet = pending[0].value
            answer = answer_for(packet, a, once)
            if answer is None:
                print(f"the {packet['kind']} is still waiting; give --answer")
                return WAITING
            problem = check(packet, answer, meta)
            if problem:
                print(f"that answer cannot be acted on: {problem}. The {packet['kind']} is still waiting.")
                return WAITING
            result = invoke(graph, Command(resume=answer), thread, thread, toolkit)
        else:
            state = {"board": os.path.join(ROOT, meta["board"]), "spot": meta["spot"], "run_dir": run_dir,
                     "mode": meta["mode"], "attempts": {}, "verdict": {}, "artifacts": {}}
            result = invoke(graph, state, thread, thread, toolkit)
        while result is not None and "__interrupt__" in result:
            packet = result["__interrupt__"][0].value
            answer = answer_for(packet, a, once)
            problem = check(packet, answer, meta) if answer is not None else None
            if answer is None or problem:
                if problem:
                    print(f"that answer cannot be acted on: {problem}.")
                trail = (graph.get_state(thread).values or {}).get("trail", [])
                toolkit.ledger.append("waiting", packet["kind"], trail=trail + [packet["kind"]])
                print(f"\nWaiting for the {packet['kind']}. What it is shown:")
                print(json.dumps(packet, indent=2, default=str))
                print(f"\nResume with:\n  python -m pipeline.run --resume {os.path.relpath(run_dir, ROOT)} "
                      f"--answer '{{\"verdict\": \"...\"}}'")
                return WAITING
            result = invoke(graph, Command(resume=answer), thread, thread, toolkit)

    if result is None:
        return 1
    print(" -> ".join(result.get("trail", [])))
    print(f"outcome: {result.get('outcome')}")
    print(f"ledger:  {os.path.relpath(toolkit.ledger.path, ROOT)}")
    return 0 if result.get("outcome") in ("delivered", "dry: stopped before the first spend") else 1


if __name__ == "__main__":
    sys.exit(main())
