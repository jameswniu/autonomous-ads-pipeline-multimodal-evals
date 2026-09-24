#!/usr/bin/env bash
# ship_gate.sh <final.mp4> <sidecar.srt> [directional] [--arrow-ok]
#
# MECHANICAL pre-delivery gate. Born 2026-07-25 after I caught the same two
# regression classes AGAIN on a delivered clip (letterbox borders; backward ocean):
# both were pre-warned in prop_gate PROSE and skipped under momentum. Lessons kept
# as prose regress; lessons kept as blocking mechanisms do not (prop_gate attest,
# the pre-publish gate in tools/). prop_gate guards the LOOK before the render spend; this
# guards the RENDER before delivery - the stage that had no mechanical check.
#
# Checks, in order:
#   1. GEOMETRY  - content band must fill >= 90% of frame height (letterbox = FAIL;
#                  the fix is a fit=cover re-render, never shipping borders). Bright bars
#                  and dark bars both count, a dark row only when it is flat and never moves.
#   2. SPASM     - spasm_probe FAIL (exit 2) blocks. WARN prints for the eye.
#   3. COHERENCE - rest/lock/phase printed; FLAG prints for the eye (outdoor
#                  confound means rest alone never hard-blocks here).
#   4. ARROW     - if "directional" is passed (water/traffic/crowd scenes): builds
#                  a slit-scan x-t image and EXITS 3 demanding an eye-read. Rerun
#                  with --arrow-ok only after actually reading the slit-scan
#                  (forward flow = one-way slope; palindrome V = ping-pong REJECT).
#                  ARROW_WINDOW="T0:T1" (seconds) is the stretch the side-band measure
#                  reads and the auto scan shows. Unset, both use 8 to 16 s.
#
# Both HOLDs that ask for an eye-read write their slit-scan BESIDE the clip, as
# <name>.arrow.png for the directional hold and <name>.replay.png for the replay hold,
# and name it on a line of its own: "slit-scan: <path>". A scan that could not be
# written fails the gate with 64 rather than asking a reader to read nothing.
#
# On pass: writes /tmp/.ship-gate-<basename>-<bytes> marker. NOTE: the reader of
# that marker (deliver.sh) is NOT in this repository, so here the marker is a
# receipt and nothing enforces it. In the private tree deliver.sh refuses
# files without a fresh marker, so skipping this gate is not possible by forgetting.
set -uo pipefail
F="$1"; SRT="$2"; DIRECTIONAL="${3:-}"; ARROWOK=""
[[ "${3:-}" == "--arrow-ok" || "${4:-}" == "--arrow-ok" ]] && ARROWOK=1
[[ "$DIRECTIONAL" == "--arrow-ok" ]] && DIRECTIONAL=""
# fail LOUD on unreadable input: a missing file must never PASS with empty metrics
# (discovered 2026-07-25 when a broken caller loop handed this gate nonexistent paths
# and every check silently defaulted clean)
[ -s "$F" ] || { echo "SHIP-GATE ERROR: input not readable: $F"; exit 64; }
[ -s "$SRT" ] || { echo "SHIP-GATE ERROR: srt not readable: $SRT"; exit 64; }
BYTES=$(stat -f%z "$F" 2>/dev/null || stat -c%s "$F" 2>/dev/null || echo 0)
MARK="/tmp/.ship-gate-$(basename "$F")-$BYTES"
SKILL="${PIPELINE_PROBES:-$(cd "$(dirname "$0")/../probes" 2>/dev/null && pwd)}"

# ARROW_WINDOW="T0:T1", in seconds, is the stretch the side-band measure in step 4 reads and
# the auto directional scan shows. Unset, both stay on 8 to 16 s, the August window, which is
# the middle of a single take. On an ad master that window is the tail of scene b, scene c and
# a second of the closer, so scene a was never measured or shown. pipeline/live.py passes
# ARROW_WINDOW="0:<closer_start>", every scene and none of the closer. It is checked here,
# before any probe spends time, because a window that is not a window measures nothing.
AW_T0=8; AW_T1=16
if [ -n "${ARROW_WINDOW:-}" ]; then
  AW=$(python3 - "$ARROW_WINDOW" <<'PY'
import math, re, sys
num = r"([0-9]+(?:\.[0-9]*)?|\.[0-9]+)"
m = re.fullmatch(rf"\s*{num}\s*:\s*{num}\s*", sys.argv[1])
def secs(x):
    return f"{x:.6f}".rstrip("0").rstrip(".") or "0"
if m:
    t0, t1 = float(m.group(1)), float(m.group(2))
    if math.isfinite(t1) and t1 > t0:
        print(secs(t0), secs(t1))
PY
)
  if [ -z "$AW" ]; then
    echo "SHIP-GATE HOLD: ARROW_WINDOW='$ARROW_WINDOW' is not a window. It takes T0:T1 in seconds,"
    echo "two non-negative numbers with T1 after T0, for example 0:15.2."
    rm -f "$MARK"; exit 64
  fi
  read -r AW_T0 AW_T1 <<<"$AW"
