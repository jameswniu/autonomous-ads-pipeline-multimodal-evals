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

HZ = 25

# The verdict rule, named so it can be bracketed and tested without a face model. Values are the
# ones calibrated on shifted controls on 2026-08-26 and mirrored from lipsync_probe's rule.
PASS_CORR = 0.25   # correlation at or above this, with the lag inside PASS_LAG, is a PASS
PASS_LAG = 0.20    # seconds either way
FAIL_CORR = 0.10   # below this the mouth is unrelated to the audio
EXIT = {"PASS": 0, "REVIEW": 2, "FAIL": 1}
# No face is not a measurement. It used to share exit 2 with REVIEW, and ad_gates.sh passes every
# REVIEW, so a closer with no measurable mouth reached AD GATES PASS (2026-09-21).
NO_FACE = 3


def verdict(corr, lag):
    """PASS, REVIEW or FAIL for a best correlation and its lag in seconds."""
    if corr >= PASS_CORR and abs(lag) <= PASS_LAG:
        return "PASS"
    if corr < FAIL_CORR:
        return "FAIL"
    return "REVIEW"

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
    # Imported here, not at module level, so the gate imports on a machine without the face
    # model and its verdict rule stays testable everywhere. The model itself is still required
    # to measure, and its absence fails loud at this line.
    from insightface.app import FaceAnalysis
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
        print(f"MOUTH SYNC NO FACE: {found} detections in {total} frames, nothing measured"); return NO_FACE
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
    v = verdict(best, bl)
    out = {"clip": path, "corr": round(best, 3), "lag_s": round(bl, 2), "face_frames": found, "frames": total, "verdict": v}
    if "--json" in sys.argv: print(json.dumps(out))
    else: print(f"MOUTH SYNC {v}: corr {best:.2f} at lag {bl:+.2f}s (mouth leads audio when positive) | face in {found} of {total} frames")
    return EXIT[v]

if __name__ == "__main__":
    sys.exit(main())
