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


# The normaliser now lives beside this script as textnorm.py, shared with caption_gate.py, and is
# checked before anything is compared. It used to be a heredoc piped into python3 -c, so a failure
# producing it handed python an empty program, which exits 0, and the gate printed PASS on a
# comparison that never ran (2026-09-21).
NORM="$(cd "$(dirname "$0")" && pwd)/textnorm.py"
[ -f "$NORM" ] || { echo "SCRIPT-MATCH ERROR: normaliser missing at $NORM, nothing was compared" >&2; exit 3; }

if [ "${1:-}" = "--selftest" ]; then
  T=$(mktemp -d)
  # Real cases from 2026-07-26. The first two are STT rendering conventions and MUST pass;
  # the third is the genuine tense flip that shipped and MUST fail.
  printf '%s' 'She asked for a thousand dollars at three in the morning.' > "$T/script1.txt"
  printf '%s' 'She asked for $1,000 at 3:00 in the morning.'            > "$T/stt1.txt"
  printf '%s' 'notice what you were actually looking for'               > "$T/script2.txt"
  printf '%s' 'notice what you are actually looking for'                > "$T/stt2.txt"
  # From 2026-09-25: a brand read back as one word is the same word and MUST pass, and two
  # numbers read back as one number are not the same and MUST fail.
  printf '%s' 'Z.ai puts frontier open models in your hands.'           > "$T/script3.txt"
  printf '%s' 'ZAI puts frontier open models in your hands.'            > "$T/stt3.txt"
  printf '%s' 'press one two'                                           > "$T/script4.txt"
  printf '%s' 'press 12'                                                > "$T/stt4.txt"
  ok=0
  python3 "$NORM" "$T/stt1.txt" "$T/script1.txt" >/dev/null 2>&1 && { echo "PASS: currency+clock normalise (no false alarm)"; ok=$((ok+1)); } || echo "FAIL: false alarm on \$1,000 / 3:00"
  python3 "$NORM" "$T/stt2.txt" "$T/script2.txt" >/dev/null 2>&1 && echo "FAIL: missed the were->are flip" || { echo "PASS: caught were->are"; ok=$((ok+1)); }
  python3 "$NORM" "$T/stt3.txt" "$T/script3.txt" >/dev/null 2>&1 && { echo "PASS: Z.ai read back as ZAI (no false alarm)"; ok=$((ok+1)); } || echo "FAIL: false alarm on Z.ai / ZAI"
  python3 "$NORM" "$T/stt4.txt" "$T/script4.txt" >/dev/null 2>&1 && echo "FAIL: missed one two read back as 12" || { echo "PASS: caught one two / 12"; ok=$((ok+1)); }
  rm -rf "$T"
  [ "$ok" = 4 ] && { echo "script_match selftest: all passed"; exit 0; } || { echo "script_match selftest: FAILED"; exit 1; }
fi

STT="${1:?usage: script_match.sh <stt.json|txt> <script.json|txt> [--accept \"reason\"]}"
SCRIPT="${2:?usage: script_match.sh <stt.json|txt> <script.json|txt> [--accept \"reason\"]}"
ACCEPT=""
[ "${3:-}" = "--accept" ] && ACCEPT="${4:?--accept requires a stated reason}"

set +e
OUT=$(python3 "$NORM" "$STT" "$SCRIPT" 2>&1); RC=$?
set -e
echo "$OUT"

if [ "$RC" = 0 ]; then echo "SCRIPT-MATCH PASS"; exit 0; fi
# Only a genuine mismatch, exit 1, may be accepted. An error means no comparison happened.
if [ "$RC" != 1 ]; then echo "SCRIPT-MATCH ERROR: the comparison did not run (exit $RC), refusing to pass or accept" >&2; exit 3; fi

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
