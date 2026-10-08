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
covers a missing file, a missing ffmpeg, silence or no audio to measure, an ffmpeg that did
not exit 0, a summary that did not parse whole, a reading that stopped short of the master's
audio, and any exception.
A crash used to exit 1 with nothing on stdout, and a caller reads exit 1 as out of spec, so a
gate that never measured anything sent the master back to be mixed again.

A reading is taken only from an ffmpeg that exited 0, only from a summary every line of which
parsed, and only when ffmpeg read the master's audio to its end. ffmpeg stopped partway, by a
signal for one, still prints a whole summary of the part it read and then exits 255, and the
gate used to read that summary as the master's: a run stopped 1.5 seconds into a six second
master passed on those 1.5 seconds, whatever the rest of the master held. A summary cut off
partway is refused the same way, never read for the numbers it still holds. So is a master
whose file stops short, a copy or a download cut off partway: master.sh puts a master's index
at its front, so such a copy still opens and still says how long it runs, and ffmpeg used to
read it to the cut and exit 0. Cut inside an audio packet, ffmpeg now stops on the broken
packet (-xerror), and cut between two it reads a clean end, which the length check catches.
pipeline/live.py reads a gate that printed no LOUDNESS_GATE line as unreadable, never as a pass.
"""
import math
import os
import re
import subprocess
import sys

TARGET_I = -16.0      # LUFS integrated, the loudnorm target every build uses
TOLERANCE_I = 1.0     # within a decibel either way
MAX_TP = -1.5         # dBTP ceiling. shoots/master.sh aims at -2.0 so an encode cannot land on it

# ebur128's summary, every line it prints after "Summary:" in the order it prints them, as a label
# and the unit its number carries. A section heading carries no number. ffmpeg 6.1, the release CI
# installs, and ffmpeg 8.1 print it the same way.
SUMMARY = (("Integrated loudness", None), ("I", "LUFS"), ("Threshold", "LUFS"),
           ("Loudness range", None), ("LRA", "LU"), ("Threshold", "LUFS"), ("LRA low", "LUFS"),
           ("LRA high", "LUFS"), ("True peak", None), ("Peak", "dBFS"))
NUMBER = r"-?(?:inf|[0-9]+\.[0-9]+)"
# ebur128 logs a line for every 100 ms it measures, starting "t: <seconds>", so the last of them
# says how far into the audio ffmpeg read. A reading that stops more than COVERED_S short of how
# long the master's audio says it runs is refused. On the 29 masters the pipeline has made, the
# last line fell at most 0.084 s short.
FRAME_TIME = re.compile(r"\bt: *([0-9]+(?:\.[0-9]+)?) +TARGET:")
COVERED_S = 0.25


class Unmeasured(Exception):
    """The master could not be measured, so there is no verdict to report."""


def summary(stderr):
    """(integrated LUFS, true peak dBTP) from the last summary in ffmpeg's output, or None unless
    every line of it is there and parsed, in order. ffmpeg's own closing lines after it are not read."""
    at = stderr.rfind("Summary:")
    if at < 0:
        return None
    lines = [ln.strip() for ln in stderr[at + len("Summary:"):].splitlines() if ln.strip()]
    if len(lines) < len(SUMMARY):
        return None
    read = {}
    for line, (label, unit) in zip(lines[:len(SUMMARY)], SUMMARY, strict=True):
        found = re.fullmatch(re.escape(label) + ":" + (rf"\s+({NUMBER}) {re.escape(unit)}" if unit else ""), line)
        if not found:
            return None
        if unit:
            read[label] = float(found.group(1))
    return read["I"], read["Peak"]


def audio_runs(path):
    """How long the master's first audio stream, the one ebur128 measures, says it runs, in
    seconds, or None when ffprobe cannot say."""
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries", "stream=duration",
                        "-of", "csv=p=0", path], capture_output=True, text=True, timeout=60)
    try:
        runs = float(r.stdout.strip())
    except ValueError:
        return None
    return runs if math.isfinite(runs) and runs > 0 else None


def measure(path):
    """(integrated LUFS, true peak dBTP) from ebur128's summary. Raises Unmeasured unless ffmpeg
    exited 0, every line of its summary parsed, and it read the master's audio to its end."""
    # -xerror makes a broken packet or decode end ffmpeg nonzero rather than be skipped over, and
    # framelog=info keeps the per-frame lines whose times say how far it read.
    r = subprocess.run(["ffmpeg", "-nostats", "-hide_banner", "-xerror", "-i", path, "-vn",
                        "-filter_complex", "ebur128=peak=true:framelog=info", "-f", "null", "-"],
                       capture_output=True, text=True, timeout=600)
    last = (r.stderr.strip().splitlines() or ["no output"])[-1][:200]
    if r.returncode != 0:
        how = f"was stopped by signal {-r.returncode}" if r.returncode < 0 else f"exited {r.returncode}"
        raise Unmeasured(f"ffmpeg {how}, so its measurement did not finish: {last}")
    read = summary(r.stderr)
    if read is None:
        raise Unmeasured(f"ffmpeg gave no whole loudness summary: {last}")
    i, tp = read
    if math.isinf(i) or math.isinf(tp):
        raise Unmeasured("the audio is silent, so there is no loudness to measure")
    runs = audio_runs(path)
    if runs is None:
        raise Unmeasured("ffprobe gave no length for the master's audio, so nothing shows the reading covered it")
    heard = max((float(t) for t in FRAME_TIME.findall(r.stderr)), default=0.0)
    if heard < runs - COVERED_S:
        raise Unmeasured(f"ffmpeg measured {heard:.2f} s of the {runs:.2f} s the master's audio runs")
    return i, tp


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
