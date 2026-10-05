#!/usr/bin/env python3
"""switch_times.py <video> <card_s> [closer_s]: where the switching sound goes when a spot asks for it at the cuts.

The build mixes hit2.mp3, the switching sound, under a change of scene. By default it plays at the
narration's sentence boundaries, which is where the August builds cut from one scene to the next.
A chained spot does not cut there. Its shots run one into the next, so the whoosh plays over
footage that keeps going, while the picture changes somewhere else: the studio blowing apart, the
warehouse folding back, the cut to the closer. A spot with "switches": "cuts" hears it there.

This reads the assembled picture up to the card, measures how much of the frame changes from one
frame to the next, and finds the moments a lot of the frame changes at once. A hard cut does it in
one frame, a morph over about half a second, so the change is summed over a short window and a
moment counts only when the window's total passes ENERGY_MIN. A slow camera move and a one-frame
pop in a render stay under it. ENERGY_MIN is AUTHORED from one measurement, the graph-zai-shots
master on 2026-09-26, 64 px grey frames at 25 fps, summed over WINDOW frames each side of a frame
after the video's median frame change is taken off: the studio blowing apart 95, the cut to the
closer 78, the warehouse folding back 72, then a crane move 38, a render pop 16.5, the join of two
chained shots 9 and her talking in the closer 6. The line sits between 38 and 72. Another spot's
footage can sit differently against it, so a new master is measured the same way before the line
moves, and the build records the times it placed on its landing for the review to hear.

Within a moment's window the sound is placed LEAD seconds ahead of the frame that changes most,
so the whoosh lands on the change. Moments closer than SPACING seconds keep the stronger one, at
most CAP are kept, and none is placed within CARD_GAP seconds of the card, which has its own sting.
An exact tie goes to the earlier moment and the earlier frame, so the same picture always gets the
same times.

The cut to the closer is the one change the build makes itself, so it knows the time exactly. Given
closer_s, the seconds where the closer begins in the assembled video, that cut is placed from the
build's own number rather than measured, because a closer lit differently from the story can change
less of the frame than the line. The cut to the rebuilt Z.ai closer, darker than the story,
measured 46.5 against 55 on 2026-09-26, and that build lost the whoosh at 16.7 s the approved cuts
version had. It counts toward CAP like any other moment, a measured one within SPACING of it gives
way to it, and it is not placed within CARD_GAP seconds of the card either.

The last line printed is the machine line the build reads, the times comma separated:

    SWITCHES mode=cuts at=0.18,12.98,16.66
"""
import itertools
import statistics
import subprocess
import sys

FPS = 25
SIZE = 64            # frames are measured as SIZE x SIZE grey
WINDOW = 6           # frames each side of a frame, about a quarter second
ENERGY_MIN = 55.0
SPACING = 2.0
LEAD = 0.1
CAP = 4
CARD_GAP = 1.0


def frame_changes(video, end_s):
    """The mean absolute change of each frame from the one before, at FPS, up to end_s. Entry i is
    the change arriving with frame i + 1, at (i + 1) / FPS seconds."""
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", video, "-t", f"{end_s:.3f}", "-vf",
                          f"fps={FPS},scale={SIZE}:{SIZE},format=gray", "-f", "rawvideo", "-"],
                         capture_output=True, timeout=600, check=True).stdout
    n = SIZE * SIZE
    frames = [raw[i:i + n] for i in range(0, len(raw) - n + 1, n)]
    return [sum(abs(a - b) for a, b in zip(cur, prev, strict=True)) / n for prev, cur in itertools.pairwise(frames)]


def picks(changes, card_s, closer_s=None):
    """The times to place the switching sound, from a list of frame changes, strongest first,
    returned in time order. The cut to the closer, at closer_s when the build gives it, is taken
    first whatever it measures, and counts toward CAP like any other. A pure function of its inputs."""
    chosen = []
    if closer_s is not None:
        at = max(0.0, closer_s - LEAD)
        if at <= card_s - CARD_GAP:
            chosen.append((closer_s, round(at, 2)))
    if not changes:
        return sorted(at for _, at in chosen)
    base = statistics.median(changes)
    excess = [max(c - base, 0.0) for c in changes]
    energy = [sum(excess[max(0, i - WINDOW):i + WINDOW + 1]) for i in range(len(excess))]
    for i in sorted(range(len(energy)), key=lambda k: (-energy[k], k)):
        if energy[i] < ENERGY_MIN or len(chosen) == CAP:
            break
        lo, hi = max(0, i - WINDOW), min(len(changes), i + WINDOW + 1)
        peak = max(range(lo, hi), key=lambda k: (changes[k], -k))
        change_s = (peak + 1) / FPS
        if any(abs(change_s - c) < SPACING for c, _ in chosen):
            continue
        at = max(0.0, change_s - LEAD)
        if at > card_s - CARD_GAP:
            continue
        chosen.append((change_s, round(at, 2)))
    return sorted(at for _, at in chosen)


def main(argv):
    if len(argv) not in (2, 3):
        print(__doc__.strip().splitlines()[0], file=sys.stderr)
        return 64
    video, card_s = argv[0], float(argv[1])
    closer_s = float(argv[2]) if len(argv) == 3 else None
    at = picks(frame_changes(video, card_s), card_s, closer_s)
    print("SWITCHES mode=cuts at=" + ",".join(f"{t:.2f}" for t in at))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
