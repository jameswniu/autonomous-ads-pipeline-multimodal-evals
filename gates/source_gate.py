#!/usr/bin/env python3
"""source_gate.py <flat_clip.mp4>: measure the two source-render defects the author named on
2026-08-27 ("Her jaw/chin always gets stretched", "movement becomes super robotic towards
the back. It doesn't end smoothly") on the FLAT HeyGen render, before any glass conversion.

Prints three numbers, no verdicts. Thresholds live with the caller, calibrated against
clips whose verdicts the author actually gave. Raw numbers only, so the metric and the gate
can be argued about separately.

  jaw_rubber   how much the chin travels beyond what the lips explain, as a fraction of
               face height. Per frame: chin overshoot = |d(chin_y) - d(lip_gap)| where d
               is the change from the clip's median. Reported: 95th percentile overshoot.
               Rubber jaw = the chin swinging further than the mouth opening warrants.
  end_ratio    mean abs frame diff over the final 1.5s divided by the same over the middle
               60% of the clip. Robotic settle = ratio far below 1.
  loop_jump    mean abs frame diff between the last frame and the first frame, the size of
               the restart teleport when the file loops.
"""
import subprocess, sys, tempfile, os, glob
import numpy as np
from PIL import Image

CLIP = sys.argv[1]
FPS_SAMPLE = 5  # landmark sampling rate; motion metrics use 10

def probe_dur(p):
    out = subprocess.run(["ffprobe","-v","error","-show_entries","format=duration",
                          "-of","csv=p=0",p], capture_output=True, text=True).stdout.strip()
    return float(out)

def extract(p, rate, w, outpat, ss=None, t=None):
    cmd = ["ffmpeg","-v","error"]
    if ss is not None: cmd += ["-ss",str(ss)]
    cmd += ["-i",p]
    if t is not None: cmd += ["-t",str(t)]
    cmd += ["-vf",f"fps={rate},scale={w}:-2","-f","image2",outpat,"-y"]
    subprocess.run(cmd, check=True)

dur = probe_dur(CLIP)
work = tempfile.mkdtemp()

# Optional window, SG_START and SG_DUR in seconds. An ad master is mostly b-roll and other
# people's faces, so its caller passes the closer's span; a daily brief is her face in every
# frame and passes nothing. Reported 2026-08-27 by the ad pipeline, whose whole-file numbers
# read 0.58 to 2.53 against 0.15 to 0.19 on the closers themselves.
_ss = float(os.environ["SG_START"]) if os.environ.get("SG_START") else None
_t = float(os.environ["SG_DUR"]) if os.environ.get("SG_DUR") else None
if _ss is not None or _t is not None:
    dur = _t if _t is not None else max(0.0, dur - (_ss or 0.0))

# ---- jaw_rubber via mediapipe FaceLandmarker (chin 152, upper lip 13, lower lip 14,
# eyes 33/263 for face height normalization)
import mediapipe as mp
from mediapipe.tasks import python as mp_python
from mediapipe.tasks.python import vision
import urllib.request
# Pinned model (adversarial review, 2026-08-27): the "latest" URL is mutable, and a
# re-download on a clean machine could silently shift landmark behaviour under a metric
# that was calibrated on this artifact. Pinned by SHA256; missing or mismatched fails closed.
import hashlib
MODEL = os.environ.get("FACE_LANDMARKER_TASK", os.path.expanduser("~/.cache/face_landmarker.task"))
MODEL_SHA256 = "64184e229b263107bc2b804c6625db1341ff2bb731874b0bcc2fe6544e0bc9ff"
MODEL_URL = "https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/latest/face_landmarker.task"
if not os.path.exists(MODEL):
    urllib.request.urlretrieve(MODEL_URL, MODEL)
_got = hashlib.sha256(open(MODEL, "rb").read()).hexdigest()
if _got != MODEL_SHA256:
    sys.exit(f"source_gate: face_landmarker.task sha256 {_got[:12]} != pinned {MODEL_SHA256[:12]}; refusing to measure with an unpinned model")
opts = vision.FaceLandmarkerOptions(base_options=mp_python.BaseOptions(model_asset_path=MODEL), num_faces=1)
lm = vision.FaceLandmarker.create_from_options(opts)

extract(CLIP, FPS_SAMPLE, 540, work+"/f%04d.png", ss=_ss, t=_t)
chin, lipgap, faceh = [], [], []
_sampled = sorted(glob.glob(work+"/f*.png"))
for p in _sampled:
    img = mp.Image.create_from_file(p)
    r = lm.detect(img)
    if not r.face_landmarks: continue
    L = r.face_landmarks[0]
    chin.append(L[152].y); lipgap.append(abs(L[14].y - L[13].y))
    faceh.append(abs(L[152].y - (L[33].y + L[263].y)/2))
# Face coverage: the fraction of sampled frames with a face. The jaw number means nothing
# when most of the span has no face or someone else's; callers skip it under 0.7.
print(f"face_cov {len(chin)/max(len(_sampled),1):.3f}")
if len(chin) < 20:
    print("jaw_rubber nan (face found in only", len(chin), "frames)")
    jaw = float("nan")
else:
    chin = np.array(chin); lipgap = np.array(lipgap); fh = float(np.median(faceh))
    d_chin = chin - np.median(chin)
    d_lip = lipgap - np.median(lipgap)
    overshoot = np.abs(d_chin - d_lip) / fh
    jaw = float(np.percentile(overshoot, 95))
    print(f"jaw_rubber {jaw:.4f}")
    # Face height as a fraction of frame height, the look-side feature the pre-gate needs.
    # Three looks so far read 0.125 / 0.172 / 0.193 on jaw_rubber with the same engine and
    # voice, so the look is the lever; this number is logged per brief until enough points
    # exist to set a rule, rather than guessing one from three.
    print(f"face_h {fh:.4f}")

# ---- end_ratio and loop_jump on small grey frames at 10fps
extract(CLIP, 10, 320, work+"/g%05d.png", ss=_ss, t=_t)
gs = [np.asarray(Image.open(p).convert("L"), float) for p in sorted(glob.glob(work+"/g*.png"))]
diffs = np.array([np.abs(gs[i]-gs[i-1]).mean() for i in range(1, len(gs))])
n = len(diffs)
mid = diffs[int(n*0.2):int(n*0.8)]
tail = diffs[-15:]  # last 1.5s at 10fps
end_ratio = float(tail.mean() / max(mid.mean(), 1e-6))
loop_jump = float(np.abs(gs[-1]-gs[0]).mean())
print(f"end_ratio {end_ratio:.3f}")
print(f"loop_jump {loop_jump:.2f}")
