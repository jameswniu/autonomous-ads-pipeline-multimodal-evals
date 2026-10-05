#!/usr/bin/env python3
"""mirror_probe.py — does the scene ping-pong, and is the answer even measurable?

Mechanical replacement for "render the slit-scan (one thin strip of every frame, laid side by side
in time) and have the operator read it". That older shape held the clip and asked me to look, which
is the step that gets rationalised at 4am; this one decides. (Distinct from guards/arrow_probe.py,
which tracks how big HER, the AI presenter, appears to be over time; this one looks for the scene
replaying itself.)

## The mechanism it measures (established 2026-07-26, two clips, exact integers)

In this file avatar_iii and avatar_iv are two of the video vendor's avatar render engines, the
cheaper and the pricier, and "iii" and "iv" are short for them. A take is one render of a scene.
The "iv benchmark" is the avatar_iv clip I labelled a clean pass. A vertex is a moment where
playback turns around, and the period is how long the scene takes to repeat.

avatar_iii generates roughly 26-30s of scene motion and then FILLS the remaining duration by
playing that segment forward, backward, forward. So the background repeats exactly with a
period of twice the generated length, and the vertices land on odd multiples of half
the period:

    iii 131s take A: repeat period 60s, vertices measured at 30, 60, 90
    iii 131s take B: repeat period 53s, vertices measured at 26.6, 53.3, 106.7
    iv  131s:        no repeat at any period (best 74% of the unrelated-frame distance)

That is why water runs backwards past the half-period, why a clip at or under ~30s is clean
(it never reaches the first vertex), and why my read was right: it reuses its own source
signal. Two detectors follow, and REPEAT is the sensitive one:

  REPEAT  frame(t) vs frame(t+P) over a sweep of P. An exact refill scores near zero.
  MIRROR  frame(v-d) vs frame(v+d) over several lags d at once. A plain forward loop can only
          match at the single lag d=P/2, so agreement across many small lags means the repeat
          is genuinely mirrored rather than merely looped.

## Two rules learned by getting it wrong the same night

  1. SIGNAL FLOOR. A region only votes if its own control (the typical difference between unrelated
     frames of that region) clears CONTROL_FLOOR. The AI agent that runs this pipeline once probed
     a nearly-static band, got a control of 0.6 (no signal at all), read "no reversal", and
     reported a 131s iii take as the first clean two-minute one. It ping-ponged at t=80.
     A dead band cannot exonerate a clip, so a frame too static to measure is UNJUDGEABLE,
     never a pass.
  2. MATCHED SPANS. Controls compare frames the SAME distance apart as the test does.
     Comparing a 3-frame gap against a 1-frame baseline made a true single take fail its own
     control earlier that night.

Her face is excluded from the scene measurement on purpose: a mouth is periodic, and speech
periodicity reads as a loop if you let it into the band. That false positive flagged a clip
I had approved.

## Thresholds (derived, never authored)

Measured on the labelled set: rejects 0.00 and 0.15 of the unrelated-frame distance; the iv
benchmark 0.74; the 26s take I approved has no period at all. REPEAT_REJECT sits at 0.40,
between the worst pass and the best fail. MIRROR_REJECT 0.22 sits between the iii rejects
(0.02-0.14) and the iv benchmark (0.31-0.41).

Usage: mirror_probe.py <video.mp4> [--json]
Exit 0 forward-only / 1 replays itself / 3 unjudgeable / 64 unreadable.
"""
import json
import os
import subprocess
import sys

import numpy as np

FPS, SIDE = 10, 128
CONTROL_FLOOR = 5.0     # a region below this has no signal and cannot clear a clip
REPEAT_REJECT = 0.40    # share of unrelated-frame distance; below this the scene refills
MIRROR_REJECT = 0.22    # share of the matched-span control; below this the repeat is mirrored
LAGS = (1.0, 2.0, 3.0, 4.0)
EDGE = 5.0
MIN_PERIOD = 5          # seconds; shorter than this is wave rhythm, not a refill


def decode(path: str):
    raw = subprocess.run(
        ["ffmpeg", "-nostdin", "-v", "error", "-i", path, "-vf",
         f"fps={FPS},scale={SIDE}:{SIDE},format=gray", "-f", "rawvideo", "pipe:1"],
        capture_output=True).stdout
    px = SIDE * SIDE
    n = len(raw) // px
    if n < int(FPS * (2 * EDGE + 4)):
        return None
    return np.frombuffer(raw[: n * px], dtype=np.uint8).reshape(n, SIDE, SIDE).astype(np.float32)