fi

# The slit-scan the two eye-read HOLDs hand a reader, written BESIDE the clip and named after
# it: slit_scan <source> <from s> <to s> <arrow|replay>. It used to go to
# /tmp/slit-<basename>.png, where two masters with the same name overwrote each other's scan,
# and nothing checked the file existed before a HOLD asked somebody to read it. The raw strip
# is scratch under TMPDIR and is deleted either way.
slit_scan() {
  local src="$1" t0="$2" t1="$3" kind="$4" stem out raw
  stem="$(basename "$F")"; stem="${stem%.*}"
  out="$(dirname "$F")/$stem.$kind.png"
  raw="${TMPDIR:-/tmp}/.slit.$$.raw"
  # A scan from an earlier run carries the same name and would pass for this run's if the
  # write below failed, so it goes first, and one that cannot be removed stops the gate.
  rm -f "$out" 2>/dev/null
  if [ -e "$out" ]; then
    echo "SHIP-GATE HOLD: an earlier slit-scan at $out could not be removed, so a fresh one"
    echo "cannot be told apart from it. Failing closed."
    rm -f "$MARK"; exit 64
  fi
  ffmpeg -y -v error -ss "$t0" -to "$t1" -i "$src" -vf "crop=2:ih*0.4:iw*0.8:ih*0.25,scale=2:200" \
    -f rawvideo -pix_fmt gray "$raw"
  # The raw strip's path goes to python as an argument. It used to be spelled inside the
  # quoted heredoc, where the shell never expands it, so python got "${TMPDIR:-/tmp}..."
  # as source text, died on a SyntaxError, and the HOLD asked a reader to read a slit-scan
  # that was never written (found 2026-09-23).
  python3 - "$out" "$raw" <<'PY'
import numpy as np, sys
from PIL import Image
raw = np.fromfile(sys.argv[2], dtype=np.uint8)
n = len(raw)//400
xt = raw[:n*400].reshape(n,200,2).mean(axis=2).T
Image.fromarray(xt.astype(np.uint8)).resize((n*3,600), Image.NEAREST).save(sys.argv[1])
PY
  rm -f "$raw"
  # A regular file with bytes in it. -s alone is true of a directory.
  if [ ! -f "$out" ] || [ ! -s "$out" ]; then
    echo "SHIP-GATE HOLD: the slit-scan could not be written to $out, so there is nothing for"
    echo "a reader to read. A HOLD that points at a missing picture is not a hold, so this fails closed."
    rm -f "$MARK"; exit 64
  fi
  echo "slit-scan: $out"
}

# 1. geometry
GEO=$(python3 - "$F" <<'PY'
import subprocess, sys
import numpy as np
path = sys.argv[1]
p = subprocess.run(["ffprobe","-v","error","-select_streams","v:0","-show_entries",
                    "stream=width,height","-of","csv=p=0",path],capture_output=True,text=True)
w,h = (int(x) for x in p.stdout.strip().split(","))
d = subprocess.run(["ffprobe","-v","error","-show_entries","format=duration","-of","csv=p=0",path],
                   capture_output=True,text=True)
dur = float(d.stdout.strip() or 30)
def frame(t):
    raw = subprocess.run(["ffmpeg","-v","error","-ss",str(t),"-i",path,"-frames:v","1",
                          "-f","rawvideo","-pix_fmt","gray","pipe:1"],capture_output=True).stdout
    return np.frombuffer(raw[:w*h],dtype=np.uint8).reshape(h,w).astype(np.float32)
# The three frames this check has always judged, and two more near the ends of the take.
at = {f: frame(dur*f) for f in (0.1, 0.2, 0.5, 0.8, 0.9)}
# Padding is also DARK and flat, and black bars are the commonest letterbox there is. Only
# bright rows used to count, so a black-barred clip passed while the step table said the
# frame fills its height. A dark row counts only when it is flat in every sampled frame AND
# holds the same values across all five of them, because a night sky or a dim room is dark
# and still carries grain or movement, while a bar never changes. Only a band running in from
# the top or bottom edge can shorten the content extent measured below, so a still dark stripe
# across the middle of a frame never reads as padding.
stack = np.stack(list(at.values()))
dark = ((stack.mean(axis=2) < 40) & (stack.std(axis=2) < 2.0)).all(axis=0)
still = np.abs(stack - stack[0]).mean(axis=2).max(axis=0) < 2.0
dark_pad = dark & still
bad = 0
for f in (0.2, 0.5, 0.8):
    fr = at[f]
    # padding is BRIGHT *and* FLAT; a pale sky or sunlit sand is bright with texture,
    # so brightness alone false-alarms (fired on the morning-foam ocean scene 2026-07-26).
    pad_row = ((fr.mean(axis=1) > 235) & (fr.std(axis=1) < 2.0)) | dark_pad
    rows = np.where(~pad_row)[0]
    ch = (rows.max()-rows.min()+1) if len(rows) else 0
    if ch < 0.9*h: bad += 1
print("LETTERBOX" if bad >= 2 else "FULLBLEED", w, h)
PY
)
echo "geometry: $GEO"
if [[ "$GEO" == LETTERBOX* ]]; then
  echo "SHIP-GATE FAIL: letterboxed frame - re-render with fit=cover, never ship borders"
  rm -f "$MARK"; exit 1
