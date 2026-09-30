"""Score one render, alone, several times. The only file on the scoring path that calls a model.

Eight frames are sampled evenly across the clip, the sampling T2VQA specifies. The captions
are burned into the picture, so the script arrives with the shot it was spoken over and no
transcript is needed.

The model call is LEAN: --bare (no hooks, plugins or LSP), empty setting sources (no
CLAUDE.md or memory files), no tools, no MCP, no session persistence, and a one-line system
prompt. A judge that has read the operator's own notes is not a judge. The image rides inside
a stream-json user message, which is what lets the tool list stay empty while vision works.

Every reply is checked before it counts: the last event in the stream must be a result, only
that result's text is parsed (an earlier assistant draft is never consulted), the result must
not carry is_error, and that text must be exactly one JSON object, optionally inside a code
fence, with nothing else around it and no NaN or Infinity constant anywhere in it, since those
are not JSON however readily Python decodes them. A truncated object, prose before it, or a
second object after it (a "correction") is refused rather than searched, because a salvaged
fragment could decide a kill. Every axis must be present at the top level as a JSON number (a
boolean or a quoted number is refused), finite, and inside 1 to 10, and a key that appears
twice is refused rather than overwritten.
A malformed reply raises instead of scoring. `parse_scores` holds these checks and is tested
without a model in test_gate.py. The saved scores in results/ predate both the --bare flag and
this strict parse; results/PROVENANCE.md says exactly what produced them.

Usage:  python3 judge.py path/to/render.mp4 [--reps 20]  ->  a JSON list of calls on stdout,
        each {"craft": n, "message": n, "warmth": n}, ready for gate.py.
Needs ffmpeg, ffprobe and the claude CLI on PATH. All three fail loud if missing.
"""
from __future__ import annotations

import argparse
import base64
import json
import math
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from gate import AXES, SCORE_MAX, SCORE_MIN, VALIDATED_REPS

FRAMES = 8
WIDTH = 512
MODEL = "claude-sonnet-5"

RUBRIC = """You are judging one short video ad, shown as eight frames sampled evenly
across the clip, in order. The spoken line is burned into each frame as a caption, so read
the captions to get the script.

Score it 1 to 10 on three axes.

craft: camera, lighting, continuity, how cleanly it is made, whether anything looks wrong.
message: how clearly the product idea lands, whether the script earns its ending.
warmth: whether it feels made by a person for a person. Human presence, intimacy, humour,
mess. An ad can be warm and badly made, or cold and flawless. Score this independently and
do not let craft pull it.

Use the whole range. A 7 for everything is not a judgement.

Reply with JSON only, no prose, no code fence:
{"craft":n,"message":n,"warmth":n,"why":"one short sentence"}"""


def frames(clip: Path, tmp: Path) -> list[Path]:
    dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                "-of", "csv=p=0", str(clip)], capture_output=True, text=True,
                               check=True).stdout.strip())
    out = []
    for i in range(FRAMES):
        t = dur * (i + 0.5) / FRAMES
        f = tmp / f"{i:02d}.jpg"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{t:.2f}", "-i", str(clip),
                        "-frames:v", "1", "-vf", f"scale={WIDTH}:-1", "-q:v", "6", str(f)],
                       check=True)
        out.append(f)
    return out


