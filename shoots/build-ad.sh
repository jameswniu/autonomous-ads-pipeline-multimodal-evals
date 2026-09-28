#!/usr/bin/env bash
# build-ad.sh <ad> [avatar-slug]: three vignette scenes cut to the narration's sentence boundaries, the avatar closer, the brand card.
#   ad          one of orchard lantern harbor quiet slowroad
#   avatar-slug defaults to <ad>-av (harbor uses harbor-maya-av etc.)
set -euo pipefail
AD=$1; AV=${2:-$AD-av}; S=$SHOOT_ROOT; T=$S/takes/ads2; V=$T/out-$AD-${AV}; mkdir -p "$V"; F2=$S/takes/film2
FN='/System/Library/Fonts/Supplemental/Arial.ttf'
enc=(-c:v libx264 -crf 18 -preset medium -pix_fmt yuv420p -r 25)
case $AD in
  orchard)  BRAND="Orchard Hill Coffee"; TAG="Roasted the week it lands."; BED=$F2/bed3.mp3 ;;
  lantern)  BRAND="Lantern Street"; TAG="The page that opens the right screen."; BED=$F2/bed4.mp3 ;;
  harbor)   BRAND="Harbor Lane Realty"; TAG="One agent. One street."; BED=$F2/bed3.mp3 ;;
  quiet)    BRAND="Quiet Hours"; TAG="Sleep, not stats."; BED=$F2/bed2.mp3 ;;
  slowroad) BRAND="Slow Road Travel"; TAG="Go slower, see more."; BED=$F2/bed3.mp3 ;;
esac
# sentence boundaries from the narration read-back: three sentences, one scene each
read -r S1 E1 S2 E2 S3 E3 VOEND < <(python3 - "$T/$AD-vo/stt.json" "$T/$AD-vo/script.txt" <<'PY'
import json,re,sys
w=[x for x in json.load(open(sys.argv[1]))["words"] if x["type"]=="word"]
t=open(sys.argv[2]).read().strip()
sents=[x.strip() for x in re.split(r'(?<=[.?!])\s+', t) if x.strip()]
while len(sents)>3:
    i=min(range(len(sents)-1), key=lambda k: len(sents[k])+len(sents[k+1])); sents[i:i+2]=[sents[i]+" "+sents[i+1]]
counts=[len(x.split()) for x in sents]
# align by word count; if the read-back word total differs, scale the boundaries proportionally
total=sum(counts); n=len(w); bounds=[]; acc=0
for c in counts[:-1]:
    acc+=c; bounds.append(round(acc*n/total))
groups=[]; prev=0
for b in bounds+[n]:
    groups.append(w[prev:b]); prev=b
out=[]
for g in groups: out+=[f"{g[0]['start']:.2f}", f"{g[-1]['end']:.2f}"]
print(" ".join(out), f"{w[-1]['end']:.2f}")
PY
)
CAPS=$(python3 - "$T/$AD-vo/script.txt" <<'PY'
import re,sys
t=open(sys.argv[1]).read().strip()
sents=[x.strip() for x in re.split(r'(?<=[.?!])\s+', t) if x.strip()]
while len(sents)>3:
    i=min(range(len(sents)-1), key=lambda k: len(sents[k])+len(sents[k+1])); sents[i:i+2]=[sents[i]+" "+sents[i+1]]
print("\n".join(sents))
PY
)
C1=$(sed -n 1p <<<"$CAPS"); C2=$(sed -n 2p <<<"$CAPS"); C3=$(sed -n 3p <<<"$CAPS")
# scene windows: scene 1 from 0, each next scene starts 0.15 s before its sentence; scene 3 ends 0.35 s after the last word
T2=$(echo "$S2-0.15"|bc); T3=$(echo "$S3-0.15"|bc); TEND=$(echo "$VOEND+0.35"|bc)
D1=$T2; D2=$(echo "$T3-$T2"|bc); D3=$(echo "$TEND-$T3"|bc)
cap() { local capf; capf=$(python3 - "$1" "${CAPSZ:-46}" <<'PYW'
import sys, hashlib, tempfile, os
t, F = sys.argv[1], int(sys.argv[2])
# two lines maximum, stretched wide (the author, 2026-08-29): usable width is the
# 1080 frame minus ~70px margin each side; average Arial advance ~0.50*F, so
# chars per line = 2136/F. CAPSZ is precomputed per video so the longest
# caption fits two lines and the size stays consistent across the whole ad.
chars = max(8, int(2136 / F))
if len(t) > chars and " " in t:
    words = t.split(); best = None; cut = 1
    for i in range(1, len(words)):
        a, b = " ".join(words[:i]), " ".join(words[i:])
        m = max(len(a), len(b))
        if best is None or m < best: best, cut = m, i
    t = " ".join(words[:cut]) + "\n" + " ".join(words[cut:])
f = os.path.join(tempfile.gettempdir(), "adcap-" + hashlib.md5((t + str(F)).encode()).hexdigest()[:10] + ".txt")
open(f, "w").write(t); print(f)
PYW
); echo "drawtext=fontfile='$FN':textfile='$capf':fontsize=${CAPSZ:-46}:fontcolor=white:box=1:boxcolor=black@0.55:boxborderw=10:line_spacing=8:x=(w-text_w)/2:y=h-170-th$2"; }
vig() { local src=$1 t0=$2 dur=$3 out=$4 captext=$5 en=${6:-}
  local vf="trim=${t0}:$(echo "$t0+$dur"|bc),setpts=PTS-STARTPTS,crop=1080:1080:420:0"
  [ -n "$captext" ] && vf="$vf,$(cap "$captext" "$en")"
  ffmpeg -v error -y -i "$src" -filter_complex "[0:v]$vf,setsar=1[v]" -map "[v]" -an "${enc[@]}" "$out"; }