fi
if [[ "$GEO" != FULLBLEED* ]]; then
  echo "SHIP-GATE ERROR: geometry unreadable (got: '$GEO') - refusing to pass blind"
  rm -f "$MARK"; exit 64
fi

# 2 + 3. probes (content-aware). Finals are TRIMMED (settle runway removed by design),
# which trips spasm_probe's structural no-runway FAIL - so probes run on the RAW take
# (env RAW=<raw.mp4>) when provided, while geometry/arrow always check the deliverable.
PROBE_SRC="${RAW:-$F}"
[ "$PROBE_SRC" != "$F" ] && echo "probes on raw take: $(basename "$PROBE_SRC")"
# SPASM NOW HOLDS (2026-07-26). It was INFO ONLY, on the reasoning that the mouth band is
# framing-dependent per look. That reasoning let five one-take briefs ship at 0.65-1.63 - three
# past the fail bar, one past the 1.44 clip I had already rejected - and I caught every one
# by eye in a single viewing. Worse, the gate PRINTED those numbers and the model truncated its output
# with `tail -1`, so the information existed and was thrown away. A number that only prints is a
# number that gets skipped under momentum; the whole point of this file is mechanisms over prose.
# The framing caveat is real, so this HOLDS for a declared reason rather than hard-rejecting:
#   SPASMOK="<why this look's band reads high / why my eye passed it>"
# The fix when it holds is usually not an override at all - it is the best-take step (meter N takes,
# ship the lowest; takes of one scene span 0.51-1.44, so selection IS the spasm fix).
# LIPSYNC (added 2026-07-26). The one metric that reproduces my labels 8/8: mouth-band motion
# cross-correlated against the audio envelope. My passes run -240..+40ms, my two "lip sync is a bit
# off" rejects measured +120 and +240ms. A trailing mouth BLOCKS, because it is re-rollable.
SYNC_OUT=$(python3 "$SKILL/sync_probe.py" "$PROBE_SRC" 2>&1); SYNC_RC=$?
echo "$SYNC_OUT" | sed 's/^/  /'
if [ "$SYNC_RC" -eq 1 ]; then
  echo ">>> SYNC DISCLOSURE (NOT a block): whole-clip lag reads high, but the measurement is UNSTABLE."
  echo "    Measured in thirds, the same clip swings 6-10 frames (F1, a clip I called good, reads"
  echo "    -1 / -5 / +1). So this number averages noise and must NOT gate anything. Disclose it and"
  echo "    let my ear decide. Downgraded from a blocker 2026-07-26, the same hour it was added."
fi

