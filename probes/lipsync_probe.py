#!/usr/bin/env python3
"""lipsync_probe.py <video.mp4> - the her<->VOICE pair's measurement layer (post-render).

The pair: the audio is an in-frame element claiming "these syllables are being sung/said NOW";
her mouth must pay each claim, on time. Calibrated 2026-07-25 on my judged pair:
  speed-mode M8 dance   = known FAIL (mouth misses vocal onsets by 400-700ms, sings through a
                          closed smile at 5.7s and 9.4s)
  precision-mode M8     = the PASS reference ("tight singing sync")
Two modes, chosen by the audio's shape:
  ONSET mode  (gappy audio, songs): per sharp vocal onset, when does mouth motion respond?
              lag per onset + dropped-phrase count.
  CORR mode   (continuous speech, talking heads): cross-correlate mouth motion vs audio
              envelope over +-0.6s; report best lag + correlation.
ROI: mouth/face band. Default fits centered talking heads; override for off-center faces:
  LIPSYNC_ROI="x0,y0,x1,y1" (fractions), e.g. dance clips: LIPSYNC_ROI="0.50,0.12,0.92,0.55"
Exit codes: 0 PASS, 1 FAIL, 2 REVIEW/INCONCLUSIVE. Numbers are evidence; the pair is the rule.
"""
import json, os, sys, subprocess
import numpy as np

W = 360
HZ = 20.0

# Every number this probe refuses a clip with, named. They were inline literals, which meant
# evals/derive.py could not bracket them and reported them in neither the derived count nor its
# denominator: its own docstring called this out as "lipsync_probe's nine" (2026-09-21).
ONSET_LOUD = 0.45        # envelope above this, after quiet, is a vocal onset
ONSET_QUIET = 0.18       # the preceding quarter second has to be below this
ONSET_GAP_S = 1.5        # onsets closer together than this are one onset
RESPONSE_S = 0.8         # the mouth has this long to answer an onset
RESPONSE_RISE = 1.6      # and has to exceed its own baseline by this factor
MISS_FAIL = 0.30         # share of onsets with no mouth response
LAG_FAIL_S = 0.35        # median response lag
MISS_REVIEW = 0.10
LAG_REVIEW_S = 0.20
CORR_FAIL = 0.10         # continuous speech: below this the mouth is unrelated to the audio
CORR_PASS = 0.25
CORR_LAG_S = 0.20
NO_LAGS = 9.9            # sentinel median when every onset was missed

# --json prints one object and nothing else, so a caller can read the measurement instead of
# scraping prose. evals/certify.py needs it to plot the probe's response against a known shift.
JSON = "--json" in sys.argv


def say(*a, **k):
    if not JSON:
        print(*a, **k)


def done(out, code):
    if JSON:
        print(json.dumps(out))
    return code


