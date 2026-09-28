#!/usr/bin/env python3
"""spasm_probe.py — "face spasm" detector for talking-head renders (v3, silence-mouth).

WHAT THE DEFECT ACTUALLY IS (calibrated 2026-07-25, the morning stage episode): after the
last spoken word (and inside long pauses), the engine keeps the mouth and lower face
WORKING — churn with nothing being said. That violates her<->VOICE coherence in both
directions (a sung syllable implies a mouth shape; SILENCE implies a settling mouth)
and reads to a human as "her face is spasming." I caught it twice; three separate
frame-scale motion metrics (translation reversals, rotation shear, flicker index) all
scored the labeled-bad regions UNREMARKABLE — the artifact is not fast oscillation,
it is mouth activity where the audio says quiet.

Discriminability on hand-labeled takes (post/speech mouth-energy ratio):
    fix-beach  1.44  <- "there's still spasm" (the take I called out)
    fix-nook   1.00
    fix-flower 0.71
    fix-bakery 0.51
A settled ending should be well BELOW speech level.

Method: decode the mouth band (center 1/4 width, 1/7 height at 42% down — 1:1
talking-head geometry) at the clip's real fps; per-frame mean abs diff = mouth
activity; SRT sidecar gives speech spans (same audio => same cues for every take).
Score = post-speech mean / speech mean, plus the worst 1s post window and the
inter-cue-gap ratio.

Verdict: FAIL when post-speech runway is under 0.30 * fps frames, else REPORT;
no PASS or WARN is ever emitted. Exit 0 REPORT / 2 FAIL.
Usage: spasm_probe.py <clip.mp4> <sidecar.srt> [--json]
"""
import json
import re
import subprocess
import sys

import numpy as np

POST_GRACE_S = 0.15     # let the final phoneme close


def clip_fps(path: str) -> float:
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
         "stream=r_frame_rate", "-of", "json", path], capture_output=True, text=True)
    num, den = json.loads(probe.stdout)["streams"][0]["r_frame_rate"].split("/")
    return float(num) / float(den)


def content_band(path: str):
    """Detect real content rows (letterbox padding is flat white): (y0, content_h, w, h).
    A fixed-fraction crop on a letterboxed frame lands in static padding and skews
    the ratio (r6 episode); geometry is detected, never assumed."""
    probe = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0",
                            "-show_entries", "stream=width,height", "-of", "csv=p=0", path],
                           capture_output=True, text=True)
    w, h = (int(x) for x in probe.stdout.strip().split(","))
    raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", "5", "-i", path, "-frames:v", "1",
                          "-f", "rawvideo", "-pix_fmt", "gray", "pipe:1"], capture_output=True).stdout
    fr = np.frombuffer(raw[: w * h], dtype=np.uint8).reshape(h, w)
    rows = np.where(fr.mean(axis=1) <= 235)[0]
    if len(rows) < h * 0.2:
        return 0, h, w, h
    return int(rows.min()), int(rows.max() - rows.min() + 1), w, h


def mouth_series(path: str) -> np.ndarray:
    y0, ch, w, h = content_band(path)
    crop = f"crop={w // 4}:{ch // 7}:{int(w * 0.375)}:{y0 + int(0.42 * ch)}"
    cmd = ["ffmpeg", "-v", "error", "-i", path, "-vf",
           f"{crop},scale=160:90,format=gray",
           "-f", "rawvideo", "pipe:1"]
    raw = subprocess.run(cmd, capture_output=True).stdout
    n = len(raw) // (160 * 90)
    fr = np.frombuffer(raw[: n * 160 * 90], dtype=np.uint8).reshape(n, 90, 160).astype(np.float32)
    return np.abs(np.diff(fr, axis=0)).mean(axis=(1, 2))


def srt_spans(srt: str):
    ts = re.findall(r"(\d\d):(\d\d):(\d\d),(\d\d\d) --> (\d\d):(\d\d):(\d\d),(\d\d\d)", open(srt).read())
    return [(int(a[1]) * 60 + int(a[2]) + int(a[3]) / 1000,
             int(a[5]) * 60 + int(a[6]) + int(a[7]) / 1000) for a in ts]