SPASM_OUT=$(python3 "$SKILL/spasm_probe.py" "$PROBE_SRC" "$SRT" 2>&1); SPASM_RC=$?
echo "$SPASM_OUT"
# THE GRAPH PHASE (2026-07-26): the invariants/pairs handle OSCILLATION (bright-dim) and the
# PALINDROME (reversal); the GRAPH handles ROBOTIC MOVEMENT, because robotic-ness is not a threshold
# on one pair, it is whether her state carries coherently node-to-node through time. This probe was
# built for exactly that and then regressed by DEMOTION, not deletion: wired `|| true`, printed, and
# truncated away with `tail -1` while it flagged all night. A probe that cannot block and is not read
# is a no-op.
# What my labels actually track (n=5, 2026-07-26): DEBT, the accumulated drift between her movement
# and the speech structure. Both clips I called natural sit at 0.16 and 0.32s; everything I rejected
# is 0.40s and up (2.0s on the worst). rest and lock are NOT criteria - my one PERFECT clip has
# rest 0.000, the worst of the set, and the two naturals sit at opposite ends of lock.
# Provisional boundary 0.35s on n=5 with a narrow 0.32/0.40 gap, so this DISCLOSES rather than blocks
# until more of my labels firm it up. Do not silently widen it; add labelled clips and re-derive.
COH_OUT=$(python3 "$SKILL/coherence_probe.py" "$PROBE_SRC" "$SRT" 2>&1) || true
echo "$COH_OUT"
COH_DEBT=$(echo "$COH_OUT" | grep -oE "debt [0-9.]+" | head -1 | awk '{print $2}')
# THE CROSSED GRAPH READING (2026-07-26): timing alone never separated my labels, because on iii
# the robotic-ness is movement being ABSENT, not mistimed, and an absence has no phase. graph_verdict
# crosses PRESENCE (hand gesture) against TIMING (debt per onset) and is the first model that explains
# every clip I have labelled - including why r3 and T2 measure almost identically and got opposite
# verdicts (same stillness, different register). Register is an INPUT: pass REGISTER=calm|excited.
if [ -f "$SKILL/graph_verdict.py" ]; then
  python3 "$SKILL/graph_verdict.py" "$PROBE_SRC" "$SRT" --register "${REGISTER:-unspecified}" 2>&1 | sed 's/^/  /'
fi
if [ -n "$COH_DEBT" ]; then
  echo "${COH_DEBT}" > "/tmp/.debt-$(basename "$F")"
  python3 -c "import sys; sys.exit(0 if float('$COH_DEBT') > 0.35 else 1)" &&     echo "  >>> DISCLOSE IN DELIVERY: graph debt ${COH_DEBT}s (my naturals 0.16-0.32s). This is the" &&     echo "  >>> ROBOTIC-movement axis, not the mouth: her motion drifts out of step with the speech."
fi
# SINGLE TAKE IS THE STANDING DEFAULT on avatar_iii (2026-07-26: "single take always pls on
# avaIII, unless i say so otherwise!!"). So spasm does NOT block: the only remedy for a high ratio is
# metering several takes, and that spend is now forbidden by default, which would make a blocking gate
# a thing the model overrides every single time - the exact rationalization this file exists to prevent.
# Instead the ratio is DISCLOSED, loudly, and written to a sidecar so the delivery can carry the
# number to my eye. I chose 1 credit per clip with informed eyes over 3 credits with a
# guaranteed settle; the gate's job is to make sure I is informed, not to relitigate my choice.
SPASM_R=$(echo "$SPASM_OUT" | grep -oE "ratio [0-9.]+|ratio inf" | head -1 | awk '{print $2}')
echo "${SPASM_R:-unmeasured}" > "/tmp/.spasm-$(basename "$F")"
if [ "$SPASM_RC" = "2" ]; then
  echo "  >>> DISCLOSE IN DELIVERY: mouth does not settle, spasm ${SPASM_R:-?} (fails under 0.30*fps of post-speech runway)."
  echo "  >>> Single take is the standing default, so this ships WITH the number stated to me."
  echo "  >>> Metering several takes (the best-take step) is the only fix, and needs my explicit go."
fi

