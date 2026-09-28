#!/usr/bin/env bash
# voice_take.sh - draw N narrations, keep the one where she sounds like herself.
#
# WHY (the author, 2026-07-26): "sometimes it gets fucked the accent. 2nd time it's happening. not
# often, but happens." Measured that night: five draws of IDENTICAL text with IDENTICAL settings
# produced F1 537 / 616 / 727 / 573 / 558. One in five landed 27% off the consensus vowel space,  (F1 in Hz across five draws, pii-allow)
# which is what the ear reads as a changed accent. A single blind draw is therefore a coin flip on
# whether she sounds like herself, exactly as a single blind render was a coin flip on the spasm.
#
# THIS IS NOT A SPEND DECISION. the author's standing rule "single take always pls on avaIII" governs
# avatar_iii RENDER credits. TTS draws cost ZERO HeyGen credits, so there is no cost tradeoff to
# put to him here: shipping one blind audio draw is strictly worse than drawing three and keeping
# the best. Metering audio is free; metering renders is not. Do not conflate the two.
#
# Usage:
#   voice_take.sh <script.txt> <out.wav|out.mp3> [N]     (N defaults to 3)
#
# The OUT extension picks the format. .wav = LOSSLESS: ElevenLabs output_format=pcm_44100 (raw s16le,
# 44.1k mono, no container) wrapped into WAV by ffmpeg with no re-encode. .mp3 = the legacy lossy
# path, code unchanged. the author, 2026-08-30, judged by eye on the burgundy closer take: the mp3 ->
# libmp3lame -> mp3 chain is two lossy generations and synced worse than the PCM chain.
#
# Needs ELEVENLABS_API_KEY in env (never printed). Writes the winning draw to <out> and leaves
# the rejected draws beside it as <out>.draw-1.<ext> ... so a drifted take stays inspectable as a
# failure exemplar - INVARIANTS.md: failure exemplars are load-bearing.
#
# Exit 0 winner written / 1 draws disagreed, nothing written / 64 usage or missing key.
set -uo pipefail
SKILL="$(cd "$(dirname "$0")" && pwd)"
VID="${ELEVENLABS_VOICE_ID:?set ELEVENLABS_VOICE_ID to the pinned voice}"  # the pinned clone, never substitute
DEFAULT_N=3

SCRIPT="${1:-}"; OUT="${2:-}"; N="${3:-$DEFAULT_N}"
if [ -z "$SCRIPT" ] || [ -z "$OUT" ]; then
  echo "usage: voice_take.sh <script.txt> <out.wav|out.mp3> [N]"
  exit 64
fi
case "$OUT" in *.wav) FMT=wav;; *) FMT=mp3;; esac
[ -s "$SCRIPT" ] || { echo "voice_take: script not readable: $SCRIPT"; exit 64; }
[ -n "${ELEVENLABS_API_KEY:-}" ] || { echo "voice_take: ELEVENLABS_API_KEY not in env"; exit 64; }

CHARS=$(wc -c < "$SCRIPT" | tr -d ' ')
if [ "$CHARS" -lt 250 ]; then
  echo "voice_take NOTE: script is $CHARS chars. eleven_v3 reads short scripts brighter and less"
  echo "  consistently (measured 2026-07-26: <250-char scripts ran ~110 Hz brighter than every clip"
  echo "  the author accepted). Metering matters MORE here, not less."
fi

REQ="${OUT%.$FMT}.req.json"
python3 - "$SCRIPT" "$REQ" << 'PY'
import json, sys
text = open(sys.argv[1]).read().strip()
# CALM SETTINGS ARE THE DEFAULT (the author, 2026-09-01, "this is good" on the golden-park
# brief cast). stability 1.0 / style 0.0 replaced 0.6 / 0.3: avatar_iii mirrors the
# audio's energy (HeyGen docs, verified 2026-08-31 research pass), and the old settings'
# energy spikes drove the gesture twitch he kept flagging. Measured same night: calm
# settings also tightened take-length spread (9.1% -> 2.1-5.6% across three draws).
# Env override for a deliberately expressive clip: AJ_VOICE_STABILITY / AJ_VOICE_STYLE.
import os
_stab = float(os.environ.get("AJ_VOICE_STABILITY", "1.0"))
_style = float(os.environ.get("AJ_VOICE_STYLE", "0.0"))
json.dump({"text": text, "model_id": "eleven_v3",
           "voice_settings": {"stability": _stab, "similarity_boost": 0.92,
                              "style": _style, "use_speaker_boost": True}},
          open(sys.argv[2], "w"), ensure_ascii=False)
PY

DRAWS=""
for i in $(seq 1 "$N"); do
  D="${OUT%.$FMT}.draw-$i.$FMT"
  if [ "$FMT" = "wav" ]; then
    P="${D%.wav}.pcm"
    CODE=$(curl -s -w "%{http_code}" -X POST "https://api.elevenlabs.io/v1/text-to-speech/$VID?output_format=pcm_44100" \
      -H "xi-api-key: $ELEVENLABS_API_KEY" -H "Content-Type: application/json" \
      -d @"$REQ" -o "$P")
    SZ=$(wc -c < "$P" | tr -d ' ')
    if [ "$CODE" != "200" ] || [ "$SZ" -lt 2000 ]; then
      echo "voice_take: draw $i failed (HTTP $CODE, $SZ bytes)"
      continue
    fi
    # s16le is two bytes per sample: an odd count is a torn download, never audio. Refuse to wrap it.
    if [ $((SZ % 2)) -ne 0 ]; then
      echo "voice_take: draw $i failed (pcm byte count $SZ is odd, torn download)"
      continue
    fi
    ffmpeg -v error -y -f s16le -ar 44100 -ac 1 -i "$P" -c:a pcm_s16le "$D" \
      || { echo "voice_take: draw $i failed (wav wrap)"; continue; }
    rm -f "$P"
    SZ=$(wc -c < "$D" | tr -d ' ')
  else
    CODE=$(curl -s -w "%{http_code}" -X POST "https://api.elevenlabs.io/v1/text-to-speech/$VID" \
      -H "xi-api-key: $ELEVENLABS_API_KEY" -H "Content-Type: application/json" \
      -H "Accept: audio/mpeg" -d @"$REQ" -o "$D")
    SZ=$(wc -c < "$D" | tr -d ' ')
    if [ "$CODE" != "200" ] || [ "$SZ" -lt 2000 ]; then
      echo "voice_take: draw $i failed (HTTP $CODE, $SZ bytes)"
      continue
    fi
  fi
  echo "  draw $i: $SZ bytes"
  DRAWS="$DRAWS $D"
done

# shellcheck disable=SC2086
set -- $DRAWS
[ "$#" -ge 2 ] || { echo "voice_take: fewer than 2 usable draws, cannot form a consensus"; exit 64; }

OUTPUT=$(python3 "$SKILL/voice_probe.py" "$@")
RC=$?
echo "$OUTPUT"
WINNER=$(echo "$OUTPUT" | grep '^SURVIVOR: ' | tail -1 | sed 's/^SURVIVOR: //')

if [ "$RC" -ne 0 ]; then
  echo "voice_take: draws did not agree; nothing written to $OUT. Redraw, or let the author's ear pick."
  exit 1
fi
cp "$WINNER" "$OUT"
echo "voice_take: wrote $(basename "$WINNER") -> $OUT (a SURVIVOR of the outlier check, not a"
echo "  quality pick: ranking within survivors was falsified by the author's ear 2026-07-26)"
echo "  rejected draws kept beside it as failure exemplars; delete them once the author has labelled."
exit 0