esc() { printf '%s' "$1"; }   # captions go through a textfile, which is literal; drawtext escaping here leaks backslashes on screen
# scene(): a narration line that outruns its footage gets proportional slow motion up to x1.6, then a held last frame;
# a scene that comes up short pulls the whole timeline ahead of the sound and the closer lip-syncs early (2026-08-26)
scene() { local src=$1 dur=$2 out=$3 captext=$4 en=$5 label=$6
  local avail; avail=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$src" | awk '{printf "%.2f", $1-0.45}')
  if [ "$(echo "$dur > $avail"|bc)" = 1 ]; then
    local rate; rate=$(echo "scale=4; $dur/$avail"|bc)
    if [ "$(echo "$rate > 1.6"|bc)" = 1 ]; then
      ffmpeg -v error -y -i "$src" -filter_complex "[0:v]trim=0.4:$(echo "0.4+$avail"|bc),setpts=(PTS-STARTPTS)*1.6,fps=25,tpad=stop_mode=clone:stop_duration=$dur,crop=1080:1080:420:0,$(cap "$captext" "$en"),trim=0:$dur,setsar=1[v]" -map "[v]" -an "${enc[@]}" "$out"
      echo "$label slowed x1.6 and held to cover $dur s"
    else
      ffmpeg -v error -y -i "$src" -filter_complex "[0:v]trim=0.4:$(echo "0.4+$avail"|bc),setpts=(PTS-STARTPTS)*$rate,fps=25,crop=1080:1080:420:0,$(cap "$captext" "$en"),trim=0:$dur,setsar=1[v]" -map "[v]" -an "${enc[@]}" "$out"
      echo "$label slowed x$rate to cover $dur s"
    fi
  else
    vig "$src" 0.4 "$dur" "$out" "$captext" "$en"
  fi; }
