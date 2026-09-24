#!/usr/bin/env python3
"""jaw_gate.py <closer.mp4>: refuse a closer whose jaw swings further than its lips explain.

source_gate.py measures and never rules, by design, so the threshold lives here with its
reasons. JAW_MAX is 0.17, the latest dated ruling in the doctrine (2026-08-30), which says to
refuse to build over 0.17 and marks the older 0.20 line as superseded. Every closer the
author accepted that week sat under it and the rubbery ones read 0.20 to 0.23. No labelled
pass/reject pair in evals/labels.csv backs the number, so evals/derive.py counts it AUTHORED.

The jaw is a property of the look, deterministic across takes and days: the same look and
audio render the same jaw again, and re-rolling the audio never moves it. So a closer over
the ceiling needs a new look, and the graph stops the run rather than re-rendering.

Needs the face extra (`make setup-face`) in whichever interpreter FACEPY names.

Exit 0 PASS / 1 FAIL / 64 UNMEASURED or no verdict at all.

UNMEASURED is a verdict: source_gate ran, and a face shows in under 70 percent of sampled
frames or the jaw reads nan, since the jaw number means nothing over someone else's face.
It prints the machine line, which is always the last line of a verdict:
JAW_GATE jaw=<value> face_cov=<value> max=<ceiling> verdict=<PASS|FAIL|UNMEASURED>

No verdict prints NO machine line, only one line on stderr saying why, and exits 64: a
missing file, an interpreter in FACEPY that is not there, source_gate crashing or printing
neither number, and any exception here. A crash used to exit 1 with nothing on stdout, and
a caller reads exit 1 as a jaw over the ceiling, so a broken install stopped the run for a
new look nobody needed.
"""
import math
import os
import re
import subprocess
import sys

JAW_MAX = 0.17        # refuse over this; see the header for the ruling
MIN_FACE_COV = 0.70   # source_gate's own rule: callers skip the jaw under this coverage

HERE = os.path.dirname(os.path.abspath(__file__))


def verdict(jaw, face_cov):
    """PASS, FAIL or UNMEASURED for a jaw_rubber reading and its face coverage."""
    if face_cov is None or face_cov < MIN_FACE_COV or jaw is None or math.isnan(jaw):
        return "UNMEASURED"
    return "PASS" if jaw <= JAW_MAX else "FAIL"


def read(text, name):
    m = re.search(rf"^{name} ([-0-9.naN]+)", text, re.M)
    try:
        return float(m.group(1)) if m else None
    except ValueError:
        return None


def no_verdict(reason):
    print(f"jaw_gate: no verdict, {reason}", file=sys.stderr)
    return 64


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if not argv or not os.path.isfile(argv[0]):
        return no_verdict("usage: jaw_gate.py <closer.mp4>, and the file must exist")
    py = os.environ.get("FACEPY", sys.executable)
    try:
        r = subprocess.run([py, os.path.join(HERE, "source_gate.py"), argv[0]],
                           capture_output=True, text=True, timeout=900)
    except Exception as exc:  # noqa: BLE001, a measurement that never ran is not a FAIL
        return no_verdict(f"source_gate did not run under FACEPY={py}: {type(exc).__name__}: {exc}")
    if r.stdout.strip():
        print(r.stdout.strip())
    if r.returncode != 0:
        tail = r.stderr.strip().splitlines()[-1:] or [f"exit {r.returncode} and nothing on stderr"]
        return no_verdict(f"source_gate crashed (exit {r.returncode}): {tail[0][:300]}")
    jaw, cov = read(r.stdout, "jaw_rubber"), read(r.stdout, "face_cov")
    # A nan jaw is a reading, the face was too sparse to measure. A number that is not printed
    # at all is source_gate failing to report, which is no reading of this closer.
    if jaw is None or cov is None:
        return no_verdict("source_gate printed no jaw_rubber or no face_cov line")
    v = verdict(jaw, cov)
    print(f"JAW_GATE jaw={jaw} face_cov={cov} max={JAW_MAX} verdict={v}")
    return {"PASS": 0, "FAIL": 1}.get(v, 64)


if __name__ == "__main__":
    sys.exit(main())