# 3b. her<->TIME, MECHANICAL (2026-07-26, after the model attested a sunrise beach for a
# night-time script and I caught it: the excuse was written in the model's own
# attestation prose, which is exactly what the probe says to fail on). Scene light
# class must agree with the delivery clock, or the gate HOLDS for an explicit
# --time-ok <reason>. Prose can no longer talk past this.
if [ -z "${TIMEOK:-}" ]; then
  LUM=$(python3 - "$F" <<'PY'
import subprocess, sys
import numpy as np
p=sys.argv[1]
d=float(subprocess.run(["ffprobe","-v","error","-show_entries","format=duration","-of","csv=p=0",p],capture_output=True,text=True).stdout.strip() or 10)
vals=[]
for t in (d*0.15, d*0.5, d*0.85):
    raw=subprocess.run(["ffmpeg","-nostdin","-v","error","-ss",str(t),"-i",p,"-frames:v","1",
                        "-vf","scale=64:64,format=gray","-f","rawvideo","pipe:1"],capture_output=True).stdout
    if len(raw)>=4096: vals.append(np.frombuffer(raw[:4096],dtype=np.uint8).mean())
print(round(float(np.mean(vals)) if vals else -1, 1))
PY
)
  HOUR=$(date +%H)
  # Calibrated 2026-07-26 on labeled renders, not guessed: moonlit night ocean measures
  # 73-87 (the moon and foam are bright), while every dawn/day scene measured 121-175.
  # The gap is wide, so the boundary sits at 105; 'twilight' spans 105-135 where a dim
  # interior (bakery 121) could legitimately be either.
  SCENE=$(python3 -c "l=float('$LUM'); print('night' if l<105 else ('twilight' if l<135 else 'day'))")
  CLOCK=$(python3 -c "h=int('$HOUR'); print('night' if (h<5 or h>=21) else ('twilight' if h<7 or h>=19 else 'day'))")
  # THE TIME TRIANGLE (2026-07-26: "lightning to time to scene (triplewise?)"). Time is
  # asserted by THREE channels - the light in the frame, the words she speaks, the clock when it
  # lands - so it is a triangle, not a pair. Pairwise checking is exactly how the sunrise/midnight
  # failure slipped: two edges passed and the model narrated over the third. ALL THREE edges must agree;
  # 2-of-3 is a FAIL.
  WORDS=$(python3 - "$SRT" <<'PY'
import re, sys
t=open(sys.argv[1], errors="ignore").read().lower()
t=re.sub(r"\d\d:\d\d:\d\d,\d\d\d --> \d\d:\d\d:\d\d,\d\d\d|^\d+$", " ", t, flags=re.M)
t=re.sub(r"\s+"," ",t)
# Only PRESENT-MOMENT time claims count. "since last evening" is a past reference and
# "will be here in the morning" is a future one; neither asserts what time it is NOW.
# (Both false-fired the triangle on 2026-07-26 before tense was handled.)
TOK=[(r"midnight|late at night|middle of the night|this late","night"),
     (r"good ?morning|sunrise|dawn|this morning|the morning","day"),
     (r"afternoon|midday|noon","day"),
     (r"evening|sunset|dusk","twilight"),
     (r"tonight","night")]
PRESENT=re.compile(r"(it'?s|it is|right now|just past|just after|just gone|currently|we'?re here)[^.]{0,40}$")
ELSEWHEN=re.compile(r"(since|last|earlier|yesterday|tomorrow|will be|will still|by then|in a few|next)[^.]{0,25}$")
claims=set()
for pat,cls in TOK:
    for m in re.finditer(pat,t):
        pre=t[max(0,m.start()-45):m.start()]
        if ELSEWHEN.search(pre): continue
        if PRESENT.search(pre): claims.add(cls)
print(",".join(sorted(claims)) if claims else "none")
PY
)
  # EXPOSURE DRIFT (2026-07-26: "suddenly the scenery becomes brighter and then becomes
  # darker towards the back, and Avatar 4 doesn't have this issue"). The light must hold ITS OWN
  # value across the clip, not just match the clock at one sample: a pulsing scene asserts a
  # different moment at different times. Measured on the pair: iii swings ~15 luma with ~40%
  # spikes every ~20s, iv swings 2. Background only, so her motion does not count as drift.
  DRIFT=$(python3 - "$F" <<'PY'
import subprocess, sys
import numpy as np
p=sys.argv[1]
d=float(subprocess.run(["ffprobe","-v","error","-show_entries","format=duration","-of","csv=p=0",p],capture_output=True,text=True).stdout.strip() or 10)
vals=[]
n=max(6, min(24, int(d/5)))
for i in range(n):
    t=1.0+i*(d-2.0)/max(1,n-1)
    r=subprocess.run(["ffmpeg","-nostdin","-v","error","-ss",f"{t:.2f}","-i",p,"-frames:v","1",
                      "-vf","scale=48:48,format=gray","-f","rawvideo","pipe:1"],capture_output=True).stdout
    if len(r)>=2304:
        fr=np.frombuffer(r[:2304],dtype=np.uint8).reshape(48,48).astype(np.float32)
        vals.append(np.concatenate([fr[:, :16].ravel(), fr[:, 32:].ravel()]).mean())
print(round(float(max(vals)-min(vals)),1) if len(vals)>3 else -1)
PY
)
  echo "exposure drift: background luma swing $DRIFT (anchored <=4, drifting >=10)"
  python3 -c "import sys; d=float('$DRIFT'); sys.exit(0 if d>=10 else 1)" && \
    echo "  NOTE: scene light is unstable across the clip (engine drift). Not blocking, but this is\
 the tell that the render has no persistent global anchor, the same weakness that produces the\
 reverse splice at length."
  echo "time triangle: light=$SCENE (luma $LUM) | words=$WORDS | clock=$CLOCK (${HOUR}h)"
  FAILED=""
  [ "$SCENE" != "$CLOCK" ] && FAILED="light-vs-clock"
  case "$WORDS" in
    none) : ;;
    *,*) FAILED="$FAILED words-claim-two-different-times($WORDS)" ;;
    *) [ "$WORDS" != "$SCENE" ] && FAILED="$FAILED words-vs-light"
       [ "$WORDS" != "$CLOCK" ] && FAILED="$FAILED words-vs-clock" ;;
  esac
  if [ -n "$FAILED" ]; then
    echo "SHIP-GATE HOLD (time triangle): broken edge(s):$FAILED"
    echo "All three must name the same moment. Re-draw the look, re-word the script, or rerun with"
    echo "TIMEOK=\"<why all three cohere anyway>\" (logged, not silent)."
    rm -f "$MARK"; exit 5
  fi