AVCAP=$(sed 's/ The pipeline behind this spot.*$//' "$T/$AV/script.txt")
PROMISE="The pipeline behind this spot is public, link under the video."
# per-video caption size: largest F <= 46 whose longest caption fits two lines
CAPSZ=$(python3 - "$C1" "$C2" "$C3" "$AVCAP" "$PROMISE" <<'PYF'
import sys
def minmax_two_line(t):
    if " " not in t:
        return len(t)
    words = t.split(); best = len(t)
    for i in range(1, len(words)):
        a, b = " ".join(words[:i]), " ".join(words[i:])
        best = min(best, max(len(a), len(b)))
    return best
need = max(minmax_two_line(a) for a in sys.argv[1:] if a) or 1
print(min(50, max(28, int(2136 / need))))
PYF
)
echo "caption size $CAPSZ (longest caption $(python3 -c "import sys; print(max(len(a) for a in sys.argv[1:] if a))" "$C1" "$C2" "$C3" "$AVCAP" "$PROMISE") chars)"
scene "$T/$AD-a/raw.mp4" "$D1" "$V/q1.mp4" "$(esc "$C1")" ":enable='gte(t,$S1)'" "scene a"
scene "$T/$AD-b/raw.mp4" "$D2" "$V/q2.mp4" "$(esc "$C2")" ":enable='gte(t,0.15)'" "scene b"
SC=${SCENE_C:-$T/$AD-c/raw.mp4}
scene "$SC" "$D3" "$V/q3.mp4" "$(esc "$C3")" ":enable='between(t,0.15,$(echo "$E3-$T3+0.10"|bc))'" "scene c"
# measured, frame-exact scene lengths: every audio anchor below derives from these, never from the plan
frames() { ffprobe -v error -select_streams v -count_frames -show_entries stream=nb_read_frames -of csv=p=0 "$1"; }
Q1=$(echo "scale=2; $(frames "$V/q1.mp4")/25"|bc); Q2=$(echo "scale=2; $(frames "$V/q2.mp4")/25"|bc); Q3=$(echo "scale=2; $(frames "$V/q3.mp4")/25"|bc)
T2=$Q1; T3=$(echo "$Q1+$Q2"|bc); TEND=$(echo "$Q1+$Q2+$Q3"|bc)
echo "measured scenes $Q1/$Q2/$Q3, closer video starts at $TEND s"
# avatar closer: the 1:1 render, trimmed to its own speech plus a short settle, TWO captions timed from its read-back
# so the on-screen text follows the voice into the standing promise instead of freezing on the brand line
AVV=$T/$AV/render.mp4; AVD=$(jq -r '[.words[]|select(.type=="word")][-1].end' "$T/$AV/stt.json" | awk '{printf "%.2f", $1+0.35}')
# TAKE-COHERENCE TRIPWIRE. Everything below trusts stt.json to describe the render's OWN speech:
# AVD trims video AND audio, PSTART/AVEND place the caption swap. On 2026-08-29 the -av dir held a
# re-drawn upload/stt while render.mp4 stayed the original take; the build clipped her final word and
# timed every closer caption off the wrong read. An avatar render lasts within ~0.15s of the audio
# that drove it, so a bigger gap between render and upload.mp3 means the files are two different
# takes. Heuristic pairing check, not proof; AV_TAKE_MISMATCH_OK=1 overrides for a deliberate case.
if [ "${AV_TAKE_MISMATCH_OK:-0}" != "1" ]; then
  RDUR=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$AVV")
  UDUR=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$T/$AV/upload.mp3" 2>/dev/null || echo "$RDUR")
  python3 -c "import sys; d=abs(float('$RDUR')-float('$UDUR')); g=float('$RDUR')-float('$AVD'); sys.exit(1 if d>0.15 or g>0.9 or g<-0.05 else 0)" || {
    echo "TAKE MISMATCH in $AV: render ${RDUR}s vs upload ${UDUR}s (AVD $AVD). stt.json/upload.mp3 do not describe render.mp4; the -av dir must be ONE coherent take."; exit 5; }
