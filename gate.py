"""Kill gate. Given every render of one brief, drop the worst one and ship the rest.

THE WHOLE THING IN THREE STEPS
  1. Score.   Each render is judged alone, never against another, on three axes, and the
              judge is called several times because one call lands on integers and ties.
  2. Sum.     A render becomes one number, the mean over calls of craft + message + warmth.
  3. Kill.    The lowest number is dropped. Nothing else is decided. The survivors are
              handed on in the order they arrived.

WHY KILL AND NOT PICK
  The same scores read from the top, shipping the highest, land below a coin flip on 398
  human votes over five briefs. Read from the bottom, dropping the lowest, they raise what
  ships by 3.9 points, positive on each brief. One scoring, two rules; eval/run.py prints both.

WHY POINTWISE
  Shown two renders side by side, this judge and a second vendor's both preferred whichever
  came second 82% of the time. Scored one at a time there is no second, so there is nothing
  to prefer. eval/facts.py prints the counts from results/pairwise_verdicts.jsonl.

WHAT IT DELIBERATELY CANNOT DO
  It never reads a file, never calls a model, and never sees a human vote. Everything it
  knows arrives as scores through the arguments to `kill`. Scoring lives in judge.py.

Reasoning behind every constant is in DECISIONS.md. Standard library only.
"""
from __future__ import annotations

import json
import math
import statistics

# ---------------------------------------------------------------------------------------
# Constants. Each one is a decision, so each one carries its evidence.
# ---------------------------------------------------------------------------------------

# The three things a render is scored on, 1 to 10 each. Craft is the axis whose score
# tracks human win rate best on its own (r = 0.28 across 28 clips; message 0.07, warmth
# 0.13, all printed by eval/facts.py). The three summed match or beat every subset on the
# gate: craft alone lowers it, and two of the three pairs tie it. These stay.
AXES = ("craft", "message", "warmth")

# Killing one of two is picking, and picking is the thing that does not work. Three is
# the floor at which "drop the worst" is a different act from "choose the best".
MIN_CLIPS = 3

# The rubric asks for 1 to 10. A reply outside it is not a low or high score, it is a
# broken reply, and total() refuses it rather than letting it decide a kill.
SCORE_MIN, SCORE_MAX = 1.0, 10.0

# How many judge calls per render the gate was validated at. One call gives integer scores
# and seven distinct totals across 28 clips, so renders tie constantly. Twenty gives 23
# distinct totals across the same 28, three tied groups corpus-wide, and on the Aug 24 cohort
# one tie inside a brief, in the middle, never at the bottom the gate reads. The gate accepts
# any count. One call was measured too and lands lower (RUNSHEET.md's break list has the
# numbers), so twenty is the selected setting, not the only one measured.
VALIDATED_REPS = 20


def total(calls: list[dict]) -> float:
    """One number for one render: the mean over calls of the three axes summed."""
    if not calls:
        raise ValueError("a render with no judge calls cannot be scored")
    sums = []
    for c in calls:
        missing = [a for a in AXES if a not in c]
        if missing:
            raise ValueError(f"judge call is missing {missing}, refusing to guess")
        # A boolean is not a score, and float(True) is 1.0, so it has to be caught before
        # the cast or a malformed reply becomes the lowest possible score and gets killed.
        bools = [a for a in AXES if isinstance(c[a], bool)]
        if bools:
            raise ValueError(f"boolean where a score was expected: {bools}")
        # A string is not a score either, and float("6") would quietly make it one.
        strs = [a for a in AXES if not isinstance(c[a], (int, float))]
        if strs:
            raise ValueError(f"non-number where a score was expected: {strs}")
        vals = [float(c[a]) for a in AXES]
        # A judge answers 1 to 10. Anything else is a malformed reply, and a malformed reply
        # must not become a decision. NaN in particular makes min() order-dependent, so a
        # NaN-scored render could be killed or shipped depending on where it sat in the dict.
        bad = [v for v in vals if not math.isfinite(v) or not SCORE_MIN <= v <= SCORE_MAX]
        if bad:
            raise ValueError(f"score out of range {SCORE_MIN} to {SCORE_MAX}: {bad}")
        sums.append(sum(vals))
    return statistics.mean(sums)


def kill(scores: dict[str, list[dict]]) -> str:
    """Name the render to drop.

    `scores` maps each render's name to its list of judge calls, each call a dict with the
    three axes. Ties break on the name, so the same input always kills the same render and a
    reload never quietly changes the answer.
    """
    if len(scores) < MIN_CLIPS:
        raise ValueError(f"{len(scores)} renders, need {MIN_CLIPS}: with fewer, killing is picking")
    totals = {name: total(calls) for name, calls in scores.items()}
    low = min(totals.values())
    return min(name for name, t in totals.items() if t == low)


def ship(scores: dict[str, list[dict]]) -> list[str]:
    """The renders that go forward, in the order they were given, minus the one killed."""
    dead = kill(scores)
    return [name for name in scores if name != dead]


def load_scores(text: str) -> dict[str, list[dict]]:
    """Parse the stdin document, refusing a render named twice.

    json.load keeps the last of two duplicate keys and drops the first without a word, so
    two renders called "a" would silently become one and the other would never be judged.
    """
    def no_dupes(pairs):
        seen = set()
        for k, _ in pairs:
            if k in seen:
                raise ValueError(f"render {k!r} appears twice")
            seen.add(k)
        return dict(pairs)

    scores = json.loads(text, object_pairs_hook=no_dupes)
    if not isinstance(scores, dict):
        raise ValueError("expected an object mapping render name to a list of judge calls")
    return scores


if __name__ == "__main__":
    import sys

    # stdin: {"render-a": [{"craft":6,"message":5,"warmth":4}, ...], "render-b": [...], ...}
    # stdout: {"kill": "render-a", "ship": ["render-b", ...]}
    try:
        scores = load_scores(sys.stdin.read())
        print(json.dumps({"kill": kill(scores), "ship": ship(scores)}))
    except Exception as e:  # a bad day is a printed reason, never a silent exit 0
        print(json.dumps({"error": str(e)}))
        sys.exit(1)
