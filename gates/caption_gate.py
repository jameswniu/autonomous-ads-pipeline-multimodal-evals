#!/usr/bin/env python3
"""caption_gate.py <captions.json>: every burned caption must say what is being spoken, when it is spoken.

Reads the manifest the ad builder writes beside its srt. For each cue it checks three things against the
STT read-back of the audio actually in the cut: the cue text matches the words spoken in its window
(letters only, so a.m./am and harbor/harbour do not fail it), the cue appears no later than 0.3 s after
the first spoken word and no earlier than 0.5 s before it, and it stays up until the last spoken word.
Exit 0 pass, 1 fail. The author, 2026-08-26, after the delivered cuts lip-synced early and the captions drifted with
them; the gate that shipped them measured the whole master and never looked at a cue.
"""
import json, os, re, sys
from difflib import SequenceMatcher

# Digits are part of what a caption claims. Stripping them compared "Only $199" against spoken
# "$999" as the same string, so a wrong price, quantity or date passed (2026-09-21). Number words
# are folded to digits first, through the same normaliser script_match.sh uses, so a caption
# reading "$199" still matches a transcript that spells out one hundred ninety nine.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from textnorm import norm  # noqa: E402


def letters(t): return re.sub(r"[^a-z]", "", " ".join(norm(t)))
def numbers(t): return [x for x in norm(t) if x.isdigit()]
def words(stt):
    return [w for w in json.load(open(stt))["words"] if w["type"] == "word"]

def main():
    m = json.load(open(sys.argv[1]))
    vo, av = words(m["vo_stt"]), words(m["av_stt"])
    off = m["closer_start"]
    # A manifest with no cues used to print PASS (0 cues). An upstream omission or a schema
    # change then read as a clean inspection of captions nobody looked at.
    if not m["cues"]:
        print("CAPTION GATE FAIL (0 cues: nothing to inspect)")
        return 1
    fails = []
    for i, c in enumerate(m["cues"], 1):
        # The first three cues are the voice-over, the rest are the closer's own audio, which
        # starts at closer_start in master time. Shift once here so every comparison below is in
        # master time and the manifest's own numbers are never the timebase.
        shift = 0.0 if i <= 3 else off
        track = vo if i <= 3 else av
        at = [(w, w["start"] + shift, w["end"] + shift) for w in track]
        spoken = [w for w, a, b in at if a >= c["spoken_start"] - 0.05 and b <= c["spoken_end"] + 0.05]
        # A word the caption stands over but the manifest's window leaves out is a stale or wrong
        # manifest, and trusting that window is how a caption could pass against speech it never
        # covered. The check is against the cue's own on-screen interval (2026-09-21).
        under = [w for w, a, b in at if b > c["start"] and a < c["end"]]
        missed = [w["text"] for w in under if w not in spoken]
        if missed:
            print(f"  cue {i} [{c['start']:.2f}-{c['end']:.2f}] FAIL the declared window leaves out "
                  f"{len(missed)} word(s) spoken under it: {' '.join(missed[:6])} :: {c['text'][:40]}")
            fails.append(i)
            continue
        said = " ".join(w["text"] for w in spoken)
        sim = SequenceMatcher(None, letters(c["text"]), letters(said)).ratio()
        # Timing is measured against the words the transcript actually carries, not against the
        # window the manifest declares for them. Trusting the declared window hid a caption that
        # stood for five seconds over a word not spoken until the fourth (2026-09-21).
        if not spoken:
            print(f"  cue {i} [{c['start']:.2f}-{c['end']:.2f}] FAIL no transcript word inside its window :: {c['text'][:50]}")
            fails.append(i)
            continue
        first = min(w["start"] for w in spoken) + shift
        last = max(w["end"] for w in spoken) + shift
        lead = first - c["start"]
        tail = c["end"] - last
        verdict = []
        # Numbers are compared exactly, never fuzzily. A price, quantity, date or phone digit is
        # the part of a caption that cannot be approximately right, and inside a longer line a
        # wrong one moved the similarity by about three points, well under the 0.90 bar.
        cue_nums, said_nums = numbers(c["text"]), numbers(said)
        if cue_nums != said_nums:
            verdict.append(f"numbers differ, caption {cue_nums} vs spoken {said_nums}")
        if sim < 0.90: verdict.append(f"text {sim:.2f} vs spoken '{said}'")
        if lead > 0.50: verdict.append(f"cue up {lead:.2f}s before speech")
        if lead < -0.30: verdict.append(f"cue {(-lead):.2f}s late")
        if tail < -0.10: verdict.append(f"cue drops {(-tail):.2f}s before the line ends")
        state = "FAIL" if verdict else "ok"
        print(f"  cue {i} [{c['start']:.2f}-{c['end']:.2f}] {state} {'; '.join(verdict)} :: {c['text'][:50]}")
        if verdict: fails.append(i)
    print("CAPTION GATE", "FAIL" if fails else "PASS", f"({len(m['cues'])} cues)")
    return 1 if fails else 0

if __name__ == "__main__":
    sys.exit(main())