fi
read -r PSTART AVEND < <(python3 - "$T/$AV/stt.json" <<'PYT'
import json, sys
w = [x for x in json.load(open(sys.argv[1]))["words"] if x["type"] == "word"]
ps = None
for i, x in enumerate(w):
    if x["text"].strip().lower().startswith("pipeline") and i > 0:
        ps = w[i-1]["start"]; break
print(f"{ps if ps is not None else w[-1]['end']:.2f} {w[-1]['end']:.2f}")
PYT
)
CAPF1=$(cap "$(esc "$AVCAP")" ":enable='between(t,0.1,$(echo "$PSTART-0.05"|bc))'")
CAPF2=$(cap "$(esc "$PROMISE")" ":enable='between(t,$PSTART,$(echo "$AVEND+0.2"|bc))'")
# measured mouth-lag compensation (2026-08-26, sign fixed the same night after the gate caught the first
# version doubling the error): probe lag POSITIVE means her mouth LEADS the audio, so the video start gets
# padded by that much; NEGATIVE means the mouth TRAILS, so the first |lag| seconds of video are trimmed.
# Applied only past 100 ms. Probe failure means no compensation, logged, never a block.
MLAG=$( ( ${FACEPY:-python3} "$GATES/mouth_sync_probe.py" "$AVV" --json 2>/dev/null || true ) | tail -1 | python3 -c "import sys,json; print(json.load(sys.stdin)['lag_s'])" 2>/dev/null || echo 0)
COMP=$(python3 -c "l=float('$MLAG' or 0)+float('${CLOSER_NUDGE:-0}'); print(round(l,2) if abs(l) >= 0.02 else 0)")   # CLOSER_NUDGE adds a manual offset when the two sync probes disagree
# CLOSER_AUTOALIGN=0 disables the probe compensation entirely. HeyGen avatar renders generate the
# mouth FROM the audio, aligned by construction; on the 2026-08-29 ads8 night the probe misread
# every lively face by 0.2-0.24s and this block TRIMMED that much off aligned video, shipping the
# desync it claimed to fix (frame-vs-onset audit on the delivered master proved the mouth ran
# exactly the trim early). CLOSER_NUDGE still applies when set explicitly.
[ "${CLOSER_AUTOALIGN:-1}" = "0" ] && COMP=$(python3 -c "l=float('${CLOSER_NUDGE:-0}'); print(round(l,2) if abs(l) >= 0.02 else 0)")
if [ "$COMP" != "0" ] && [ "$(echo "$COMP > 0"|bc)" = 1 ]; then
  echo "closer mouth leads audio by ${COMP}s, padding video start to align"
  ffmpeg -v error -y -i "$AVV" -filter_complex "[0:v]tpad=start_mode=clone:start_duration=$COMP,trim=0:$AVD,setpts=PTS-STARTPTS,scale=1080:1080:force_original_aspect_ratio=increase,crop=1080:1080,$CAPF1,$CAPF2,setsar=1[v]" -map "[v]" -an "${enc[@]}" "$V/q4.mp4"
elif [ "$COMP" != "0" ]; then
  TR=$(printf "%.2f" "$(echo "0 - $COMP"|bc)")   # bc emits .16 with no leading zero and ffmpeg's trim refuses it
  echo "closer mouth trails audio by ${TR}s, trimming video start to align"
  ffmpeg -v error -y -i "$AVV" -filter_complex "[0:v]trim=$TR:$(echo "$AVD+$TR"|bc),setpts=PTS-STARTPTS,scale=1080:1080:force_original_aspect_ratio=increase,crop=1080:1080,$CAPF1,$CAPF2,setsar=1[v]" -map "[v]" -an "${enc[@]}" "$V/q4.mp4"
else
  ffmpeg -v error -y -i "$AVV" -filter_complex "[0:v]trim=0:$AVD,setpts=PTS-STARTPTS,scale=1080:1080:force_original_aspect_ratio=increase,crop=1080:1080,$CAPF1,$CAPF2,setsar=1[v]" -map "[v]" -an "${enc[@]}" "$V/q4.mp4"