def scene(fr):
    """Background only. She is excluded: a mouth is periodic and reads as a loop."""
    n = len(fr)
    return np.concatenate([fr[:, :, : SIDE // 4].reshape(n, -1),
                           fr[:, :, 3 * SIDE // 4:].reshape(n, -1)], axis=1)


def repeat_scan(bg):
    """Sweep the refill period. Returns (unrelated_distance, best_share, best_period)."""
    n = len(bg)
    far = float(np.mean([((bg[i] - bg[(i + n // 3) % n]) ** 2).mean() for i in range(0, n, 11)]))
    best = (1e18, None)
    for P in range(MIN_PERIOD, int(n / FPS / 1.5)):
        L = P * FPS
        if n - L < FPS:
            break
        v = float(np.mean([((bg[i] - bg[i + L]) ** 2).mean() for i in range(0, n - L, 5)]))
        if v < best[0]:
            best = (v, P)
    return far, best[0] / max(far, 1e-9), best[1]


def mirror_scan(bg):
    """Multi-lag mirror test. A forward-only loop cannot match at many lags at once."""
    n = len(bg)
    lf = [int(round(d * FPS)) for d in LAGS]
    ctl = [((bg[c - L] - bg[c + L]) ** 2).mean()
           for frac in (0.15, 0.3, 0.5, 0.7, 0.85)
           for c in [int(n * frac)]
           for L in lf if c - L >= 0 and c + L < n]
    if not ctl:
        return None
    control = float(np.median(ctl))
    best = (1e18, None)
    for v in range(int(EDGE * FPS), n - int(EDGE * FPS)):
        vals = [((bg[v - L] - bg[v + L]) ** 2).mean() for L in lf if v - L >= 0 and v + L < n]
        if len(vals) < len(lf):
            continue
        m = float(np.mean(vals))
        if m < best[0]:
            best = (m, v / FPS)
    return control, best[0] / max(control, 1e-9), best[1]


def control(path):
    """The unrelated-frame distance, which is exactly what CONTROL_FLOOR gates.

    A region below that floor has no signal, so it cannot clear a clip and the
    verdict is UNJUDGEABLE rather than a pass. Until now the number that decided
    that was computed and never exposed, so nothing could check it.
    """
    fr = decode(path)
    if fr is None:
        raise ValueError(path)
    return round(float(repeat_scan(scene(fr))[0]), 1)


def main():
    if len(sys.argv) < 2:
        print(__doc__.strip())
        sys.exit(64)
    path = sys.argv[1]
    fr = decode(path)
    if fr is None:
        print("mirror_probe: unreadable or too short to judge")
        sys.exit(64)
    bg = scene(fr)
    dur = len(fr) / FPS

    far, rep_share, period = repeat_scan(bg)
    ms = mirror_scan(bg)
    out = {"clip": os.path.basename(path), "seconds": round(dur, 1),
           "unrelated_distance": round(far, 1)}

    if far < CONTROL_FLOOR:
        out.update({"verdict": "UNJUDGEABLE",
                    "why": f"scene distance {far:.1f} below the signal floor {CONTROL_FLOOR}; "
                           f"a scene this static cannot show a replay either way, so NOT a pass"})
        print(json.dumps(out, indent=2) if "--json" in sys.argv else
              f"MIRROR UNJUDGEABLE: scene distance {far:.1f} < floor {CONTROL_FLOOR}. "
              f"NOT a pass - too static to measure.")
        sys.exit(3)

    out.update({"repeat_period_s": period, "repeat_share": round(rep_share, 3)})
    replays = rep_share < REPEAT_REJECT
    reason = f"scene refills with period {period}s at {rep_share * 100:.0f}% of unrelated" if replays else ""
    if ms:
        control, mir_share, vertex = ms
        out.update({"mirror_control": round(control, 1), "mirror_share": round(mir_share, 3),
                    "mirror_vertex_s": round(vertex, 1) if vertex is not None else None})
        if mir_share < MIRROR_REJECT:
            replays = True
            reason = (reason + "; " if reason else "") + \
                     f"mirrored about t={vertex:.1f}s at {mir_share * 100:.0f}% of control"
            if period:
                half = period / 2.0
                k = round(vertex / half) if half else 0
                if k and abs(vertex - k * half) < 2.0:
                    out["ping_pong"] = (f"vertex sits on multiple {k} of half-period {half:.1f}s "
                                        f"- forward/backward refill, not a one-off splice")

    out["verdict"] = "REPLAYS" if replays else "FORWARD"
    if replays:
        out["why"] = reason
    if "--json" in sys.argv:
        print(json.dumps(out, indent=2))
    else:
        print(f"MIRROR {out['verdict']}: {dur:.0f}s | repeat {rep_share:.2f} at P={period}s "
              f"(reject <{REPEAT_REJECT}) | mirror {out.get('mirror_share', float('nan')):.2f} "
              f"at t={out.get('mirror_vertex_s')} (reject <{MIRROR_REJECT})")
        if replays:
            print(f"  why: {reason}")
        if out.get("ping_pong"):
            print(f"  {out['ping_pong']}")
    sys.exit(1 if replays else 0)


if __name__ == "__main__":
    main()
