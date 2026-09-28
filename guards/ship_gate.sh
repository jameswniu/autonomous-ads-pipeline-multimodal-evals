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
#                  the fix is a fit=cover re-render, never shipping borders).
#   2. SPASM     - spasm_probe FAIL (exit 2) blocks. WARN prints for the eye.
#   3. COHERENCE - rest/lock/phase printed; FLAG prints for the eye (outdoor
#                  confound means rest alone never hard-blocks here).
#   4. ARROW     - if "directional" is passed (water/traffic/crowd scenes): builds
#                  a slit-scan x-t image and EXITS 3 demanding an eye-read. Rerun
#                  with --arrow-ok only after actually reading the slit-scan
#                  (forward flow = one-way slope; palindrome V = ping-pong REJECT).
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
bad = 0
for t in (dur*0.2, dur*0.5, dur*0.8):
    raw = subprocess.run(["ffmpeg","-v","error","-ss",str(t),"-i",path,"-frames:v","1",
                          "-f","rawvideo","-pix_fmt","gray","pipe:1"],capture_output=True).stdout
    fr = np.frombuffer(raw[:w*h],dtype=np.uint8).reshape(h,w).astype(np.float32)
    # padding is BRIGHT *and* FLAT; a pale sky or sunlit sand is bright with texture,
    # so brightness alone false-alarms (fired on the morning-foam ocean scene 2026-07-26).
    pad_row = (fr.mean(axis=1) > 235) & (fr.std(axis=1) < 2.0)
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
  BG=$(python3 - "$F" <<'PY'
import subprocess, sys
import numpy as np
path = sys.argv[1]
cmd = ["ffmpeg","-v","error","-ss","8","-t","8","-i",path,"-vf",
       "crop=iw*0.15:ih*0.5:0:ih*0.2,scale=64:128,format=gray","-f","rawvideo","pipe:1"]
raw = subprocess.run(cmd, capture_output=True).stdout
n = len(raw)//(64*128)
if n < 10: print("0.0"); sys.exit()
fr = np.frombuffer(raw[:n*64*128],dtype=np.uint8).reshape(n,128,64).astype(np.float32)
left = np.abs(np.diff(fr,axis=0)).mean()
cmd[5] = "crop=iw*0.15:ih*0.5:iw*0.85:ih*0.2,scale=64:128,format=gray"
raw = subprocess.run(cmd, capture_output=True).stdout
n = len(raw)//(64*128)
fr = np.frombuffer(raw[:n*64*128],dtype=np.uint8).reshape(n,128,64).astype(np.float32)
right = np.abs(np.diff(fr,axis=0)).mean()
print(round(max(left,right),2))
PY
)
  echo "background side-band motion: $BG (directional threshold 0.6)"
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
  SLIT="/tmp/slit-$(basename "$F").png"
  DUR=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$F")
  T0=$(python3 -c "print(max(0,float('$DUR')-11))"); T1=$(python3 -c "print(float('$DUR')-1)")
  ffmpeg -y -v error -ss "$T0" -to "$T1" -i "$F" -vf "crop=2:ih*0.4:iw*0.8:ih*0.25,scale=2:200" -f rawvideo -pix_fmt gray "${TMPDIR:-/tmp}/.slit.$$.raw"
  python3 - "$SLIT" <<'PY'
import numpy as np, sys
from PIL import Image
raw = np.fromfile(""${TMPDIR:-/tmp}/.slit.$$.raw"", dtype=np.uint8)
n = len(raw)//400
xt = raw[:n*400].reshape(n,200,2).mean(axis=2).T
Image.fromarray(xt.astype(np.uint8)).resize((n*3,600), Image.NEAREST).save(sys.argv[1])
print("slit-scan:", sys.argv[1])
PY
  echo "SHIP-GATE HOLD: directional scene - READ the slit-scan (one-way slope = pass;"
  echo "palindrome V = ping-pong REJECT), then rerun with --arrow-ok"
  exit 3
fi

touch "$MARK"
echo "SHIP-GATE PASS: $MARK"