def one_call(frame_paths: list[Path]) -> dict:
    content = [{"type": "text", "text": RUBRIC}]
    for f in frame_paths:
        content.append({"type": "image", "source": {
            "type": "base64", "media_type": "image/jpeg",
            "data": base64.b64encode(f.read_bytes()).decode()}})
    msg = json.dumps({"type": "user", "message": {"role": "user", "content": content}})
    p = subprocess.run(
        ["claude", "-p", "--bare",
         "--setting-sources", "", "--tools", "",
         "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}',
         "--no-session-persistence", "--disable-slash-commands",
         "--model", MODEL,
         "--system-prompt", "You are a judge. Reply with JSON only.",
         "--input-format", "stream-json", "--output-format", "stream-json", "--verbose"],
        input=msg, capture_output=True, text=True, timeout=300)
    if p.returncode != 0:
        raise RuntimeError(f"claude exit {p.returncode}: {p.stderr[:300]}")
    # Only the result event's text is parsed. An assistant event earlier in the stream can
    # carry a draft with score-shaped JSON, and reading it would let a draft bypass every
    # check applied to the final reply. Non-JSON lines are skipped and do not count as events.
    result_text = None
    last_type = None
    for line in p.stdout.splitlines():
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        last_type = ev.get("type")
        if last_type == "result":
            if ev.get("is_error"):
                raise RuntimeError(f"judge returned an error result: {str(ev.get('result'))[:200]}")
            result_text = ev.get("result") or ""
    if last_type != "result" or result_text is None:
        raise RuntimeError("judge stream did not end in a result event; treating as no judgment")
    return parse_scores(result_text)


def parse_scores(text: str) -> dict:
    """The result text as scores, or a ValueError.

    The whole text must be one JSON object, optionally in a code fence. It is decoded from
    the first character and must be consumed to the last, so a truncated object, prose before
    it, or a second object after it all fail. Searching the text for any object that happens
    to carry the three axes would let an ambiguous reply decide a kill.
    """
    def no_dupes(pairs):
        seen = set()
        for k, _ in pairs:
            if k in seen:
                raise ValueError(f"judge reply names {k!r} twice")
            seen.add(k)
        return dict(pairs)

    def no_constants(name):
        # Python's decoder accepts NaN and Infinity, which JSON does not. A reply carrying one
        # anywhere is not a JSON document, and a NaN could sit in an axis.
        raise ValueError(f"judge reply contains {name}, which is not JSON")

    t = text.strip()
    fence = re.fullmatch(r"```[A-Za-z]*\s*(.*?)\s*```", t, re.S)
    if fence:
        t = fence.group(1)
    try:
        v, end = json.JSONDecoder(object_pairs_hook=no_dupes, parse_constant=no_constants).raw_decode(t)
    except json.JSONDecodeError as e:
        raise ValueError(f"judge reply is not one JSON object: {t[:200]!r}") from e
    if t[end:].strip():
        raise ValueError(f"judge reply has text after its JSON object: {t[end:end + 100]!r}")
    if not isinstance(v, dict):
        raise ValueError(f"judge reply is not an object: {t[:200]!r}")
    missing = [a for a in AXES if a not in v]
    if missing:
        raise ValueError(f"judge reply is missing {missing}: {t[:200]!r}")
    if any(isinstance(v[a], bool) for a in AXES):
        raise ValueError(f"judge returned a boolean where a score was expected: {v}")
    # A quoted number is a string, and a string is not a score; float("6") would hide that.
    if any(not isinstance(v[a], (int, float)) for a in AXES):
        raise ValueError(f"judge returned a non-number where a score was expected: {v}")
    out = {a: float(v[a]) for a in AXES}
    bad = {a: x for a, x in out.items() if not math.isfinite(x) or not SCORE_MIN <= x <= SCORE_MAX}
    if bad:
        raise ValueError(f"judge scored outside {SCORE_MIN} to {SCORE_MAX}: {bad}")
    return out


def score(clip: Path, reps: int = VALIDATED_REPS) -> list[dict]:
    if reps < 1:
        raise ValueError(f"reps must be at least 1, got {reps}")
    with tempfile.TemporaryDirectory() as d:
        fp = frames(clip, Path(d))
        return [one_call(fp) for _ in range(reps)]


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("clip", type=Path)
    ap.add_argument("--reps", type=int, default=VALIDATED_REPS)
    a = ap.parse_args()
    try:
        print(json.dumps(score(a.clip, a.reps)))
    except Exception as e:
        print(json.dumps({"error": str(e)}), file=sys.stderr)
        sys.exit(1)
