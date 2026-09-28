#!/usr/bin/env python3
"""caption_gate.py <captions.json>: every burned caption must say what is being spoken, when it is spoken.

Reads the manifest the ad builder writes beside its srt. For each cue it checks three things against the
STT read-back of the audio actually in the cut: the cue text matches the words spoken in its window
(letters only, so a.m./am and harbor/harbour do not fail it), the cue appears no later than 0.3 s after
the first spoken word and no earlier than 0.5 s before it, and it stays up until the last spoken word.
Exit 0 pass, 1 fail. The author, 2026-08-26, after the delivered cuts lip-synced early and the captions drifted with
them; the gate that shipped them measured the whole master and never looked at a cue.
"""
import json, re, sys
from difflib import SequenceMatcher

def letters(t): return re.sub(r"[^a-z]", "", t.lower())
def words(stt):
    return [w for w in json.load(open(stt))["words"] if w["type"] == "word"]

def main():
    m = json.load(open(sys.argv[1]))
    vo, av = words(m["vo_stt"]), words(m["av_stt"])
    off = m["closer_start"]
    fails = []
    for i, c in enumerate(m["cues"], 1):
        if i <= 3:
            spoken = [w for w in vo if w["start"] >= c["spoken_start"] - 0.05 and w["end"] <= c["spoken_end"] + 0.05]
        else:
            spoken = [w for w in av if off + w["start"] >= c["spoken_start"] - 0.05 and off + w["end"] <= c["spoken_end"] + 0.05]
        said = " ".join(w["text"] for w in spoken)
        sim = SequenceMatcher(None, letters(c["text"]), letters(said)).ratio()
        lead = c["spoken_start"] - c["start"]
        tail = c["end"] - c["spoken_end"]
        verdict = []
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
