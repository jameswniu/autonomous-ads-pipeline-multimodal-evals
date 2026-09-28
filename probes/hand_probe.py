#!/usr/bin/env python3
"""hand_probe.py <video.mp4> - does she GESTURE? The axis none of the other probes measure.

Built 2026-07-26 after every timing/level/mouth meter failed to predict my "natural" calls.
My naturals (avatar_v) have visible hand gesture; the avatar_iii rejects are talking heads with hands
frozen or absent. So measure the hand/arm band directly: motion energy BELOW the shoulder line,
excluding her head, as a fraction of the head's own motion.

  gesture_ratio = (motion in the hand/arm band) / (motion in the head band)

A talking head with still hands scores near 0. A person gesturing with the words scores high.
This is deliberately NOT a naturalness verdict on its own - it is the missing INPUT that the
state<->movement pair (INVARIANTS #10) needs, since "her movement" was never being measured.
"""
import subprocess, sys
import numpy as np

def main():
    positional = [a for a in sys.argv[1:] if not a.startswith("-")]
    if len(positional) < 1:
        print("usage: hand_probe.py CLIP.mp4", file=sys.stderr)
        return 2
    path = positional[0]
    raw = subprocess.run(["ffmpeg","-nostdin","-v","error","-i",path,"-vf",
                          "fps=10,scale=128:128,format=gray","-f","rawvideo","pipe:1"],
                         capture_output=True).stdout
    n = len(raw)//16384
    if n < 20:
        print("hand_probe: too short"); sys.exit(64)
    fr = np.frombuffer(raw[:n*16384],dtype=np.uint8).reshape(n,128,128).astype(np.float32)
    d = np.abs(np.diff(fr,axis=0))
    # head band: where the motion centroid sits in the upper frame
    var = d.mean(axis=0).copy(); var[int(0.62*128):,:] = 0
    ys,xs = np.where(var >= np.percentile(var[var>0],96))
    cy,cx = int(ys.mean()), int(xs.mean())
    head = d[:, max(0,cy-12):cy+12, max(0,cx-12):cx+12].mean()
    # hand/arm band: below the shoulders, full width, excluding the head column centre
    y0 = min(127, cy+22)
    band = d[:, y0:, :]
    hands = band.mean()
    ratio = hands/max(head,1e-6)
    print(f"HAND gesture ratio {ratio:.3f}  (head-band motion {head:.2f}, hand-band motion {hands:.2f})")
    print(f"  reference: avatar_v clips I call natural show visible gesture; a frozen talking head ~0.2 or less")
    sys.exit(0)

if __name__ == "__main__":
    sys.exit(main())
