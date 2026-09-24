#!/usr/bin/env python3
"""voice_probe.py — pick the take where she sounds like HERSELF, and name the ones that drifted.

## The defect this exists for (the author, 2026-07-26)

"sometimes it gets fucked the accent. 2nd time it's happening. not often, but happens."

An intermittent defect with no detector ships silently. His ear caught it twice; nothing in the
pipeline caught it once. This is the same shape as the spasm: `eleven_v3` redraws the voice per
generation, and a minority of draws land materially off her.

MEASURED 2026-07-26, five draws of IDENTICAL text with IDENTICAL settings (voice, eleven_v3, 0.6/0.92/0.3):

    draw   F1    F2/F1
    1      537   3.44
    2      616   2.91
    3      727   2.59   <- 27% off the consensus vowel space
    4      573   3.09
    5      558   3.22

F1 is tongue height. A 190 Hz spread on identical text is not delivery variance, it is a different
vowel space, which is what the ear reads as a changed accent. One draw in five landed there, which
matches "not often, but happens" exactly.

## Why the draws are their own reference (the trap this avoids)

The obvious detector — compare a clip's formants to a fixed profile of her accepted clips — is
WRONG, and I built it and watched it fail first. Formant medians are dominated by WHICH VOWELS THE
SCRIPT CONTAINS, not by accent. Across the campaign's different scripts, F2/F1 ranged 2.75-4.57
while two clips the author ACCEPTED sat at 2.90 and 3.38, straddling most of that range. Content swamps
the signal, so no absolute threshold can separate drift from "this line had different vowels".

So this probe never compares across scripts. It compares N draws OF THE SAME TEXT against each
other and takes their median as the reference. Self-normalizing: the script's own vowel content is
held constant by construction, and the only thing left varying is the model. Same lesson as
mirror_probe's matched spans and level_probe's relations — measure the thing that varies, hold the
rest fixed.

## Why the fix is free (and does not violate the single-take rule)

The author, 2026-07-26: "single take always pls on avaIII, unless i say so otherwise!!" That rule is
about avatar_iii RENDER credits. TTS draws cost zero HeyGen credits, so metering audio is not a
spend decision at all. Meter-and-select — the thing that actually fixed the spasm — applies here at
no cost, which makes shipping a blind single audio draw a pure loss.

## Threshold

DEVIATE_REJECT 0.15 is DERIVED, not authored: on the measured set the consensus cluster deviates
0.00-0.08 from the median F1 and the drifted draw deviates 0.27. It sits between them, nearer the
cluster. n=5, so it is provisional and re-derives the moment the author labels a take by ear — the author's ear
outranks this meter, as it outranks every other one in this skill.

Usage:
  voice_probe.py <take1.mp3> <take2.mp3> [take3.mp3 ...]
    -> ranked table; last line is WINNER: <path> (the take closest to consensus)

Exit 0 a consensus winner was found / 1 the draws do not agree (redraw) / 64 usage.
"""
import subprocess
import sys

import numpy as np

SR = 16000
DEVIATE_REJECT = 0.15   # fractional distance from the median vowel space; see header
MIN_TAKES = 3           # below this there is no meaningful consensus to be closest to
MIN_VOICED = 40         # frames; fewer and the medians are noise


def pcm(path: str):
    raw = subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-i", path, "-ac", "1",
                          "-ar", str(SR), "-f", "s16le", "pipe:1"], capture_output=True).stdout
    return np.frombuffer(raw, dtype=np.int16).astype(np.float64) / 32768.0


def lpc(x, order=14):
    """Levinson-Durbin. Plain numpy so the skill carries no extra dependency."""
    x = x * np.hamming(len(x))
    r = np.correlate(x, x, "full")[len(x) - 1: len(x) - 1 + order + 1]
    if r[0] <= 0:
        return None
    a = np.zeros(order + 1)
    a[0], e = 1.0, r[0]
    for i in range(1, order + 1):
        acc = r[i] + sum(a[j] * r[i - j] for j in range(1, i))
        k = -acc / e
        an = a.copy()
        for j in range(1, i):
            an[j] = a[j] + k * a[i - j]
        an[i] = k
        a = an
        e *= (1 - k * k)
        if e <= 0:
            return None
    return a


