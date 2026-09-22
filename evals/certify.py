#!/usr/bin/env python3
"""Certify that each lip-sync probe can still measure the thing it gates on.

WHY THIS IS NOT A LABEL SOURCE. The obvious idea is to shift a clip's audio by a known amount,
call the result a reject, and derive a threshold from it. That fails here for three measured
reasons, all of them in this repository. shoots/build-ad.sh already trims each closer by
mouth_sync_probe's own reading, so the released masters were pre-corrected by the probe the
injection would calibrate. Across those masters the baseline lag spans 240 ms, wider than any
dose worth injecting, so an injected reject reads as a pass on a master that started early. And
correlation does not separate the human verdicts at all: eye-approved masters read 0.14 to 0.45
while human rejects read 0.05 to 0.23, so a floor derived this way would be printed DERIVED while
the labels refute it.

WHAT A KNOWN SHIFT DOES TELL YOU. Whether the needle moves. Apply a dose, read the probe, and fit
the readings against the doses. Two numbers come out, both properties of the instrument and of no
opinion:

  slope   does a 100 ms shift read as 100 ms? A probe at slope 0.2 has stopped tracking its axis.
  sigma   the residual scatter. A probe with 80 ms of scatter cannot resolve an 80 ms difference,
          so no threshold on that axis means anything, from labels injected or human.

The line itself stays where a human put it, from verdicts already recorded. This file supplies the
precision; evals/labels.csv supplies the edges; evals/derive.py requires the threshold to clear
both edges by a margin of k sigma, so a probe that goes blind fails the build instead of quietly
passing everything.

THE CLIP IS SYNTHETIC ON PURPOSE. A bar whose height follows the audio envelope exactly. Real
footage would import the very thing being measured, the engine's own sync error, into the ruler.
A synthetic clip has no sync error by construction, so every millimetre the needle moves is the
dose. It is a set of known weights, not a recipe.

WHAT IT DOES NOT CERTIFY. A synthetic bar is an ideal subject, so this measures the ALGORITHM's
resolution, not whether the probe survives a real framing. Those are different, and this
repository already knows it: gates/ad_gates.sh records sync_probe moving only 80 ms for a known
400 ms shift on a real closer, while mouth_sync_probe moved 560 ms on the same controls. Pass a
real master with --clip to certify that half, and read the two results as the separate claims
they are.

    python3 evals/certify.py            certify both probes on the reference clip
    python3 evals/certify.py --write    and update evals/certificates.json
    python3 evals/certify.py --clip master.mp4    certify against a real render instead

Exit 0 every probe tracks its axis / 1 one does not / 64 ffmpeg or a probe is unusable.
"""
import argparse
import json
import math
import os
import subprocess
import sys
import tempfile
import wave

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RECEIPT = os.path.join(ROOT, "evals", "certificates.json")

FPS = 25
SECONDS = 14
SIZE = 512
SR = 16000
DOSES_MS = (-160, -120, -80, -40, 0, 40, 80, 120, 160)

# A probe has to resolve the distinction its threshold draws. sync_probe's labelled worst pass is
# +40 ms and its best reject is +120 ms, an 80 ms gap, so scatter of half that leaves nothing to
# measure with. Slope is the same test in the other axis: below 0.8 the probe is reading a shift
# as something smaller than it is.
SLOPE_MIN = 0.8
SIGMA_MAX_MS = 40.0

# Each probe's sign convention, declared, because they are OPPOSITE and a silent inversion has
# already cost this pipeline a shipped desync (gates/mouth_sync_probe.py, 2026-08-26). Delaying
# the audio makes the mouth lead. sync_probe calls a trailing mouth positive, so it must go
# negative; lipsync_probe's correlation lag calls a leading mouth positive, so it must go up.
EXPECT_SIGN = {"sync_probe": -1, "lipsync_probe": +1}


# The reference envelope: an APERIODIC syllable train, fixed seed, so the clip is identical on
# every machine and every run. Aperiodic is the load-bearing word. The first version modulated a
# sine at 2.3 Hz, which gave the correlation an identical peak every 435 ms, and the probes'
# argmax jumped between aliases: readings of -600, -536 and +48 ms for doses 80 ms apart. A
# periodic stimulus cannot measure lag, however clean it looks. It also never falls quiet for
# long, so the onset detector stays out and the correlation path is what gets certified.
_RNG = np.random.default_rng(7)
_CENTRES, _T = [], 0.0
while _T < SECONDS + 1:
    _T += float(_RNG.uniform(0.18, 0.42))
    _CENTRES.append((_T, float(_RNG.uniform(0.05, 0.09)), float(_RNG.uniform(0.45, 1.0))))