fi

# 4. arrow. AUTO-DETECTED, never trusted to the operator's memory (that was the exact
# failure mode this gate exists for): measure background motion in the side bands
# (outside the centered subject); a moving background makes the scene directional
# whether or not anyone remembered to say so. The explicit "directional" arg only FORCES.
if [ -z "$DIRECTIONAL" ] && [ -z "$ARROWOK" ]; then
  BG=$(python3 - "$F" "$AW_T0" "$AW_T1" "${ARROW_WINDOW:+named}" <<'PY'
import subprocess, sys
import numpy as np
path, t0, t1 = sys.argv[1], float(sys.argv[2]), float(sys.argv[3])
named = sys.argv[4:] == ["named"]
def secs(x):
    return f"{x:.6f}".rstrip("0").rstrip(".") or "0"
def band(crop):
    # Each band builds its own command. The right band used to reuse the left band's list by
    # overwriting element 5, which is "-t", not the filter, so ffmpeg took the filter for an
    # output file name and refused, the right band came back empty, and max(left, nan)
    # returned the left. Only the left band had ever been measured.
    cmd = ["ffmpeg","-v","error","-ss",secs(t0),"-t",secs(t1 - t0),"-i",path,"-vf",
           crop + ",scale=64:128,format=gray","-f","rawvideo","pipe:1"]
    raw = subprocess.run(cmd, capture_output=True).stdout
    n = len(raw)//(64*128)
    if n < 10:
        return None
    fr = np.frombuffer(raw[:n*64*128],dtype=np.uint8).reshape(n,128,64).astype(np.float32)
    # A shot change is not background motion. An ad master cuts between its scenes inside the
    # window, and one cut frame changes by up to a hundred levels, enough on its own to read two
    # still scenes as directional. A frame that changes many times more than the typical frame
    # is a cut, and is left out.
    d = np.abs(np.diff(fr,axis=0)).mean(axis=(1,2))
    moving = d[d <= max(20.0, 8 * float(np.median(d)))]
    return float(moving.mean()) if moving.size else 0.0
left = band("crop=iw*0.15:ih*0.5:0:ih*0.2")
right = band("crop=iw*0.15:ih*0.5:iw*0.85:ih*0.2")
if left is None or right is None:
    # A clip shorter than the August window has always read as still, and still does. A
    # window the caller NAMED that holds under ten frames is a mistake about the clip.
    print("NOFRAMES" if named else "0.0")
else:
    print(round(max(left, right), 2))
PY
)
  case "$BG" in
    NOFRAMES)
      echo "SHIP-GATE HOLD: ARROW_WINDOW=$ARROW_WINDOW holds under ten frames of this clip, so the side"
      echo "bands were not measured. A window with nothing in it cannot clear a clip."
      rm -f "$MARK"; exit 64 ;;
    ''|*[!0-9.]*)
      echo "SHIP-GATE HOLD: the side-band measure returned no number (got '$BG'). Unmeasured is not"
      echo "still, so this fails closed."
      rm -f "$MARK"; exit 64 ;;
  esac
  echo "background side-band motion: $BG (directional threshold 0.6, $AW_T0 to $AW_T1 s)"
  python3 -c "import sys; sys.exit(0 if float('$BG') > 0.6 else 1)" && DIRECTIONAL="auto"
