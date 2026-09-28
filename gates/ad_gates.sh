#!/usr/bin/env bash
# ad_gates.sh <master.mp4> <captions.json>: the two gates an ad master must clear before deliver.sh will take it.
#   caption gate  every burned caption says what is spoken, when it is spoken (caption_gate.py)
#   closer gate   the closer window cut out of the MASTER, not the raw render: its video must start where its
#                 audio was placed (frame-exact, 40 ms), sync_probe must not read late, lipsync_probe must not FAIL
#                 (REVIEW is the talking-photo baseline and passes with a logged line; the eye still decides)
# Writes /tmp/.ad-gates-<basename>-<size> on pass. the author, 2026-08-26: "are the lip-syncs correct? add evals and
# gates for the subtitles and the lip-sync"; the whole-master sync read had hidden a 2.8 s closer offset.
set -uo pipefail
M=$1; CJ=$2; P="$(cd "$(dirname "$0")/../probes" && pwd)"; SK="$(cd "$(dirname "$0")" && pwd)"
[ -f "$M" ] && [ -f "$CJ" ] || { echo "ad_gates: missing master or captions.json"; exit 64; }
fail=0
echo "== caption gate"
python3 "$SK/caption_gate.py" "$CJ" || fail=1
CS=$(python3 -c "import json,sys; print(json.load(open(sys.argv[1]))['closer_start'])" "$CJ")
CD=$(python3 -c "import json,sys; print(json.load(open(sys.argv[1]))['closer_dur'])" "$CJ")
AMS=$(python3 -c "import json,sys; print(json.load(open(sys.argv[1]))['audio_closer_ms'])" "$CJ")
V=$(dirname "$CJ")
echo "== closer assembly"
Q=$(python3 - "$V" <<'PY'
import subprocess, sys
v = sys.argv[1]; tot = 0
for q in ("q1","q2","q3"):
    n = subprocess.run(["ffprobe","-v","error","-select_streams","v","-count_frames","-show_entries","stream=nb_read_frames","-of","csv=p=0",f"{v}/{q}.mp4"],capture_output=True,text=True).stdout.strip()
    tot += int(n)
print(int(tot/25*1000))
PY
)
D=$(( Q - AMS )); [ $D -lt 0 ] && D=$(( -D ))
if [ "$D" -le 40 ]; then echo "  closer video at ${Q} ms, audio placed at ${AMS} ms, drift ${D} ms: ok"; else echo "  closer video at ${Q} ms, audio placed at ${AMS} ms, drift ${D} ms: FAIL"; fail=1; fi
echo "== closer window probes"
W=/tmp/ad-gate-closer-$(basename "$M")
ffmpeg -v error -y -ss "$CS" -t "$CD" -i "$M" -c:v libx264 -crf 18 -c:a aac "$W" || { echo "  could not cut closer window"; exit 1; }
# sync_probe: LATE fails (> +80 ms); early is forgiven, every HeyGen render reads about -240 on this probe,
# approved ones included, so an early read is disclosed, not blocked
# sync_probe is a DISCLOSURE, not a gate (calibrated 2026-08-27 and demoted on the evidence): against
# controls with the audio shifted a known +/-0.4 s on a closer render, sync_probe moved only 80 ms, in the
# wrong direction for its own convention, and its +/-240 ms search window cannot represent a 400 ms shift
# at all. mouth_sync_probe moved 560 ms in the correct order on the same controls, so it is the gate here.
# sync_probe stays printed because it is still meaningful on HER reference framing, where it was tuned.
LAG=$(python3 "$P/sync_probe.py" "$W" --json 2>/dev/null | python3 -c "import sys,json; print(json.load(sys.stdin)['lag_ms'])" 2>/dev/null || echo "")
if [ -z "$LAG" ]; then echo "  sync lag unreadable (disclosure only)"
elif [ "$LAG" -gt 80 ]; then echo "  sync lag ${LAG} ms, reads late (disclosure only, probe does not track shifts on this framing)"
else echo "  sync lag ${LAG} ms (disclosure only): ok"; fi
# mouth_sync_probe: face-located lip openness against the audio envelope, calibrated on shifted controls 2026-08-26
FACEPY=${FACEPY:-python3}
MS=$("$FACEPY" "$SK/mouth_sync_probe.py" "$W" 2>/dev/null | tail -1); rm=$?
echo "  $MS"
case "$rm" in 0) ;; 2) echo "  mouth sync REVIEW, eye decides (logged)";; *) echo "  mouth sync FAIL"; fail=1;; esac
if [ "$fail" -eq 0 ]; then
  SZ=$(stat -f %z "$M"); touch "/tmp/.ad-gates-$(basename "$M")-$SZ"; echo "AD GATES PASS $(basename "$M")"
else
  echo "AD GATES FAIL $(basename "$M")"
fi
exit $fail
