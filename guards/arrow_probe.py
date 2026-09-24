#!/usr/bin/env python3
"""arrow_probe.py <video.mp4> - the 4D arrow gate's MEASUREMENT layer (her body, not the backdrop).

Tracks HER apparent scale over time (template match at multiple scales). Verdict rules were
calibrated 2026-07-25 against the seven clips the author judged by eye that night:
  FAIL   - the classic early shrink: her scale drops below 0.96x baseline inside the first 6s
           with no prior forward move (the original coastal clip: 0.95x at t=2 -> the author rejected it).
  REVIEW - a big ease-back after a forward peak (>8% below running peak): walk B did 1.16->0.97
           and the author ACCEPTED it as funded sway, so this is flagged for the author's eye, never auto-failed.
  PASS   - everything else: hold + sway (planted 0.97-1.03), gentle approach (cup B), night street.
Exit codes: 0 PASS, 1 FAIL, 2 REVIEW. Prints the trace either way; the numbers are evidence, not
the rule - the rule is the forward arrow (prop_gate.sh probe).
"""
import sys, cv2, numpy as np

W = 720
HER = (0.32, 0.10, 0.68, 0.58)
SCALES = np.arange(0.85, 1.161, 0.01)

def main():
    if len(sys.argv) < 2:
        print(__doc__); return 64
    cap = cv2.VideoCapture(sys.argv[1])
    if not cap.isOpened():
        print(f"arrow_probe: cannot open {sys.argv[1]}", file=sys.stderr); return 64
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    fr = []
    while True:
        ok, f = cap.read()
        if not ok: break
        fr.append(cv2.cvtColor(cv2.resize(f, (W, W), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2GRAY))
    cap.release()
    if len(fr) < 30:
        print("arrow_probe: too few frames"); return 64
    dur = int(len(fr) / fps)
    x0, y0, x1, y1 = [int(v * W) for v in HER]
    ref = fr[0][y0:y1, x0:x1]
    print("  t(s)  scale   quality")
    series = []
    for t in range(0, dur + 1):
        i = min(int(t * fps), len(fr) - 1)
        best = (0.0, 1.0)
        for s in SCALES:
            h, w = ref.shape
            sc = cv2.resize(ref, (int(w * s), int(h * s)), interpolation=cv2.INTER_LINEAR)
            if sc.shape[0] >= W or sc.shape[1] >= W: continue
            r = cv2.matchTemplate(fr[i], sc, cv2.TM_CCOEFF_NORMED)
            _, q, _, _ = cv2.minMaxLoc(r)
            if q > best[0]: best = (q, float(s))
        series.append((t, best[1], best[0]))
        print(f"  {t:4d}  {best[1]:.2f}x   {best[0]:.2f}")
    usable = [(t, s) for t, s, q in series if q > 0.55]
    if len(usable) < 5:
        print("  ARROW VERDICT: INCONCLUSIVE - match quality too low to trust; judge by eye.")
        return 2
    # rule 1: early shrink = FAIL
    early_fwd = False
    for t, s in usable:
        if t > 6: break
        if s > 1.03: early_fwd = True
        if s < 0.96 and not early_fwd:
            print(f"  ARROW VERDICT: FAIL - early shrink to {s:.2f}x at t={t}s with no prior forward"
                  f" move. The rewind: the frame claims she stepped back and nothing pays for it.")
            return 1
    # rule 2: big ease-back after a forward peak = REVIEW (the author accepted walk B's 1.16->0.97)
    peak = 1.0
    for t, s in usable:
        peak = max(peak, s)
        if peak > 1.06 and s < peak - 0.08:
            print(f"  ARROW VERDICT: REVIEW - ease-back to {s:.2f}x after a {peak:.2f}x peak at"
                  f" t={t}s. May be funded sway (walk B was accepted); a human eye decides. Do not"
                  f" ship without the author seeing it, do not auto-reject.")
            return 2
    swing = (max(s for _, s in usable) - min(s for _, s in usable)) * 100
    print(f"  ARROW VERDICT: PASS - forward-or-hold throughout (swing {swing:.0f}%). No rewind.")
    return 0

if __name__ == "__main__":
    sys.exit(main())