fi
# 4b. palindrome probe (2026-07-26). The probe detects the refill MECHANICALLY (8/8 on the
# eye-labelled set: periods 38-60s, turnarounds on half-period multiples). Whether the refill
# is VISIBLE is a fact about the scene the pixels would not give up: two metrics tried the same
# morning (side-band diff 0.23 on water I saw reverse; phase-correlation drift ~0 on every
# clip) both failed the labelled set. So visibility is DECLARED, never inferred: on REPLAYS the
# gate HOLDS and forces the call. REPLAYOK="<why the scene hides it>" passes a genuinely static
# scene (my approved lamp-lit interiors), logged like TIMEOK. It can never silently pass a
# replaying clip again (the scheduled-replay failure), and never auto-kills an approved static.
# (First wiring was removed by a blanket rebase I requested for other reasons; restored the
# same morning on the grounds that it should never have been dropped.)
MP="$SKILL/mirror_probe.py"
# The replay detector lives beside the other probes. A missing probe used to be skipped in
# silence, which let a replaying clip pass the gate. Now it fails closed like unreadable input.
if [ ! -f "$MP" ]
then
  echo "SHIP-GATE HOLD, mirror_probe.py not found at $MP. The replay check cannot run, failing closed."
  # The receipt goes first, as it does on every other failing path in this
  # file. Leaving it behind means a clip that passed yesterday still holds a
  # valid-looking receipt today, when the probe install is broken and nothing
  # has been checked. A HOLD that leaves an approval standing is not a hold.
  rm -f "$MARK"
  exit 64
