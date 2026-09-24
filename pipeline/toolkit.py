"""What the graph's nodes act through: the repo's own gates, and the engines that spend.

The graph decides where a run goes next; the toolkit does the work of each step and
reports a verdict. Keeping them apart is what lets the routing be tested without media
or money: a test hands the graph a toolkit that returns scripted verdicts and checks the
path the graph takes.

Three toolkits share this base. DryToolkit runs the free checks for real and stops before
the first spend. LiveToolkit (pipeline/live.py) spends. The tests use a scripted one.
"""
import json
import os
import subprocess
import sys
import tempfile

from pipeline.ledger import Ledger, fingerprint, new_request_id

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# The engine a scene renders on when neither the spot nor the board names one. The source
# says "shoot every ad on Omni unless he names another engine."
DEFAULT_ENGINE = "google/gemini-omni-flash"

# What a scene costs on each engine, in dollars, as recorded when the August shoots ran.
# Dry runs report the spend a live run would make before anyone commits to it.
PRICE_PER_SCENE = {
    "google/gemini-omni-flash": 0.63,
    "alibaba/wan-3.0/text-to-video": 1.00,
    "bytedance/seedance-2.0/text-to-video": 1.00,
}

# Keys whose values are identities, at any depth in an answer or a verdict. The ledger gets
# their fingerprint, never the id.
IDENTITY_KEYS = ("look", "avatar", "avatar_id", "voice", "voice_id")


def load_spot(board_path, spot):
    with open(board_path) as fh:
        board = json.load(fh)
    spots = board.get("spots", {})
    if spot not in spots:
        raise KeyError(f"{spot!r} is not a spot in {board_path}; it has {sorted(spots)}")
    return board, spots[spot]


def engine_for(board, spot_def):
    return spot_def.get("engine") or board.get("engine") or DEFAULT_ENGINE


def scene_prompt(board, scene_text):
    """The prompt the August shoots sent: the scene line, a blank line, the guard verbatim.

    Checked against the ledger, not assumed: every first-roll request in shoots/ads5 is
    exactly this string.
    """
    guard = board.get("guard", "")
    return f"{scene_text}\n\n{guard}" if guard else scene_text


class Toolkit:
    def __init__(self, run_dir, run_id=None):
        self.run_dir = os.path.abspath(run_dir)
        self.ledger = Ledger(run_dir, run_id)

    def repo(self, *args, timeout=600):
        """Run one of the repo's own scripts, with this interpreter for Python ones."""
        cmd = [sys.executable, *args] if args[0].endswith(".py") else ["bash", *args]
        return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=timeout)

    # What reaches the ledger. A kept run's ledger is committed, so no local path and no
    # identity id may reach it, whichever step or person produced the text.

    def clean(self, text):
        """The run's own paths become relative to it, the repository's relative to the repository,
        temporary files lose their machine-specific prefix, and the home directory becomes ~."""
        text = str(text)
        for base, short in ((self.run_dir, ""), (ROOT, "")):
            text = text.replace(base + os.sep, short).replace(base, ".")
        for tmp in {os.path.realpath(tempfile.gettempdir()), tempfile.gettempdir(), "/private/tmp", "/tmp"}:
            text = text.replace(tmp.rstrip(os.sep) + os.sep, "<tmp>/")
        return text.replace(os.path.expanduser("~"), "~")

    def scrub(self, value):
        """An answer or a verdict made safe for the ledger, at any depth: identity ids become
        fingerprints and every string is cleaned."""
        if isinstance(value, dict):
            return {k: (fingerprint(v) if k in IDENTITY_KEYS and isinstance(v, str) and v else self.scrub(v))
                    for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [self.scrub(v) for v in value]
        if isinstance(value, str):
            return self.clean(value)
        return value

    # --- Board is free and runs for real in every toolkit -----------------------------

    def board(self, state):
        board_path, spot = state["board"], state["spot"]
        r = self.repo("gates/board_probe.py", board_path, "--json")
        try:
            report = json.loads(r.stdout)
        except json.JSONDecodeError:
            verdict = {"pass": False, "reason": "board probe gave no readable verdict",
                       "stderr": self.clean(r.stderr[-400:])}
            self.ledger.append("gate", "board", spot=spot, **verdict)
            return verdict
        checks = report["spots"].get(spot, {}).get("checks")
        if checks is None:
            verdict = {"pass": False, "reason": f"{spot} is not on the board"}
        else:
            failed = sorted(k for k, ok in checks.items() if not ok)
            verdict = {"pass": not failed, "checks": checks, "failed": failed}
        self.ledger.append("gate", "board", spot=spot, board=os.path.relpath(board_path, ROOT), **verdict)
        return verdict

    # --- What a person said -------------------------------------------------------------

    def record_eye(self, state, answer):
        """The whole answer is kept, nested, so no key in it can collide with the row's own."""
        a = self.scrub(answer)
        self.ledger.append("eye", "eye", spot=state.get("spot"), verdict=a.get("verdict"), cause=a.get("cause"),
                           who=a.get("who"), asked_by=a.get("asked_by"), preset=bool(a.get("preset")), answer=a)

    def record_review(self, state, answer):
        """The person's word on a delivered cut. A withdrawal is its own row, with its reason,
        so the record says what was pulled and why before the run goes back to fix it."""
        a = self.scrub(answer)
        self.ledger.append("review", "review", spot=state.get("spot"), verdict=a.get("verdict"), who=a.get("who"),
                           preset=bool(a.get("preset")), answer=a)
        if a.get("verdict") == "withdraw":
            artifacts = state.get("artifacts") or {}
            self.ledger.append("withdrawn", "review", spot=state.get("spot"),
                               master=self.scrub(artifacts.get("delivered") or artifacts.get("master")),
                               reason=a.get("reason", ""), back_to=a.get("back_to"))

    def close(self, state):
        """The ledger step: write why the run ended, shipped or stopped."""
        trail = state.get("trail") or []
        verdicts = state.get("verdict") or {}
        last = trail[-1] if trail else None
        if (verdicts.get("render") or {}).get("dry"):
            outcome = "dry: stopped before the first spend"
        elif last == "review":
            v = verdicts.get("review") or {}
            if v.get("verdict") == "keep":
                outcome = "delivered"
            elif v.get("verdict") == "withdraw":
                outcome = "withdrawn, with no withdrawal left to fix it"
            else:
                outcome = "stopped at review"
        else:
            outcome = f"stopped at {last}"
        self.ledger.append("close", "ledger", spot=state.get("spot"), outcome=outcome,
                           trail=trail + ["ledger"], because=self.scrub(verdicts.get(last)),
                           artifacts=self.scrub(state.get("artifacts") or {}))
        return outcome


class DryToolkit(Toolkit):
    """Runs every free check for real, then records what a live run would spend, and stops."""

    def render(self, state):
        board, spot_def = load_spot(state["board"], state["spot"])
        engine = engine_for(board, spot_def)
        scenes = spot_def.get("scenes", {})
        total = 0.0
        for key in sorted(scenes):
            price = PRICE_PER_SCENE.get(engine)
            total += price or 0.0
            self.ledger.append("request", "render", dry=True, request_id=new_request_id(),
                               spot=state["spot"], scene=f"{state['spot']}-{key}", engine=engine,
                               prompt=scene_prompt(board, scenes[key]), est_usd=price)
        self.ledger.append("estimate", "render", dry=True, spot=state["spot"],
                           scenes=len(scenes), engine=engine, est_usd=round(total, 2))
        return {"dry": True, "scenes": len(scenes), "engine": engine, "est_usd": round(total, 2)}