fi

# brand card
python3 - "$V" "$BRAND" "$TAG" <<'PY'
from PIL import Image, ImageDraw, ImageFont; import sys
V,brand,tag=sys.argv[1:4]; path="/System/Library/Fonts/Supplemental/Baskerville.ttc"
def line_png(text,size,tracking,fill,out):
    f=ImageFont.truetype(path,size,index=0); widths=[f.getlength(ch) for ch in text]; total=int(sum(widths)+tracking*(len(text)-1))+4
    bbox=f.getbbox("Hgyj|"); h=bbox[3]-bbox[1]+8; im=Image.new("RGBA",(total,h),(0,0,0,0)); d=ImageDraw.Draw(im); x=2; y=-bbox[1]+4
    for ch,w in zip(text,widths): d.text((x,y),ch,font=f,fill=fill); x+=w+tracking
    im.save(out)
line_png(brand,104,2.5,(255,255,255,255),f"{V}/c1.png"); line_png(tag,62,3.5,(240,240,240,255),f"{V}/c2.png")
PY
ffmpeg -v error -y -f lavfi -i "color=c=black:s=1080x1080:d=3.0:r=25" -i "$V/c1.png" -i "$V/c2.png" -filter_complex "[0:v][1:v]overlay=x=(W-w)/2:y=(H-h)/2-64:enable='gte(t,0.1)'[a];[a][2:v]overlay=x=(W-w)/2:y=(H-h)/2+58:enable='gte(t,0.7)',fade=t=out:st=2.6:d=0.4,format=yuv420p,setsar=1[v]" -map "[v]" "${enc[@]}" "$V/q5.mp4"
: > "$V/concat.txt"; for q in q1 q2 q3 q4 q5; do printf "file '%s/%s.mp4'\n" "$V" "$q" >> "$V/concat.txt"; done
ffmpeg -v error -y -f concat -safe 0 -i "$V/concat.txt" -c:v libx264 -crf 18 -preset slow -pix_fmt yuv420p "$V/video.mp4"
AVMS=$(echo "$TEND*1000/1"|bc); CARDMS=$(echo "($TEND+$AVD)*1000/1"|bc); DUR=$(echo "$TEND+$AVD+3.0"|bc)
T2MS=$(echo "$T2*1000/1"|bc); T3MS=$(echo "$T3*1000/1"|bc)
ffmpeg -v error -y -i "$T/$AD-vo/narration.mp3" -i "$T/$AD-a/raw.mp4" -i "$T/$AD-b/raw.mp4" -i "${SCENE_C:-$T/$AD-c/raw.mp4}" -i "$AVV" -i "$BED" -i "$F2/hit2.mp3" -i "$F2/hit.mp3" -filter_complex "
[0:a]apad=whole_dur=$DUR[vo];
[1:a]atrim=0.4:$(echo "0.4+$D1"|bc),asetpts=PTS-STARTPTS,volume=0.14[m1];
[2:a]atrim=0.4:$(echo "0.4+$D2"|bc),asetpts=PTS-STARTPTS,volume=0.14,adelay=$T2MS|$T2MS[m2];
[3:a]atrim=0.4:$(echo "0.4+$D3"|bc),asetpts=PTS-STARTPTS,apad=whole_dur=$D3,volume=0.14,adelay=$T3MS|$T3MS[m3];
[4:a]atrim=0:$AVD,asetpts=PTS-STARTPTS,volume=1.0,adelay=$AVMS|$AVMS[av];
[5:a]atrim=0:$DUR,asetpts=PTS-STARTPTS,volume='if(lt(t,$TEND),0.20,if(lt(t,$(echo "$TEND+$AVD"|bc)),0.10,0.22))':eval=frame,afade=t=in:st=0:d=0.2,afade=t=out:st=$(echo "$DUR-0.8"|bc):d=0.8[bed];
[6:a]adelay=$T2MS|$T2MS,volume=0.4[k1];[6:a]adelay=$T3MS|$T3MS,volume=0.4[k2];
[7:a]adelay=$CARDMS|$CARDMS,volume=0.7[h1];
[vo][m1][m2][m3][av][bed][k1][k2][h1]amix=inputs=9:duration=first:normalize=0[a]" -map "[a]" -c:a aac -b:a 160k "$V/audio.m4a"
ffmpeg -v error -y -i "$V/video.mp4" -i "$V/audio.m4a" -map 0:v -map 1:a -c copy -shortest -movflags +faststart "$V/ad.mp4"
# caption sidecar for the gates: narration sentences then the avatar line
python3 - "$T/$AD-vo/stt.json" "$T/$AV/stt.json" "$TEND" "$V/clean.srt" <<'PY'
import json,sys
def sents(p):
    w=[x for x in json.load(open(p))["words"] if x["type"]=="word"]; out=[]; cur=[]
    for x in w:
        cur.append(x)
        if x["text"].rstrip().endswith((".","?","!")): out.append(cur); cur=[]
    if cur: out.append(cur)
    return out
