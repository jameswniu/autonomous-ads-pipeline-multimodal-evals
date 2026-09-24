#!/usr/bin/env python3
"""graph_verdict.py <video> <srt> - the GRAPH phase, crossing PRESENCE against TIMING.

The author's architecture (2026-07-26): invariants own oscillation and the palindrome; the GRAPH owns
robotic movement. But every graph metric alone failed the author's labels, and the reason is structural:
coherence_probe measures whether motion is IN STEP with the speech, and on avatar_iii there is
barely any body motion to be in step with. Robotic-ness there comes from movement being ABSENT,
not mistimed, and an absence has no phase to measure.

So the graph verdict needs two terms crossed:

    PRESENCE  - is there movement to be coherent with?     (hand_probe gesture ratio)
    TIMING    - does the movement arrive with the speech?  (coherence_probe debt per onset)

  present + in step   -> coherent, reads alive        (ivy ava5: gesture 0.79, 0.0103 s/onset)
  present + late      -> reads laboured
  absent  + in step   -> vacuously "in step", reads still; fine ONLY in a calm register
  absent  + late      -> worst: nothing happening, and what does happen lags

The calm-register exception is why this prints a REGISTER-DEPENDENT reading rather than a verdict:
The author's PERFECT clip (r3) is absent-and-still and the author loved it, because the script was a lullaby. The
same profile on an excited script is the frozen-hands defect the author rejected. Register comes from the
caller, not from pixels.

Usage: graph_verdict.py <video> <srt> [--register calm|excited]
Exit 0 always: this REPORTS. The eye and the register decide.
"""
import subprocess, sys, os

SKILL = os.path.dirname(os.path.abspath(__file__))

def num(out, pat, field=1):
    import re
    m = re.search(pat, out)
    return float(m.group(field)) if m else None

def main():
    if len(sys.argv) < 3:
        print("usage: graph_verdict.py <video> <srt> [--register calm|excited]")
        return 64
    v, s = sys.argv[1], sys.argv[2]
    reg = "unspecified"
    if "--register" in sys.argv:
        reg = sys.argv[sys.argv.index("--register")+1]
    ho = subprocess.run([sys.executable, f"{SKILL}/hand_probe.py", v], capture_output=True, text=True).stdout
    co = subprocess.run([sys.executable, f"{SKILL}/coherence_probe.py", v, s], capture_output=True, text=True).stdout
    gesture = num(ho, r"ratio ([0-9.]+)")
    debt = num(co, r"debt ([0-9.]+)")
    import re
    m = re.search(r"leads/sync/lates (\d+)/(\d+)/(\d+)", co)
    onsets = sum(int(x) for x in m.groups()) if m else 0
    per = (debt/onsets) if (debt is not None and onsets) else None
    if gesture is None or per is None:
        print("graph_verdict: not measurable (clip too short or no speech events)"); return 0
    presence = "present" if gesture >= 0.35 else "absent"
    timing = "in step" if per <= 0.011 else "late"
    print(f"GRAPH  presence={presence} (gesture {gesture:.3f})  timing={timing} ({per:.4f}s per onset)")
    quad = {("present","in step"): "coherent and alive - the avatar_v profile the author calls natural",
            ("present","late"):    "movement happens but lags the words: reads laboured",
            ("absent","in step"):  "still and on time: RIGHT for a calm register, the frozen-hands defect on an excited one",
            ("absent","late"):     "worst quadrant: little movement, and what there is arrives late"}[(presence,timing)]
    print(f"  -> {quad}")
    print(f"  register given: {reg}")
    if presence == "absent" and reg == "excited":
        print("  MISMATCH: an excited script needs present movement; avatar_iii cannot supply it (motionPrompt is ignored).")
    return 0

if __name__ == "__main__":
    sys.exit(main())
