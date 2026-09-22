"""The eight files in gates/ decide whether an ad ships, and until 2026-09-21 no test or CI step
ran any of them. An adversarial sweep that day found nine ways a gate says PASS while measuring
nothing. Every test here reproduces one of those, so a gate that goes quiet fails the build instead
of shipping the clip it was supposed to stop.

Each test names the defect it guards. Run with: python3 -m pytest tests/test_gates.py -v
"""
import importlib.util
import json
import os
import shutil
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GATES = os.path.join(ROOT, "gates")


def run(args, **kw):
    return subprocess.run(args, cwd=ROOT, capture_output=True, text=True, timeout=120, **kw)


def load(name):
    """Import a gate module by path. A gate that runs work at import time fails here."""
    path = os.path.join(GATES, name)
    spec = importlib.util.spec_from_file_location(name[:-3], path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def manifest(tmp, cues, vo_words, av_words, closer_start=0.0):
    for n, words in (("vo", vo_words), ("av", av_words)):
        json.dump({"words": [{"type": "word", "text": t, "start": s, "end": e} for t, s, e in words]},
                  open(os.path.join(tmp, f"{n}.json"), "w"))
    m = {"vo_stt": os.path.join(tmp, "vo.json"), "av_stt": os.path.join(tmp, "av.json"),
         "closer_start": closer_start, "cues": cues}
    p = os.path.join(tmp, "captions.json")
    json.dump(m, open(p, "w"))
    return p


# --------------------------------------------------------------------------------------
# caption_gate.py
# --------------------------------------------------------------------------------------

def test_caption_gate_compares_digits(tmp_path):
    """A caption reading 199 against spoken 999 must fail. The normaliser stripped every
    non-letter, so prices, quantities and dates were compared as empty strings."""
    t = str(tmp_path)
    cues = [{"text": "Only 199", "start": 0.0, "end": 1.0, "spoken_start": 0.0, "spoken_end": 1.0}]
    p = manifest(t, cues, [("only", 0.0, 0.4), ("999", 0.5, 1.0)], [])
    r = run([sys.executable, os.path.join(GATES, "caption_gate.py"), p])
    assert r.returncode != 0, f"199 passed against spoken 999:\n{r.stdout}"


def test_caption_gate_compares_numbers_exactly_inside_a_long_caption(tmp_path):
    """Fuzzy matching on the whole line hid a wrong number. "Get only 199 dollars today" against
    spoken 999 scores about 0.97, well past the 0.90 bar, so the price shipped."""
    t = str(tmp_path)
    text = "Get only 199 dollars today and keep the rest"
    spoken = [("get", 0.0, 0.1), ("only", 0.1, 0.2), ("999", 0.2, 0.3), ("dollars", 0.3, 0.4),
              ("today", 0.4, 0.5), ("and", 0.5, 0.6), ("keep", 0.6, 0.7), ("the", 0.7, 0.8),
              ("rest", 0.8, 0.9)]
    cues = [{"text": text, "start": 0.0, "end": 1.0, "spoken_start": 0.0, "spoken_end": 1.0}]
    p = manifest(t, cues, spoken, [])
    r = run([sys.executable, os.path.join(GATES, "caption_gate.py"), p])
    assert r.returncode != 0, f"a wrong price passed inside a long caption:\n{r.stdout}"


def test_caption_gate_refuses_a_manifest_with_no_cues(tmp_path):
    """Zero cues printed PASS. An upstream omission then reads as a clean inspection."""
    p = manifest(str(tmp_path), [], [], [])
    r = run([sys.executable, os.path.join(GATES, "caption_gate.py"), p])
    assert r.returncode != 0, f"an empty manifest passed:\n{r.stdout}"


def test_caption_gate_times_against_the_words_actually_spoken(tmp_path):
    """Lead and tail were measured against the manifest's own declared window, so a manifest
    claiming speech from 0 to 5 hid a word that is not spoken until second 4."""
    t = str(tmp_path)
    cues = [{"text": "hello", "start": 0.0, "end": 5.0, "spoken_start": 0.0, "spoken_end": 5.0}]
    p = manifest(t, cues, [("hello", 4.0, 5.0)], [])
    r = run([sys.executable, os.path.join(GATES, "caption_gate.py"), p])
    assert r.returncode != 0, f"a caption up 4s before its word passed:\n{r.stdout}"


def test_caption_gate_refuses_a_window_that_leaves_out_a_spoken_word(tmp_path):
    """The manifest used to decide which words existed. A stale window could exclude part of the
    line, and the caption then passed against speech it never covered."""
    t = str(tmp_path)
    cues = [{"text": "buy one", "start": 0.0, "end": 2.0, "spoken_start": 0.0, "spoken_end": 1.0}]
    p = manifest(t, cues, [("buy", 0.1, 0.5), ("one", 0.5, 0.9), ("free", 1.4, 1.9)], [])
    r = run([sys.executable, os.path.join(GATES, "caption_gate.py"), p])
    assert r.returncode != 0, f"a word spoken under the caption was ignored:\n{r.stdout}"


# --------------------------------------------------------------------------------------
# board_probe.py
# --------------------------------------------------------------------------------------

def test_board_probe_refuses_an_empty_board(tmp_path):
    """An empty object printed BOARD PROBE PASS (0 spots)."""
    p = os.path.join(str(tmp_path), "b.json")
    json.dump({"spots": {}, "guard": ""}, open(p, "w"))
    r = run([sys.executable, os.path.join(GATES, "board_probe.py"), p])
    assert r.returncode != 0, f"an empty board passed:\n{r.stdout}"


# --------------------------------------------------------------------------------------
# edge_clip_probe.py
# --------------------------------------------------------------------------------------

def test_edge_probe_refuses_unreadable_media(tmp_path):
    """A nonexistent path printed EDGE CLEAN and exited 0, so missing media was
    indistinguishable from inspected footage."""
    r = run([sys.executable, os.path.join(GATES, "edge_clip_probe.py"),
             os.path.join(str(tmp_path), "nope.mp4")])
    assert r.returncode != 0, f"an unreadable clip read CLEAN:\n{r.stdout}"
    assert "CLEAN" not in r.stdout.upper(), r.stdout


def test_edge_probe_merges_each_side_on_its_own():
    """Hits merged only with the immediately preceding event, so a prop clipped on BOTH edges
    alternated sides, left every event one frame long, and never reached the three-frame floor."""
    ecp = load("edge_clip_probe.py")
    hits = [(i * 0.04, "left" if i % 2 == 0 else "right", 400) for i in range(20)]
    events = ecp.merge_events(hits)
    real = [e for e in events if e["frames"] >= 3]
    assert real, "twenty alternating both-edge hits produced no event"


# --------------------------------------------------------------------------------------
# script_match.sh
# --------------------------------------------------------------------------------------

def test_script_match_fails_when_its_normaliser_is_missing(tmp_path):
    """The normaliser used to be a program built by a command substitution, so a failure to
    produce it handed python3 an empty program, which exits 0, and the gate printed
    SCRIPT-MATCH PASS on a comparison that never ran. It is now a file, checked before use."""
    t = str(tmp_path)
    shutil.copy(os.path.join(GATES, "script_match.sh"), os.path.join(t, "sm.sh"))
    for n in ("a", "b"):
        open(os.path.join(t, f"{n}.txt"), "w").write("hello world")
    r = subprocess.run(["bash", os.path.join(t, "sm.sh"),
                        os.path.join(t, "a.txt"), os.path.join(t, "b.txt")],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode != 0, f"a gate with no normaliser beside it passed:\n{r.stdout}"
    assert "PASS" not in r.stdout, r.stdout


def test_script_match_accept_requires_a_comparison_to_have_happened(tmp_path):
    """--accept records a deliberate wording difference. It also swallowed a missing file, so an
    override could authorise audio whose contents were never read."""
    t = str(tmp_path)
    shutil.copy(os.path.join(GATES, "script_match.sh"), os.path.join(t, "sm.sh"))
    open(os.path.join(t, "script.txt"), "w").write("hello world")
    r = subprocess.run(["bash", os.path.join(t, "sm.sh"), os.path.join(t, "missing.json"),
                        os.path.join(t, "script.txt"), "--accept", "deliberate"],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode != 0, f"--accept passed an unreadable input:\n{r.stdout}\n{r.stderr}"


@pytest.mark.parametrize("text,expected", [
    ("one thousand two hundred dollars", ["1200", "dollars"]),
    ("one two", ["1", "2"]),
    ("twenty five", ["25"]),
    ("one hundred and five", ["105"]),
    ("black and white", ["black", "and", "white"]),
    ("a thousand dollars at three in the morning", ["1000", "dollars", "at", "3", "in", "the", "morning"]),
])
def test_number_words_normalise_without_changing_their_value(text, expected):
    """Adjacent number words were accumulated arithmetically, so one thousand two hundred became
    100200 and one two collided with three."""
    tn = load("textnorm.py")
    assert tn.norm(text) == expected


def test_both_gates_share_one_normaliser():
    """The normaliser used to live inside a bash heredoc, where caption_gate.py could not reach
    it, so the two gates disagreed about what two texts saying the same thing looks like."""
    sm = open(os.path.join(GATES, "script_match.sh")).read()
    cg = open(os.path.join(GATES, "caption_gate.py")).read()
    assert "textnorm.py" in sm, "script_match.sh does not use the shared normaliser"
    assert "from textnorm import" in cg, "caption_gate.py does not use the shared normaliser"
    assert "norm_py" not in sm, "the old heredoc normaliser is still in script_match.sh"


def test_caption_gate_accepts_a_spoken_number_written_as_digits(tmp_path):
    """A caption reading 199 against a transcript that spells the number out is the same claim."""
    t = str(tmp_path)
    cues = [{"text": "Only 199", "start": 0.0, "end": 1.0, "spoken_start": 0.0, "spoken_end": 1.0}]
    p = manifest(t, cues, [("only", 0.0, 0.3), ("one", 0.3, 0.5), ("hundred", 0.5, 0.7),
                           ("ninety", 0.7, 0.85), ("nine", 0.85, 1.0)], [])
    r = run([sys.executable, os.path.join(GATES, "caption_gate.py"), p])
    assert r.returncode == 0, f"digits rejected against the same number spoken:\n{r.stdout}"


# --------------------------------------------------------------------------------------
# mouth_sync_probe.py, the only lip-sync check that blocks
# --------------------------------------------------------------------------------------

def test_no_face_is_not_the_same_answer_as_review():
    """Fewer than five detections returned exit 2 before any correlation was computed, and
    ad_gates.sh maps every 2 to REVIEW, so a closer with no measurable mouth reached AD GATES PASS."""
    msp = load("mouth_sync_probe.py")
    assert msp.NO_FACE != msp.EXIT["REVIEW"], "no face and REVIEW share an exit code"
    gate = open(os.path.join(GATES, "ad_gates.sh")).read()
    # Read the case statement that routes the probe's exit code, not the whole file. A bare
    # substring check passed vacuously on ("q1","q2","q3"), which also contains "3)".
    case = next(line for line in gate.splitlines() if line.lstrip().startswith('case "$rm" in'))
    arm = case.split(f"{msp.NO_FACE})", 1)
    assert len(arm) == 2, f"the exit-code case has no arm for no-face ({msp.NO_FACE}): {case}"
    assert "fail=1" in arm[1].split(";;", 1)[0], f"no-face does not fail the gate: {case}"


def test_mouth_sync_verdicts_are_a_pure_function():
    """The verdict rule has to be testable without a face model, or it is only ever exercised
    on a machine that already has insightface installed."""
    msp = load("mouth_sync_probe.py")
    assert msp.verdict(0.40, 0.05) == "PASS"
    assert msp.verdict(0.05, 0.00) == "FAIL"
    assert msp.verdict(0.40, 0.50) == "REVIEW"


# --------------------------------------------------------------------------------------
# the directory as a whole
# --------------------------------------------------------------------------------------

@pytest.mark.parametrize("name", sorted(f for f in os.listdir(GATES) if f.endswith(".py")))
def test_every_gate_imports_with_no_side_effects(name):
    """CI imports probes/ and never gates/. source_gate.py read sys.argv at import time and two
    gates import model libraries that are in neither requirements.txt nor pyproject.toml."""
    load(name)


def test_ad_gates_reads_file_size_portably():
    """stat -f is BSD only, so the receipt line died on any Linux runner."""
    gate = open(os.path.join(GATES, "ad_gates.sh")).read()
    assert "stat -f" not in gate, "ad_gates.sh uses the BSD-only stat -f"


def test_ad_gates_takes_the_frame_rate_from_the_file():
    """The closer assembly arithmetic hardcoded 25 fps, so a 30 fps render mismeasured drift and
    the 40 ms tolerance judged the wrong number."""
    gate = open(os.path.join(GATES, "ad_gates.sh")).read()
    assert "/25*1000" not in gate.replace(" ", ""), "ad_gates.sh hardcodes 25 fps"


def test_voice_take_checks_its_probe_before_spending():
    """voice_take.sh calls a voice_probe.py that is not in this repository, and it called it
    only after the TTS draws, so a fresh clone spent vendor credit and then failed."""
    sh = open(os.path.join(GATES, "voice_take.sh")).read()
    probe_line = sh.index("voice_probe.py")
    first_post = sh.index("api.elevenlabs.io")
    assert "voice_probe.py" in sh
    guard = sh[:first_post]
    assert "voice_probe.py" in guard or "PROBE" in guard, (
        "the probe is not checked before the first TTS request")
    assert probe_line != -1
