#!/usr/bin/env bash
# GATE: does the synthesised audio actually say the script? Run BEFORE spending a render.
#
# WHY THIS EXISTS (2026-07-26, the author: "i thought our voice/intent engine is supposed to catch this
# kinda nonsense"): there was no such engine. Step 2b of SKILL.md was the ONLY pre-render check in the
# whole pipeline with no executable behind it - prop_gate, ship_gate, settle_pad, subs_style and
# deliver all exit non-zero, 2b just asked nicely. So when ElevenLabs rendered eve's "notice what you
# WERE actually looking for" as "what you ARE", the STT read-back surfaced it, I decided it was the
# transcriber mishearing, and rendered anyway. HeyGen's caption (same audio) also said "are", so the
# flip was real and a clip shipped saying something I did not write. Detection was never the problem.
# Enforcement was. This file is the enforcement.
#
# Usage:
#   bash script_match.sh <stt.json|stt.txt> <script.json|script.txt>
#   bash script_match.sh <stt> <script> --accept "<why this difference is deliberate>"
#   bash script_match.sh --selftest
#
# Exit 0 = audio matches the script. Exit 2 = mismatch, DO NOT RENDER (re-synthesise, respelling the
# offending word phonetically). --accept records a deliberate override so accepting is an explicit act
# with a stated reason, never a silent judgement call.
set -euo pipefail

norm_py() {
cat <<'PY'
import json,re,sys
def load(p):
    raw=open(p,encoding="utf-8").read()
    if p.endswith(".json"):
        d=json.loads(raw)
        return d.get("text") or d.get("script") or raw
    return raw
UNITS={"zero":0,"one":1,"two":2,"three":3,"four":4,"five":5,"six":6,"seven":7,"eight":8,"nine":9,
"ten":10,"eleven":11,"twelve":12,"thirteen":13,"fourteen":14,"fifteen":15,"sixteen":16,
"seventeen":17,"eighteen":18,"nineteen":19,"twenty":20,"thirty":30,"forty":40,"fifty":50,
"sixty":60,"seventy":70,"eighty":80,"ninety":90}
SCALES={"hundred":100,"thousand":1000,"million":1000000}
def norm(t):
    t=t.replace("’","'").replace("‘","'").replace("“",'"').replace("”",'"')
    t=t.replace("—"," ").replace("–"," ")
    t=t.lower()
    # currency: $1,000 / $1000 -> 1000 dollars
    t=re.sub(r"\$\s*([\d,]+)", lambda m: m.group(1).replace(",","")+" dollars", t)
    # clock times: 3:00 -> 3 ; 03:30 -> 3 30  pii-allow, documents the normaliser
    t=re.sub(r"\b(\d{1,2}):(\d{2})\b", lambda m: str(int(m.group(1)))+("" if m.group(2)=="00" else " "+str(int(m.group(2)))), t)
    t=re.sub(r"(\d),(\d{3})", r"\1\2", t)
    t=re.sub(r"[^a-z0-9' ]"," ",t)
    w=t.split()
    # number words -> digits, composing "a thousand" / "one thousand" / "twenty five"
    out=[];i=0
    while i<len(w):
        tok=w[i]
        if tok in UNITS or (tok=="a" and i+1<len(w) and w[i+1] in SCALES):
            cur=0 if tok=="a" else UNITS[tok]
            if tok=="a": cur=1
            i+=1
            while i<len(w) and (w[i] in UNITS or w[i] in SCALES):
                if w[i] in SCALES: cur=(cur or 1)*SCALES[w[i]]
                else: cur+=UNITS[w[i]]
                i+=1
            out.append(str(cur)); continue
        out.append(tok); i+=1
    return out
a=norm(load(sys.argv[1])); b=norm(load(sys.argv[2]))
import difflib
if a==b:
    print("MATCH"); sys.exit(0)
print("MISMATCH")
for d in difflib.unified_diff(b,a,lineterm="",n=1):
    if d.startswith(("+","-")) and not d.startswith(("+++","---")): print("  "+d)
sys.exit(1)
PY
}

if [ "${1:-}" = "--selftest" ]; then
  T=$(mktemp -d)
  # Real cases from 2026-07-26. The first two are STT rendering conventions and MUST pass;
  # the third is the genuine tense flip that shipped and MUST fail.
  printf '%s' 'She asked for a thousand dollars at three in the morning.' > "$T/script1.txt"
  printf '%s' 'She asked for $1,000 at 3:00 in the morning.'            > "$T/stt1.txt"
  printf '%s' 'notice what you were actually looking for'               > "$T/script2.txt"
  printf '%s' 'notice what you are actually looking for'                > "$T/stt2.txt"
  ok=0
  python3 -c "$(norm_py)" "$T/stt1.txt" "$T/script1.txt" >/dev/null 2>&1 && { echo "PASS: currency+clock normalise (no false alarm)"; ok=$((ok+1)); } || echo "FAIL: false alarm on \$1,000 / 3:00"
  python3 -c "$(norm_py)" "$T/stt2.txt" "$T/script2.txt" >/dev/null 2>&1 && echo "FAIL: missed the were->are flip" || { echo "PASS: caught were->are"; ok=$((ok+1)); }
  rm -rf "$T"
  [ "$ok" = 2 ] && { echo "script_match selftest: all passed"; exit 0; } || { echo "script_match selftest: FAILED"; exit 1; }
fi

STT="${1:?usage: script_match.sh <stt.json|txt> <script.json|txt> [--accept \"reason\"]}"
SCRIPT="${2:?usage: script_match.sh <stt.json|txt> <script.json|txt> [--accept \"reason\"]}"
ACCEPT=""
[ "${3:-}" = "--accept" ] && ACCEPT="${4:?--accept requires a stated reason}"

set +e
OUT=$(python3 -c "$(norm_py)" "$STT" "$SCRIPT" 2>&1); RC=$?
set -e
echo "$OUT"

if [ "$RC" = 0 ]; then echo "SCRIPT-MATCH PASS"; exit 0; fi

if [ -n "$ACCEPT" ]; then
  echo "SCRIPT-MATCH ACCEPTED (deliberate): $ACCEPT"
  echo "$(date -u +%FT%TZ) | $SCRIPT | $ACCEPT" >> "$(dirname "$0")/.script-match-accepted.log"
  exit 0
fi

cat >&2 <<'MSG'
SCRIPT-MATCH FAIL: the synthesised audio does not say what the script says.
  DO NOT RENDER. Re-synthesise, respelling the offending word phonetically in the ElevenLabs input
  (spelling sent to TTS is tuning, not content - subtitles come from the SRT, so it never reaches the
  viewer). "It is probably just the transcriber mishearing" is the exact reasoning that shipped a
  wrong-tense clip on 2026-07-26; HeyGen's caption came from the same audio and confirmed the flip.
  If the difference IS deliberate, say so out loud to the author and re-run with:
      --accept "<why>"
MSG
exit 2