def envelope_at(t):
    """Amplitude at time t: overlapping syllable bursts on a quiet floor."""
    v = 0.22
    for c, w, a in _CENTRES:
        d = t - c
        if abs(d) < 3 * w:
            v += a * math.exp(-0.5 * (d / w) ** 2)
    return min(1.0, v)


def build(tmp):
    """A silent video and a wav whose envelope drives the bar's height, frame for frame."""
    import cv2
    vid = os.path.join(tmp, "v.mp4")
    wav = os.path.join(tmp, "a.wav")
    w = cv2.VideoWriter(vid, cv2.VideoWriter_fourcc(*"mp4v"), FPS, (SIZE, SIZE))
    for i in range(SECONDS * FPS):
        f = np.full((SIZE, SIZE, 3), 40, dtype=np.uint8)
        openness = envelope_at(i / FPS)
        # Both probes measure MOTION, the frame-to-frame difference, against the audio envelope.
        # A smoothly opening mouth makes motion the derivative of the envelope, which has two
        # lobes per syllable straddling its peak, and the correlation then favours either lobe:
        # measured slope flipped sign between runs. Alternating open and shut each frame makes
        # the motion itself proportional to the envelope, in phase, with one peak (2026-09-21).
        half = 6 + int(44 * openness) if i % 2 == 0 else 6
        cy, cx = int(SIZE * 0.41), int(SIZE * 0.50)
        f[cy - half:cy + half, cx - 70:cx + 70] = 235
        w.write(f)
    w.release()
    n = SECONDS * SR
    t = np.arange(n) / SR
    env = np.array([envelope_at(x) for x in t])
    tone = np.sin(2 * math.pi * 180 * t) * env
    with wave.open(wav, "w") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(SR)
        out.writeframes((tone * 20000).astype(np.int16).tobytes())
    return vid, wav


def split(clip, tmp):
    """A real render, taken apart into a silent video and its audio, so doses can be applied to
    the audio the same way the reference clip gets them."""
    vid, wav = os.path.join(tmp, "rv.mp4"), os.path.join(tmp, "ra.wav")
    subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", clip, "-an", "-c:v", "copy", vid],
                   check=True, capture_output=True)
    subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", clip, "-vn", "-ac", "1",
                    "-ar", str(SR), wav], check=True, capture_output=True)
    return vid, wav


def samples(path):
    with wave.open(path) as w:
        return np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32)


def dosed(vid, wav, ms, out):
    """Mux the audio against the video, shifted by ms. Positive delays the audio.

    The shift is cut into the SAMPLES. Asking ffmpeg for it with -itsoffset silently caps a
    positive delay at about 75 ms, so doses of 80, 120 and 160 ms all arrived as 75 and both
    probes dutifully reported the same number three times. The harness read that as two probes
    saturating and nearly cost them a BLIND verdict they had not earned (2026-09-21). A ruler
    needs its own calibration, which is what verify_dose below is for.
    """
    a = samples(wav)
    n = abs(int(round(ms * SR / 1000.0)))
    if ms > 0:
        a = np.concatenate([np.zeros(n, dtype=np.float32), a])
    elif ms < 0:
        a = a[n:]
    shifted = out.replace(".mp4", ".wav")
    with wave.open(shifted, "w") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(a.astype(np.int16).tobytes())
    subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", vid, "-i", shifted,
                    "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-c:a", "aac", "-shortest", out],
                   check=True, capture_output=True)
    return out


