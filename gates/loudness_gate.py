#!/usr/bin/env python3
"""loudness_gate.py <master.mp4>: integrated loudness and true peak, against the delivery spec.

Every build masters with ffmpeg's loudnorm aimed at -16 LUFS integrated and -2.0 dBTP true
peak (shoots/master.sh), half a decibel under the -1.5 dBTP ceiling this gate enforces, and
until this file nothing measured the result. The ship-gate row of the step table claimed
loudness and the gate never read it. loudnorm in one pass can land off its target, so the
master is measured after the fact, the same way every other gate reads the output rather
than trusting the step that made it.

The numbers are a published delivery spec, not a judgement calibrated against labels, so
they are reported apart from the thresholds a person's grades set.

Measured with ffmpeg's ebur128 filter, integrated loudness over the whole master and the
true peak across channels.

Exit 0 within spec / 1 out of spec / 64 no verdict.
A verdict prints one machine-readable last line: LOUDNESS_GATE i=<LUFS> tp=<dBTP> verdict=<PASS|FAIL>
No verdict prints NO machine line, only one line on stderr saying why, and exits 64. That
covers a missing file, a missing ffmpeg, silence or no audio to measure, and any exception.
A crash used to exit 1 with nothing on stdout, and a caller reads exit 1 as out of spec, so a
gate that never measured anything sent the master back to be mixed again.
"""
import os
import re
import subprocess
import sys

TARGET_I = -16.0      # LUFS integrated, the loudnorm target every build uses
TOLERANCE_I = 1.0     # within a decibel either way
MAX_TP = -1.5         # dBTP ceiling. shoots/master.sh aims at -2.0 so an encode cannot land on it


class Unmeasured(Exception):
    """The master could not be measured, so there is no verdict to report."""


def measure(path):
    """(integrated LUFS, true peak dBTP) from ebur128's summary. Raises Unmeasured."""
    r = subprocess.run(["ffmpeg", "-nostats", "-hide_banner", "-i", path, "-vn",
                        "-filter_complex", "ebur128=peak=true", "-f", "null", "-"],
                       capture_output=True, text=True, timeout=600)
    summary = r.stderr[r.stderr.rfind("Summary:"):] if "Summary:" in r.stderr else ""
    i = re.search(r"I:\s+(-?[0-9.]+|-inf) LUFS", summary)
    tp = re.search(r"True peak:\s+Peak:\s+(-?[0-9.]+|-inf) dBFS", summary)
    if not (i and tp):
        tail = r.stderr.strip().splitlines()[-1:] or ["no output"]
        raise Unmeasured(f"ffmpeg gave no loudness summary (exit {r.returncode}): {tail[0][:200]}")
    if "inf" in i.group(1) or "inf" in tp.group(1):
        raise Unmeasured("the audio is silent, so there is no loudness to measure")
    return float(i.group(1)), float(tp.group(1))


def verdict(i, tp):
    if i is None or tp is None:
        return "UNREADABLE"
    return "PASS" if abs(i - TARGET_I) <= TOLERANCE_I and tp < MAX_TP else "FAIL"


def no_verdict(reason):
    print(f"loudness_gate: no verdict, {reason}", file=sys.stderr)
    return 64


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if not argv or not os.path.isfile(argv[0]):
        return no_verdict("usage: loudness_gate.py <master.mp4>, and the file must exist")
    try:
        i, tp = measure(argv[0])
    except Unmeasured as exc:
        return no_verdict(str(exc))
    except Exception as exc:  # noqa: BLE001, any crash is a missing measurement, never a FAIL
        return no_verdict(f"{type(exc).__name__}: {exc}")
    v = verdict(i, tp)
    print(f"integrated {i:.1f} LUFS (target {TARGET_I} within {TOLERANCE_I}), "
          f"true peak {tp:.1f} dBTP (under {MAX_TP})")
    print(f"LOUDNESS_GATE i={i} tp={tp} verdict={v}")
    return {"PASS": 0, "FAIL": 1}[v]


if __name__ == "__main__":
    sys.exit(main())