def main():
    if len(sys.argv) < 2:
        print(__doc__); return 64
    path = sys.argv[1]
    if not os.path.isfile(path):
        print(f"lipsync_probe: not found: {path}", file=sys.stderr); return 64
    import cv2
    roi = os.environ.get("LIPSYNC_ROI", "0.32,0.22,0.68,0.60")
    x0, y0, x1, y1 = [float(v) for v in roi.split(",")]

    # audio envelope at HZ
    p = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-vn", "-ac", "1", "-ar", "16000",
                        "-f", "f32le", "pipe:1"], capture_output=True)
    a = np.frombuffer(p.stdout, dtype=np.float32)
    if len(a) < 16000:
        say("lipsync_probe: no usable audio"); return 2
    hop = int(16000 / HZ)
    na = len(a) // hop
    env = np.array([np.sqrt((a[i*hop:(i+1)*hop]**2).mean()) for i in range(na)])
    env = env / (env.max() + 1e-9)

    # mouth-motion trace at HZ
    cap = cv2.VideoCapture(path)
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    px0, py0, px1, py1 = None, None, None, None
    prev = None
    raw = []          # (t, motion)
    idx = 0
    while True:
        ok, f = cap.read()
        if not ok: break
        g = cv2.cvtColor(cv2.resize(f, (W, W), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2GRAY).astype(np.float32)
        if px0 is None:
            px0, py0, px1, py1 = int(x0*W), int(y0*W), int(x1*W), int(y1*W)
        cur = g[py0:py1, px0:px1]
        if prev is not None:
            raw.append((idx / fps, float(np.abs(cur - prev).mean())))
        prev = cur; idx += 1
    cap.release()
    if len(raw) < 20:
        say("lipsync_probe: too few frames"); return 2
    nbins = int(raw[-1][0] * HZ) + 1
    mouth = np.zeros(nbins); cnt = np.zeros(nbins)
    for t, m in raw:
        b = min(int(t * HZ), nbins - 1); mouth[b] += m; cnt[b] += 1
    mouth = mouth / np.maximum(cnt, 1)
    n = min(len(env), len(mouth)); env = env[:n]; mouth = mouth[:n]

    # onsets: quiet -> loud
    onsets = []
    for i in range(4, n - int(RESPONSE_S * HZ)):
        if env[i] > ONSET_LOUD and env[i-4:i].mean() < ONSET_QUIET:
            t = i / HZ
            if not onsets or t - onsets[-1] > ONSET_GAP_S: onsets.append(t)

    if len(onsets) >= 3:
        say(f"  mode: ONSET ({len(onsets)} sharp vocal onsets)")
        lags, misses = [], 0
        for t0 in onsets:
            i0 = int(t0 * HZ)
            b0, b1 = max(0, i0 - int(0.5*HZ)), max(0, i0 - int(0.1*HZ))
            base = mouth[b0:b1].mean() if b1 > b0 else mouth[max(0,i0-2):i0].mean()
            hit = None
            for j in range(max(0, i0 - 2), min(n, i0 + int(RESPONSE_S*HZ))):
                if mouth[j] > base * RESPONSE_RISE + 1e-4:
                    hit = j / HZ - t0; break
            if hit is None:
                misses += 1
                say(f"    onset {t0:5.1f}s  -> NO mouth response within 0.8s (dropped phrase)")
            else:
                lags.append(hit)
                say(f"    onset {t0:5.1f}s  -> mouth responds {hit:+.2f}s")
        miss_rate = misses / len(onsets)
        med = float(np.median(lags)) if lags else NO_LAGS
        say(f"  median lag {med:+.2f}s | dropped {misses}/{len(onsets)} ({miss_rate*100:.0f}%)")
        base = {"clip": path, "mode": "onset", "onsets": len(onsets), "miss_rate": round(miss_rate, 3),
                "median_lag_s": round(med, 3)}
        if miss_rate >= MISS_FAIL or med > LAG_FAIL_S:
            say("  LIPSYNC VERDICT: FAIL - her <-> voice unpaid: the voice claims syllables her"
                " mouth does not deliver on time (the speed-mode dance signature).")
            return done({**base, "verdict": "FAIL"}, 1)
        if miss_rate >= MISS_REVIEW or med > LAG_REVIEW_S:
            say("  LIPSYNC VERDICT: REVIEW - borderline sync; my eye decides.")
            return done({**base, "verdict": "REVIEW"}, 2)
        say("  LIPSYNC VERDICT: PASS - mouth pays each vocal onset on time.")
        return done({**base, "verdict": "PASS"}, 0)
    else:
        # continuous speech: correlate
        me = mouth - mouth.mean(); ee = env - env.mean()
        # The correlation is sampled in 1/HZ bins, so the raw peak can only ever land on a 50 ms
        # grid. Taking it whole gave 164 ms of scatter against a known shift, four times the
        # resolution a threshold on this axis needs, which evals/certify.py called BLIND. Fitting
        # a parabola through the peak and its two neighbours recovers the sub-bin position
        # (2026-09-21).
        curve = {}
        for lag_bins in range(-int(0.6*HZ), int(0.6*HZ) + 1):
            if lag_bins < 0: x, y = me[-lag_bins:], ee[:lag_bins] if lag_bins else ee
            elif lag_bins > 0: x, y = me[:-lag_bins], ee[lag_bins:]
            else: x, y = me, ee
            if len(x) < 20: continue
            curve[lag_bins] = float(np.corrcoef(x, y)[0, 1])
        if not curve:
            say("lipsync_probe: too little overlap to correlate")
            return 2
        k = max(curve, key=curve.get)
        best = curve[k]
        left, right = curve.get(k - 1), curve.get(k + 1)
        offset = 0.0
        if left is not None and right is not None:
            denom = left - 2 * best + right
            if denom < -1e-12:
                offset = max(-0.5, min(0.5, 0.5 * (left - right) / denom))
        bl = (k + offset) / HZ
        say(f"  mode: CORR (continuous speech) | best correlation {best:.2f} at lag {bl:+.2f}s")
        base = {"clip": path, "mode": "corr", "corr": round(best, 3), "lag_s": round(bl, 3)}
        if best < CORR_FAIL:
            say("  LIPSYNC VERDICT: FAIL - mouth motion is unrelated to the audio.")
            return done({**base, "verdict": "FAIL"}, 1)
        if abs(bl) <= CORR_LAG_S and best >= CORR_PASS:
            say("  LIPSYNC VERDICT: PASS - mouth tracks the speech envelope in time.")
            return done({**base, "verdict": "PASS"}, 0)
        say("  LIPSYNC VERDICT: REVIEW - weak or offset tracking; my eye decides.")
        return done({**base, "verdict": "REVIEW"}, 2)

if __name__ == "__main__":
    sys.exit(main())