fi
if [ -z "$ARROWOK" ]; then
  MPOUT=$(python3 "$MP" "${RAW:-$F}" 2>&1); MPRC=$?
  echo "$MPOUT" | head -2 | sed 's/^/  /'
  # THE EXIT CODE ALONE CANNOT BE TRUSTED. The probe uses 1 for "this clip
  # replays itself", and python also exits 1 on any uncaught exception, so a
  # probe that died on an import error or a bad frame is indistinguishable from
  # one that reached a verdict. With REPLAYOK set, that crash walked straight
  # into the override branch and the clip shipped with a receipt behind it and
  # no replay check at all. The probe prints a MIRROR verdict line on both of
  # its real outcomes and on neither of its failures, so the line is what makes
  # the exit code mean something.
  # The verdict line must be ANCHORED and must AGREE with the exit code. A bare
  # substring test is not enough: a SyntaxError in the probe makes python quote
  # the offending source line back at you, and the offending line here is the
  # one that prints the verdict, so the traceback contains the word MIRROR and
  # a loose match reads a crash as a decision. The traceback quotes the source
  # indented, and stderr is folded into this output, so only a line that STARTS
  # with the verdict counts. Pairing it with the exit code closes the other
  # half: a FORWARD verdict cannot arrive with a replay exit, or the other way.
  MPVERDICT="$(printf '%s\n' "$MPOUT" | grep -c '^MIRROR \(FORWARD\|REPLAYS\):')"
  if [ "$MPVERDICT" -lt 1 ] \
     || { [ "$MPRC" = "0" ] && ! printf '%s\n' "$MPOUT" | grep -q '^MIRROR FORWARD:'; } \
     || { [ "$MPRC" = "1" ] && ! printf '%s\n' "$MPOUT" | grep -q '^MIRROR REPLAYS:'; }
  then
    echo "SHIP-GATE HOLD, the replay probe gave no verdict matching its exit code ($MPRC)."
    echo "A real run prints MIRROR FORWARD: with 0 or MIRROR REPLAYS: with 1, at the"
    echo "start of a line. Anything else is a crash wearing a verdict's exit code,"
    echo "and python quotes the printing line back in a traceback, so a loose match"
    echo "on the word would read the crash as a decision."
    rm -f "$MARK"
    exit 64
  fi
  if [ "$MPRC" = "1" ]; then
    if [ -n "${REPLAYOK:-}" ]; then
      echo "  REPLAY OVERRIDE (logged): $REPLAYOK"
    else
      # Show the reader the turn, not only the verdict. This HOLD asks a person whether anything
      # in frame can reveal the replay, and it used to show them nothing. The scan is centred on
      # the vertex the probe names, five seconds either side, read from its verdict line or the
      # why line under it. With no vertex to read, or one outside the clip, it shows the whole
      # clip. It scans the footage the probe measured, so the vertex and the picture share one
      # timeline.
      RSRC="${RAW:-$F}"
      RDUR=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$RSRC")
      RW=$(PROBE_OUT="$MPOUT" python3 - "$RDUR" <<'PY'
import os, re, sys
lines = os.environ.get("PROBE_OUT", "").splitlines()
num = r"([0-9]+(?:\.[0-9]+)?)"
at = next((i for i, ln in enumerate(lines) if re.match(r"\w+ REPLAYS:", ln)), None)
vertex = None
if at is not None:
    near = lines[at:at + 4]
    for pat in (rf"\babout t={num}s\b", rf"\bat t={num}(?![0-9.])"):
        hit = next((m for m in (re.search(pat, ln) for ln in near) if m), None)
        if hit:
            vertex = hit.group(1)
            break
def secs(x):
    return f"{x:.6f}".rstrip("0").rstrip(".") or "0"
try:
    dur = float(sys.argv[1])
except ValueError:
    dur = 0.0   # unreadable footage, so the scan below fails closed
lo, hi = 0.0, dur
if vertex is not None:
    a, b = max(0.0, float(vertex) - 5.0), min(dur - 0.5, float(vertex) + 5.0)
    if b > a:
        lo, hi = a, b
print(vertex or "-", secs(lo), secs(hi))
PY
)
      read -r VERTEX RT0 RT1 <<<"$RW"
      if [ -n "$VERTEX" ] && [ "$VERTEX" != "-" ]; then
        echo "replay vertex: t=${VERTEX}s"
      else
        echo "the replay probe named no vertex, so the scan shows the whole clip"
      fi
      slit_scan "$RSRC" "${RT0:-0}" "${RT1:-0}" replay
      echo "SHIP-GATE HOLD: the scene replays itself (avatar_iii refill). If ANYTHING directional"
      echo "is in frame (water, drifting clouds, traffic) this is the backward-water defect: REJECT;"
      echo "go shorter, composite over a real plate, or avatar_iv with my explicit yes."
      echo "If the scene is time-SYMMETRIC (calm swell, flame flicker, static interior; my 2026-07-26 rule), rerun with"
      echo "REPLAYOK=\"<why nothing in frame can reveal it>\" (logged, not silent)."
      # The receipt goes with the rejection. This is the branch where it
      # matters most: the probe has just said the clip replays itself, and
      # leaving a valid-looking approval behind lets the next reader of /tmp
      # conclude it shipped clean. Every other failing path in this file drops
      # the receipt; this one could not, because until the probe path was fixed
      # this branch was unreachable and nobody had ever been here.
      rm -f "$MARK"
      exit 3
    fi
  fi
  [ "$MPRC" = "0" ] && ARROWOK=1
  # A probe that RAN but could not reach a verdict is the same silent skip as a
  # probe that was never found, wearing different clothes. This one returns 64
  # for footage it cannot read or that is too short to judge, and 3 when there
  # is not enough visual signal to decide. Neither was handled: both fell
  # through to the directional check, and with no directional argument the run
  # walked on to touch the receipt and print PASS. That is a shipping receipt
  # for a clip nothing examined.
  case "$MPRC" in
    0|1) ;;
    *)
      echo "SHIP-GATE HOLD, the replay probe ran but reached no verdict (exit $MPRC)."
      echo "64 means it could not read the footage or the clip is too short to judge;"
      echo "3 means there was not enough visual signal to decide. Unexamined is not"
      echo "clean, so this fails closed exactly like a missing probe."
      rm -f "$MARK"
      exit 64 ;;
  esac
fi
if [ -n "$DIRECTIONAL" ] && [ -z "$ARROWOK" ]; then
  DUR=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$F")
  if [ "$DIRECTIONAL" = "auto" ]; then
    # Scan the window the side-band measure above read and flagged: ARROW_WINDOW exactly when
    # it is set, and 8 to 16 s when it is not. It used to scan the last 11 s whatever raised the
    # flag, which on an ad master is the closer and the brand card, so the reader was shown a
    # window that had nothing to do with the motion that stopped the clip.
    if [ -n "${ARROW_WINDOW:-}" ]; then
      T0=$AW_T0; T1=$AW_T1
    else
      T0=8; T1=$(python3 -c "print(min(16.0, float('$DUR')-1))")
    fi
  else
    T0=$(python3 -c "print(max(0,float('$DUR')-11))"); T1=$(python3 -c "print(float('$DUR')-1)")
  fi
  slit_scan "$F" "$T0" "$T1" arrow
  rm -f "$MARK"   # a HOLD takes back any earlier pass receipt, like every other HOLD here
  echo "SHIP-GATE HOLD: directional scene - READ the slit-scan (one-way slope = pass;"
  echo "palindrome V = ping-pong REJECT), then rerun with --arrow-ok"
  exit 3
fi

touch "$MARK"
echo "SHIP-GATE PASS: $MARK"
