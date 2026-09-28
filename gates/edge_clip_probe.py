#!/usr/bin/env python3
"""edge_clip_probe.py <clip.mp4> [--json]: is a story prop being amputated by the frame edge?

Born 2026-08-27 when a flying luggage tag swooped past the right edge of the delivered square and shipped
as a white rectangle sliced in half. The scenes render 16:9 and the build crops the center square, so the
left and right edges of the delivery are cuts the engine never saw; the crop gate watches only her
silhouette on closer renders, and nothing watched b-roll props. This probe looks for a BRIGHT, COMPACT,
MOVING blob that straddles the left or right edge band for a sustained beat, which is the signature of a
sign, tag, or card being cut off, and stays quiet for ordinary crowd motion at the edges, which is diffuse
and dim. A flagger, not a gate: it prints the seconds to look at, and the eye rules.
Exit 0 quiet, 3 flagged.
"""
import json, sys
import numpy as np
import cv2

def main():
    path = sys.argv[1]
    cap = cv2.VideoCapture(path)
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    prev = None; idx = 0; hits = []
    EDGE = 26        # px band at each side of the delivered frame
    while True:
        ok, f = cap.read()
        if not ok: break
        g = cv2.cvtColor(f, cv2.COLOR_BGR2GRAY).astype(np.float32)
        if prev is not None:
            diff = np.abs(g - prev)
            for side, band, inner in (("left", diff[:, :EDGE], diff[:, EDGE:EDGE*3]),
                                       ("right", diff[:, -EDGE:], diff[:, -EDGE*3:-EDGE])):
                bright = g[:, :EDGE] if side == "left" else g[:, -EDGE:]
                moving = (band > 18)
                blob = moving & (bright > 150)
                area = int(blob.sum())
                if area > 350 and inner.mean() > 6:
                    ys = np.where(blob.any(axis=1))[0]
                    if len(ys) and (ys.max() - ys.min()) < g.shape[0] * 0.4:
                        hits.append((idx / fps, side, area))
        prev = g; idx += 1
    cap.release()
    events = []
    for t, side, area in hits:
        if events and t - events[-1]["until"] < 0.4 and events[-1]["side"] == side:
            events[-1]["until"] = t; events[-1]["frames"] += 1
        else:
            events.append({"at": round(t, 1), "until": t, "side": side, "frames": 1})
    real = [e for e in events if e["frames"] >= 3]
    for e in real: e["until"] = round(e["until"], 1)
    out = {"clip": path, "events": real, "verdict": "EDGE CLIP" if real else "CLEAN"}
    if "--json" in sys.argv: print(json.dumps(out))
    else:
        if real:
            spots = ", ".join(f"{e['side']} {e['at']}-{e['until']}s" for e in real)
            print(f"EDGE CLIP: bright compact prop straddles the frame edge at {spots}. Look before shipping.")
        else:
            print("EDGE CLEAN: nothing bright and compact is being cut by the frame edge.")
    return 3 if real else 0

if __name__ == "__main__":
    sys.exit(main())