def main():
    positional = [a for a in sys.argv[1:] if not a.startswith("-")]
    if len(positional) < 2:
        print("usage: spasm_probe.py CLIP.mp4 CUES.srt", file=sys.stderr)
        return 2
    path, srt = positional[0], positional[1]
    as_json = "--json" in sys.argv
    fps = clip_fps(path)
    d = mouth_series(path)
    t = np.arange(len(d)) / fps
    spans = srt_spans(srt)
    speech_end = spans[-1][1]
    in_speech = np.zeros(len(d), bool)
    for s, e in spans:
        in_speech |= (t >= s) & (t <= e)
    post = t > speech_end + POST_GRACE_S
    gaps = (~in_speech) & (~post) & (t > 0.2)
    sp = float(d[in_speech].mean()) if in_speech.any() else 0.0
    po = float(d[post].mean()) if post.any() else 0.0
    ga = float(d[gaps].mean()) if gaps.any() else 0.0
    dp = d[post]
    w = int(round(fps))
    worst = 0.0
    if len(dp):
        for i in range(max(1, len(dp) - w)):
            worst = max(worst, float(dp[i:i + w].mean()))
    ratio = po / max(sp, 0.01)
    if post.sum() < 0.30 * fps:
        # audio (and clip) end at the last word: no settle runway exists at all — the
        # boundary-cram condition itself. Structural FAIL regardless of measured ratio.
        #
        # THRESHOLD ALIGNED 2026-07-26. It was 0.5*fps, which is STRICTER than the settle-pad step's own
        # contract (--check passes at 0.4s, default pad 0.6s). Correctly padded clips measured
        # 0.59-0.64s of tail and tripped this anyway, so the probe was reporting a cut-off on clips
        # whose settle beat had worked perfectly. 0.30 sits below the padder's guarantee, so this
        # now fires only when there is genuinely no runway.
        verdict = "FAIL"
        ratio = float("inf") if not post.any() else ratio
    else:
        # RATIO IS NOT A VERDICT (2026-07-26): "you're measuring it wrongly... it has to be
        # against the energy. It's not against stillness. If you measure against stillness, you're
        # always going to penalize the excited ones."
        #
        # post/speech divides by SPEECH motion, which silently makes STILLNESS the ideal: a clip
        # only scores well if her mouth goes near-dead in the gaps. But an animated person keeps
        # breathing, emoting and moving between sentences, so an EXCITED clip is marked down for
        # being excited - the defect is manufactured by the denominator, not observed.
        #
        # Proof it inverts: M1 measured 1.45 here, nearly 2x the old fail bar and beside a 1.44 I
        # had rejected by eye, and my verdict on M1 was "this is ok". Its ABSOLUTE motion is low
        # (speech 2.72); she simply does not go still in the gaps.
        #
        # This is invariant 10 (state-movement coherence), which was already written down and then
        # ignored here for a fixed number. So the probe now reports ENERGY and stops adjudicating.
        # Only the caller knows the script's register, and per this skill's standing rule my eye
        # outranks the meter. Callers: read `energy` and `ratio` TOGETHER against the register.
        verdict = "REPORT"
    energy = max(sp, po, ga)
    out = {"clip": path, "fps": round(fps, 2), "speech_mouth": round(sp, 2),
           "gap_mouth": round(ga, 2), "post_mouth": round(po, 2), "energy": round(energy, 2),
           "worst1s_post": round(worst, 2), "post_speech_ratio": round(ratio, 2),
           "post_frames": int(post.sum()), "verdict": verdict}
    if as_json:
        print(json.dumps(out))
    elif verdict == "FAIL":
        print(f"SPASM FAIL (structural): the clip ends at the last word, so no settle runway "
              f"exists at all (speech {sp:.2f}, post {po:.2f}). Fix with the settle-pad step, not a re-roll.")
    else:
        print(f"SPASM REPORT: energy {energy:.2f} | ratio {ratio:.2f} "
              f"(speech {sp:.2f}, post {po:.2f}, worst1s {worst:.2f}, gaps {ga:.2f})")
        print(f"  NOT a verdict. Judge against the script's REGISTER, never against stillness: a "
              f"calm line should settle, an excited one should not (invariant 10).")
    sys.exit(2 if verdict == "FAIL" else 0)


if __name__ == "__main__":
    sys.exit(main())
