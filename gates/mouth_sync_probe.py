#!/usr/bin/env python3
"""mouth_sync_probe.py <clip.mp4> [--json]: does her mouth move WITH the voice, wherever her mouth is in frame?

lipsync_probe.py measures frame difference inside a FIXED crop box tuned to her reference framing, so on a
1:1 fit-cover closer where she sits elsewhere it finds no mouth at all and calls every onset dropped
(2026-08-26, the orchard closer: 3/3 dropped with the face plainly visible). This probe locates the face per
frame with insightface (buffalo_l, the same detector the identity gate uses), takes the lower third of the
face box as the mouth region, and cross-correlates that region's motion against the audio envelope over
lags of -0.6 to +0.6 s. Verdict mirrors lipsync_probe's continuous-speech rule so the two stay comparable:
  PASS    corr >= 0.25 and |lag| <= 0.20 s       exit 0
  REVIEW  otherwise, unless                       exit 2
  FAIL    corr < 0.10 (mouth unrelated to audio)  exit 1
Positive lag means the mouth LEADS the audio (the audio envelope trails the lip motion); negative means the mouth trails. Sign verified against the shifted controls, and the first deployment had this label inverted, which sent a compensation the wrong way (2026-08-26). Run with ~/portrait-aj/.venv-face/bin/python.
Calibrated 2026-08-26 on a shifted control: the same clip with its audio delayed 0.4 s must read lag ~+0.4.
"""
import json, subprocess, sys, tempfile, os
import numpy as np
import cv2
from insightface.app import FaceAnalysis

HZ = 25

def envelope(path, hz=HZ):
    wav = tempfile.mktemp(suffix=".wav")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", path, "-ac", "1", "-ar", "16000", "-f", "wav", wav], check=True)
    import wave
    with wave.open(wav) as w:
        a = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768.0
    os.unlink(wav)
    hop = 16000 // hz
    n = len(a) // hop
    env = np.array([np.sqrt(np.mean(a[i*hop:(i+1)*hop] ** 2)) for i in range(n)])
    return env / (env.max() + 1e-9)

def mouth_motion(path):
    """Per-frame mouth openness from the 106-point landmarks (indices 52-71 are the lips, verified 2026-08-26
    at y 0.69-0.84 of the face box): vertical extent of the lip cluster over face height. Landmark openness,
    not region frame-difference, because hair, hands and head motion pass through a region and drown the lips."""
    app = FaceAnalysis(name="buffalo_l", providers=["CPUExecutionProvider"])  # pii-allow, a model name, not a time
    app.prepare(ctx_id=0, det_size=(640, 640))
    cap = cv2.VideoCapture(path)
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    series = []; found = 0; total = 0; last = 0.0
    while True:
        ok, f = cap.read()
        if not ok: break
        total += 1
        faces = app.get(f)
        if faces:
            fc = max(faces, key=lambda z: (z.bbox[2]-z.bbox[0]) * (z.bbox[3]-z.bbox[1]))
            lm = fc.landmark_2d_106[52:72]
            h = fc.bbox[3] - fc.bbox[1]
            last = float((lm[:, 1].max() - lm[:, 1].min()) / max(h, 1.0)); found += 1
        series.append(last)
    cap.release()
    return np.array(series), fps, found, total

def main():
    path = sys.argv[1]
    env = envelope(path)
    mouth, fps, found, total = mouth_motion(path)
    if found < 5:
        print(f"MOUTH SYNC: no face found ({found} detections in {total} frames)"); return 2
    # resample mouth series to HZ
    t = np.arange(len(mouth)) / fps
    grid = np.arange(0, t[-1], 1.0 / HZ)
    m = np.interp(grid, t, mouth)
    n = min(len(m), len(env)); m = m[:n]; e = env[:n]
    m = (m - m.mean()) / (m.std() + 1e-9); e = (e - e.mean()) / (e.std() + 1e-9)
    best, bl = -2.0, 0.0
    for lag in range(-int(0.6*HZ), int(0.6*HZ) + 1):
        if lag < 0: x, y = m[-lag:], e[:lag]
        elif lag > 0: x, y = m[:-lag], e[lag:]
        else: x, y = m, e
        if len(x) < 20: continue
        c = float(np.corrcoef(x, y)[0, 1])
        if c > best: best, bl = c, lag / HZ
    verdict = "PASS" if (best >= 0.25 and abs(bl) <= 0.20) else ("FAIL" if best < 0.10 else "REVIEW")
    out = {"clip": path, "corr": round(best, 3), "lag_s": round(bl, 2), "face_frames": found, "frames": total, "verdict": verdict}
    if "--json" in sys.argv: print(json.dumps(out))
    else: print(f"MOUTH SYNC {verdict}: corr {best:.2f} at lag {bl:+.2f}s (mouth leads audio when positive) | face in {found} of {total} frames")
    return {"PASS": 0, "REVIEW": 2, "FAIL": 1}[verdict]

if __name__ == "__main__":
    sys.exit(main())
