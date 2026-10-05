#!/usr/bin/env bash
# master.sh <built.mp4> <master.mp4>: the mastering pass every August batch driver ran after
# build-ad.sh, which mixes at unity and never normalises (its amix runs with normalize=0). The
# standard is the one build-ads3.sh through build-ads8.sh carry: loudnorm to -16 LUFS integrated,
# 48 kHz stereo AAC, the picture copied untouched. gates/loudness_gate.py reads the result back,
# because a single loudnorm pass can land off its target.
#
# The true-peak target is -2.0 dBTP, half a decibel under the gate's -1.5 ceiling. The August
# drivers aimed at -1.5, the ceiling itself, and the gate compares strictly on a reading rounded
# to a tenth: a limited mix re-encoded to AAC lands a hair under or over its target, reads -1.5,
# and fails, and every re-master lands in the same place, so the clip could never pass. A tone
# burst mastered at -1.5 measured exactly that on 2026-09-24, and the same signal at -2.0 read
# -2.0 and passed. The margin is headroom for the encoder, not a looser spec.
set -euo pipefail
IN=${1:?usage: master.sh <built.mp4> <master.mp4>}; OUT=${2:?usage: master.sh <built.mp4> <master.mp4>}
[ -s "$IN" ] || { echo "master.sh: no input at $IN"; exit 64; }
ffmpeg -v error -y -i "$IN" -c:v copy -af "loudnorm=I=-16:TP=-2:LRA=11" -ar 48000 -ac 2 -c:a aac -b:a 192k -movflags +faststart "$OUT"