def verify_dose(clip, wav, ms, tol_ms=10.0):
    """Cross-correlate the delivered audio against the reference to confirm the dose landed."""
    raw = subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-i", clip, "-ac", "1",
                          "-ar", str(SR), "-f", "s16le", "pipe:1"], capture_output=True).stdout
    got = np.frombuffer(raw, dtype=np.int16).astype(np.float32)
    ref = samples(wav)
    n = min(len(ref), len(got)) - SR // 2
    if n < SR:
        return None
    best, at = -2.0, 0
    for shift in range(-SR // 4, SR // 4 + 1, SR // 400):
        a, b = ref[SR // 4: SR // 4 + n], got[SR // 4 + shift: SR // 4 + shift + n]
        if len(b) != len(a):
            continue
        c = float(np.corrcoef(a, b)[0, 1])
        if c > best:
            best, at = c, shift
    delivered = at * 1000.0 / SR
    return delivered if abs(delivered - ms) <= tol_ms else None


def read(probe, clip):
    """The lag this probe reports, in milliseconds, or None when it could not measure."""
    r = subprocess.run([sys.executable, os.path.join(ROOT, "probes", f"{probe}.py"), clip, "--json"],
                       capture_output=True, text=True, timeout=300)
    line = next((ln for ln in reversed(r.stdout.splitlines()) if ln.strip().startswith("{")), None)
    if not line:
        return None
    d = json.loads(line)
    if probe == "sync_probe":
        return float(d["lag_ms"])
    if d.get("mode") != "corr":
        return None
    return float(d["lag_s"]) * 1000.0


def fit(doses, measured):
    """Least squares slope and intercept, plus the residual scatter around that line."""
    x = np.array(doses, dtype=float)
    y = np.array(measured, dtype=float)
    slope, intercept = np.polyfit(x, y, 1)
    resid = y - (slope * x + intercept)
    sigma = float(np.sqrt((resid ** 2).sum() / max(len(x) - 2, 1)))
    return float(slope), float(intercept), sigma


def tracks(slope, sigma, expect):
    """Does the probe still measure its own axis? Three ways it can fail to.

    The sign has to match the convention the probe documents, because the two probes here use
    OPPOSITE ones and a silent inversion already cost this pipeline a shipped desync. The
    magnitude has to be close to one, or the probe is reading a shift as something smaller than
    it is. And the scatter has to be finer than the distinction the threshold draws: the labelled
    worst pass is +40 ms and the best reject +120 ms, so 40 ms of noise leaves nothing to measure.
    """
    return abs(slope) >= SLOPE_MIN and sigma <= SIGMA_MAX_MS and (slope > 0) == (expect > 0)


def certify(probe, vid, wav, tmp):
    doses, measured = [], []
    skipped = []
    for ms in DOSES_MS:
        clip = dosed(vid, wav, ms, os.path.join(tmp, f"{probe}-{ms}.mp4"))
        # Confirm the clip carries the dose before believing what the probe says about it.
        if verify_dose(clip, wav, ms) is None:
            skipped.append(ms)
            continue
        got = read(probe, clip)
        if got is None:
            skipped.append(ms)
            continue
        doses.append(ms)
        measured.append(got)
    # Every dose has to read. Dropping the ones that do not and fitting a line through what is
    # left is how a probe blind on its whole positive side still certifies as tracking, which is
    # the same fail-open shape the gates in this repository were full of (2026-09-21).
    if skipped:
        return {"probe": probe, "doses_ms": doses, "skipped_ms": skipped,
                "verdict": "INCOMPLETE"}
    slope, intercept, sigma = fit(doses, measured)
    expect = EXPECT_SIGN[probe]
    return {"probe": probe, "doses_ms": doses, "measured_ms": [round(m, 1) for m in measured],
            "slope": round(slope, 3), "expected_sign": expect, "intercept_ms": round(intercept, 1),
            "sigma_ms": round(sigma, 1), "slope_min": SLOPE_MIN, "sigma_max_ms": SIGMA_MAX_MS,
            "skipped_ms": skipped,
            "verdict": "TRACKS" if tracks(slope, sigma, expect) else "BLIND"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true", help="update evals/certificates.json")
    ap.add_argument("--probe", default=None, help="certify one probe instead of every probe")
    ap.add_argument("--clip", default=None, help="certify against a real render instead of the reference")
    a = ap.parse_args()
    names = [a.probe] if a.probe else sorted(EXPECT_SIGN)
    with tempfile.TemporaryDirectory() as tmp:
        try:
            if a.clip:
                vid, wav = split(a.clip, tmp)
                subject = f"real render, {os.path.basename(a.clip)}"
            else:
                vid, wav = build(tmp)
                subject = "synthetic, a bar whose motion follows the audio envelope"
        except Exception as e:
            print(f"certify: could not prepare the subject clip: {e}", file=sys.stderr)
            return 64
        out = {"clip": subject, "seconds": SECONDS, "fps": FPS,
               "certificates": [certify(n, vid, wav, tmp) for n in names]}
    for c in out["certificates"]:
        if c["verdict"] == "INCOMPLETE":
            print(f"  {c['probe']:16s} INCOMPLETE, {len(c['skipped_ms'])} of {len(DOSES_MS)} doses "
                  f"never read: {c['skipped_ms']}")
            continue
        print(f"  {c['probe']:16s} {c['verdict']:6s} slope {c['slope']:+.2f} "
              f"(sign {c['expected_sign']:+d} expected)  sigma {c['sigma_ms']:.1f} ms  "
              f"n={len(c['doses_ms'])}")
    if a.write:
        json.dump(out, open(RECEIPT, "w"), indent=2)
        print(f"  receipt written to {os.path.relpath(RECEIPT, ROOT)}")
    return 0 if all(c["verdict"] == "TRACKS" for c in out["certificates"]) else 1


if __name__ == "__main__":
    sys.exit(main())
