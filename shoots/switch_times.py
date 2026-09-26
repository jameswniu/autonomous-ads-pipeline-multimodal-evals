#!/usr/bin/env python3
"""switch_times.py <video> <card_s>: where the switching sound goes when a spot asks for it at the cuts.

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
chained shots 9 and her talking in the closer 6. The line sits between 38 and 72.

Within a moment's window the sound is placed LEAD seconds ahead of the frame that changes most,
so the whoosh lands on the change. Moments closer than SPACING seconds keep the stronger one, at
most CAP are kept, and none is placed within CARD_GAP seconds of the card, which has its own sting.
An exact tie goes to the earlier moment and the earlier frame, so the same picture always gets the
same times.

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


def picks(changes, card_s):
    """The times to place the switching sound, from a list of frame changes, strongest first,
    returned in time order. A pure function of its inputs."""
    if not changes:
        return []
    base = statistics.median(changes)
    excess = [max(c - base, 0.0) for c in changes]
    energy = [sum(excess[max(0, i - WINDOW):i + WINDOW + 1]) for i in range(len(excess))]
    chosen = []
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
    if len(argv) != 2:
        print(__doc__.strip().splitlines()[0], file=sys.stderr)
        return 64
    video, card_s = argv[0], float(argv[1])
    at = picks(frame_changes(video, card_s), card_s)
    print("SWITCHES mode=cuts at=" + ",".join(f"{t:.2f}" for t in at))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