def ts(t): return "%02d:%02d:%06.3f"%(t//3600,t%3600//60,t%60)
off=float(sys.argv[3]); cues=[(s[0]["start"],s[-1]["end"]," ".join(x["text"] for x in s)) for s in sents(sys.argv[1])]
cues+=[(s[0]["start"]+off,s[-1]["end"]+off," ".join(x["text"] for x in s)) for s in sents(sys.argv[2])]
with open(sys.argv[4],"w") as f:
    for i,(a,b,t) in enumerate(cues,1): f.write(f"{i}\n{ts(a).replace('.',',')} --> {ts(b).replace('.',',')}\n{t}\n\n")
PY
python3 - "$V/captions.json" "$S1" "$E1" "$S2" "$E2" "$S3" "$E3" "$T2" "$T3" "$TEND" "$AVD" "$PSTART" "$AVEND" "$C1" "$C2" "$C3" "$AVCAP" "$PROMISE" "$T/$AD-vo/stt.json" "$T/$AV/stt.json" <<'PYM'
import json, sys
a = sys.argv
S1,E1,S2,E2,S3,E3,T2,T3,TEND,AVD,PSTART,AVEND = map(float, a[2:14])
C1,C2,C3,AVCAP,PROMISE,VOSTT,AVSTT = a[14:21]  # pii-allow, a python slice
cues = [
 {"text": C1, "start": S1, "end": T2, "spoken_start": S1, "spoken_end": E1},
 {"text": C2, "start": round(T2+0.15,2), "end": T3, "spoken_start": S2, "spoken_end": E2},
 {"text": C3, "start": round(T3+0.15,2), "end": round(min(TEND, T3+E3-S3+0.25),2), "spoken_start": S3, "spoken_end": E3},
 {"text": AVCAP, "start": round(TEND+0.1,2), "end": round(TEND+PSTART-0.05,2), "spoken_start": round(TEND,2), "spoken_end": round(TEND+PSTART,2)},
 {"text": PROMISE, "start": round(TEND+PSTART,2), "end": round(TEND+AVEND+0.2,2), "spoken_start": round(TEND+PSTART,2), "spoken_end": round(TEND+AVEND,2)},
]
json.dump({"cues": cues, "closer_start": TEND, "closer_dur": AVD, "audio_closer_ms": int(TEND*1000), "vo_stt": VOSTT, "av_stt": AVSTT}, open(a[1], "w"), indent=1)
PYM
echo "built $V/ad.mp4 $(ffprobe -v error -show_entries format=duration -of csv=p=0 "$V/ad.mp4") s (scenes $D1/$D2/$D3, avatar $AVD)"