def profile(path: str):
    """Median vowel space (F1, F2) over voiced frames. None if too little voiced audio."""
    x = pcm(path)
    if len(x) < SR:
        return None
    pre = np.append(x[0], x[1:] - 0.97 * x[:-1])   # pre-emphasis, standard for formants
    W, H = int(0.025 * SR), int(0.0125 * SR)
    F1, F2 = [], []
    for i in range(0, len(pre) - W, H):
        w = pre[i:i + W]
        if np.sqrt((w ** 2).mean()) < 0.03:        # unvoiced / silence contributes nothing
            continue
        a = lpc(w)
        if a is None:
            continue
        try:
            rts = np.roots(a)
        except Exception:
            continue
        rts = [r for r in rts if np.imag(r) >= 0.01]
        if not rts:
            continue
        f = sorted(abs(np.arctan2(np.imag(r), np.real(r))) * SR / (2 * np.pi) for r in rts)
        f = [v for v in f if 200 < v < 4500]
        if len(f) < 2:
            continue
        F1.append(f[0])
        F2.append(f[1])
    if len(F1) < MIN_VOICED:
        return None
    return float(np.median(F1)), float(np.median(F2)), len(F1)


def main():
    takes = sys.argv[1:]
    if len(takes) < 2:
        print("usage: voice_probe.py <take1.mp3> <take2.mp3> [take3.mp3 ...]")
        sys.exit(64)
    if len(takes) < MIN_TAKES:
        print(f"voice_probe WARNING: {len(takes)} takes. Consensus needs at least {MIN_TAKES}; "
              f"with two, 'closest to median' is meaningless. Proceeding, but say so on delivery.")

    measured = []
    for p in takes:
        pr = profile(p)
        if pr is None:
            print(f"  {p.split('/')[-1]:28s} unmeasurable (too little voiced audio), skipped")
            continue
        measured.append((p, *pr))
    if len(measured) < 2:
        print("voice_probe: not enough measurable takes to form a consensus")
        sys.exit(64)

    med1 = float(np.median([m[1] for m in measured]))
    med2 = float(np.median([m[2] for m in measured]))

    rows = []
    for p, f1, f2, n in measured:
        # distance in the vowel plane, each axis normalised by its own consensus value so F2's
        # larger absolute numbers do not dominate F1's
        dev = float(np.hypot((f1 - med1) / med1, (f2 - med2) / med2))
        rows.append((dev, p, f1, f2, n))
    rows.sort()

    print(f"\nconsensus vowel space: F1 {med1:.0f} Hz, F2 {med2:.0f} Hz "
          f"(median of {len(measured)} draws of the same text)")
    print(f"{'take':30s} {'F1':>6s} {'F2':>6s} {'deviation':>10s}  verdict")
    for dev, p, f1, f2, _n in rows:
        v = "DRIFTED" if dev > DEVIATE_REJECT else ("consensus" if dev < DEVIATE_REJECT / 2 else "near")
        print(f"{p.split('/')[-1]:30s} {f1:6.0f} {f2:6.0f} {dev:10.3f}  {v}")

    drifted = [r for r in rows if r[0] > DEVIATE_REJECT]
    if drifted:
        print(f"\n{len(drifted)} of {len(rows)} draws drifted off her vowel space. This is the accent "
              f"slip the author hears; it is a per-draw coin flip, not a settings error.")

    survivors = [r for r in rows if r[0] <= DEVIATE_REJECT]
    if not survivors:
        print("\nvoice_probe: EVERY draw sits far from the others; there is no consensus to trust.")
        print("Redraw rather than shipping one, and tell the author the draws disagreed.")
        print(f"SURVIVOR: {rows[0][1]}")
        sys.exit(1)

    # RANKING AMONG SURVIVORS IS NOT SUPPORTED BY EVIDENCE (falsified 2026-07-26 by the author's ear).
    # The original rule was "closest to the median wins". His labels inverted it: on one identical-text
    # pool, the take at deviation 0.000 (the most consensus take there is) the author called NOT USABLE, while
    # the take the author called USABLE sat at 0.066, mid-pack. Meanwhile the flagged outlier at 0.197 the author also
    # rejected. So this metric separates GROSS DRIFT from the rest, and has NO signal inside the
    # surviving band. Picking the minimum is therefore false precision, and pretending otherwise is how
    # a meter outranks the author's ear, which is backwards in this skill.
    pick = survivors[len(survivors) // 2]      # arbitrary-but-stable; explicitly NOT "the best"
    print(f"\nvoice_probe: {len(survivors)} of {len(rows)} draws survive the outlier check.")
    print("Ranking WITHIN survivors is not supported: the author's labelled 0.000 was unusable and the author's labelled")
    print("0.066 was usable, so this metric cannot order the survivors. The pick below is arbitrary")
    print("among them, not a quality judgement. When it matters, put the survivors to the author's ear.")
    print(f"SURVIVOR: {pick[1]}")
    sys.exit(0)


if __name__ == "__main__":
    main()
