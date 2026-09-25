"""The eight files in gates/ decide whether an ad ships, and until 2026-09-21 no test or CI step
ran any of them. An adversarial sweep that day found nine ways a gate says PASS while measuring
nothing. Every test here reproduces one of those, so a gate that goes quiet fails the build instead
of shipping the clip it was supposed to stop.

Each test names the defect it guards. Run with: python3 -m pytest tests/test_gates.py -v
"""
import glob
import importlib.util
import json
import os
import re
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


def _board_checks(tmp_path, scene, narration="It works."):
    p = os.path.join(str(tmp_path), "b.json")
    spot = {"brand": "Acme", "quirk": "a lamp hums", "narration": narration,
            "scenes": {"a": scene + " Mouth closed, nobody speaks."}}
    json.dump({"guard": "Keep the subject in the middle third.", "spots": {"s": spot}}, open(p, "w"))
    r = run([sys.executable, os.path.join(GATES, "board_probe.py"), p, "--json"])
    return json.loads(r.stdout)["spots"]["s"]["checks"]


def _cast_check(tmp_path, scene):
    return _board_checks(tmp_path, scene)["cast"]


def _register(tmp_path, narration):
    return _board_checks(tmp_path, "A warehouse hums.", narration)["register"]


def test_board_probe_sends_back_a_person_who_is_not_the_story_character(tmp_path):
    """Every person in a scene is the story's character, written {character} where she appears.
    The Z.ai scenes wrote "a student", and the girl changed from one scene to the next. The
    narrator appears only in the closer, so {presenter} in a scene fails too."""
    assert _cast_check(tmp_path, "{character} sits at a desk, her mug beside her.") is True
    assert _cast_check(tmp_path, "A tiny studio where a student sits at a desk.") is False, "a student passed"
    assert _cast_check(tmp_path, "The room grows around her desk.") is False, "a pronoun with no character passed"
    assert _cast_check(tmp_path, "{character} hands a coffee to a customer.") is False, "a second person passed"
    assert _cast_check(tmp_path, "{presenter} sits at a desk.") is False, "the narrator was written into a scene"
    assert _cast_check(tmp_path, "{character} and {presenter} share a desk.") is False, "the narrator passed beside her"
    assert _cast_check(tmp_path, "A warehouse hums, screens scrolling, a mug perfectly still.") is True
    assert _cast_check(tmp_path, "The theme of these shelves is a human touch.") is True, "words inside words read as people"


def test_board_probe_sends_back_a_narration_that_talks_about_someone(tmp_path):
    """The voice talks to the viewer, never about the character (the doctrine, 2026-08-29), and the
    doctrine's own example is the Z.ai line. A narration with he, she, his, her, him or hers fails,
    whatever its case, and a word that only contains one of them does not."""
    zai = json.load(open(os.path.join(ROOT, "shoots", "graph-zai-cast", "boards.json")))["spots"]["zai"]["narration"]
    fixed = json.load(open(os.path.join(ROOT, "shoots", "graph-zai-character", "boards.json")))["spots"]["zai"]["narration"]
    old, new = "Her studio apartment is smaller than the problem she's solving.", \
        "Your studio apartment is smaller than the problem you're solving."
    assert zai.startswith(old) and fixed == new + zai[len(old):], "the new board changed more than the first sentence"
    assert _register(tmp_path, zai) is False, "the doctrine's own banned line passed"
    assert _register(tmp_path, fixed) is True
    for word in ("He", "she", "HIS", "her", "him", "Hers"):
        assert _register(tmp_path, f"Then {word} builds.") is False, word
    for word in ("sheer", "theme", "history", "himalayan", "ethics", "shell"):
        assert _register(tmp_path, f"A {word} build.") is True, word


NO_CHAIN = object()


def _chain_check(tmp_path, chain=NO_CHAIN, noun="student"):
    scenes = {"a": "{character} sits at a desk.", "b": "The room grows around {character}.", "c": "A mug sits still."}
    p = os.path.join(str(tmp_path), "b.json")
    spot = {"brand": "Acme", "quirk": "a lamp hums", "narration": "It works.",
            "scenes": {k: v + " Mouth closed, nobody speaks." for k, v in scenes.items()}}
    if chain is not NO_CHAIN:
        spot["chain"] = chain
    if noun:
        spot["character_noun"] = noun
    json.dump({"guard": "Keep the subject in the middle third.", "spots": {"s": spot}}, open(p, "w"))
    r = run([sys.executable, os.path.join(GATES, "board_probe.py"), p, "--json"])
    return json.loads(r.stdout)["spots"]["s"]["checks"]["chain"]


def test_board_probe_holds_a_chain_to_the_spots_own_scenes(tmp_path):
    """A chained spot shoots its scenes in the chain's order, each from the last frame of the one
    before, so the chain names the spot's own scenes, each once. The frame carries her face and the
    prompt only names her, so a chained scene that writes {character} needs a noun to name her by.
    A spot with no chain passes, and a chain may leave a scene out."""
    assert _chain_check(tmp_path) is True
    assert _chain_check(tmp_path, ["a", "b", "c"]) is True
    assert _chain_check(tmp_path, ["a", "c"]) is True
    assert _chain_check(tmp_path, ["c"], noun=None) is True, "a chain with nobody in it was asked for a noun"
    assert _chain_check(tmp_path, ["a", "d"]) is False, "a chain naming a scene the spot lacks passed"
    assert _chain_check(tmp_path, ["a", "b", "a"]) is False, "a scene listed twice passed"
    assert _chain_check(tmp_path, []) is False, "an empty chain passed"
    assert _chain_check(tmp_path, "abc") is False, "a chain that is not a list passed"
    assert _chain_check(tmp_path, ["a", "b"], noun=None) is False, "a chained character with no noun to name her passed"


# --------------------------------------------------------------------------------------
# cast_gate.py
# --------------------------------------------------------------------------------------

def test_the_cast_verdict_is_on_the_mean_and_the_floor_is_inclusive():
    cast = _gate_module("cast_gate")
    assert cast.CAST_MIN == 0.30
    assert cast.verdict([0.30]) == "PASS" and cast.verdict([0.299]) == "FAIL"
    assert cast.verdict([0.9, 0.1, 0.1]) == "PASS", "one odd frame sank a scene whose faces are her"
    assert cast.verdict([0.1, 0.1, 0.5]) == "FAIL"
    assert cast.verdict([]) == "NOFACE"
    assert cast.line([0.46, 0.44, 0.48]) == "CAST_GATE faces=3 sim=0.46 min=0.44 strangers=0 not=- floor=0.30 verdict=PASS"
    assert cast.line([]) == "CAST_GATE faces=0 sim=nan min=nan strangers=0 not=- floor=0.30 verdict=NOFACE"
    assert cast.verdict([0.5] * 8, strangers=1) == "PASS", "one glitched frame read as a person"
    assert cast.verdict([0.5] * 8, strangers=2) == "FAIL", "a stranger behind her passed"
    assert cast.line([0.5], 2) == "CAST_GATE faces=1 sim=0.50 min=0.50 strangers=2 not=- floor=0.30 verdict=FAIL"


def test_a_scene_that_reads_as_close_to_the_narrator_as_to_her_fails():
    """The narrator rendered into the girl's scene read 0.40 against the girl, over the floor, and
    0.53 against the narrator. With a second reference read, a scene at least as close to it as to
    the first fails, on the means and a tie included, and it never lifts a scene under the floor."""
    cast = _gate_module("cast_gate")
    assert cast.verdict([0.40] * 8, 0, [0.53] * 8) == "FAIL"
    assert cast.verdict([0.40] * 8, 0, [0.40] * 8) == "FAIL", "a tie went to the character"
    assert cast.verdict([0.40] * 8, 0, [0.39] * 8) == "PASS"
    assert cast.verdict([0.5, 0.3], 0, [0.6, 0.1]) == "PASS", "one frame decided instead of the means"
    assert cast.verdict([0.29] * 8, 0, [0.10] * 8) == "FAIL", "a scene under the floor passed"
    assert cast.verdict([0.65] * 8, 0, []) == "PASS"
    assert cast.line([0.40] * 8, 0, [0.53] * 8) == \
        "CAST_GATE faces=8 sim=0.40 min=0.40 strangers=0 not=0.53 floor=0.30 verdict=FAIL"
    assert cast.line([], 0, []) == "CAST_GATE faces=0 sim=nan min=nan strangers=0 not=nan floor=0.30 verdict=NOFACE"


def test_the_cast_gate_reads_a_second_face_and_a_still(monkeypatch, capsys):
    """--not reads the main faces against a second reference, the narrator's. A still is read as
    one frame, which is how the character's reference is held apart from the narrator's."""
    import math
    from types import SimpleNamespace as face
    cast = _gate_module("cast_gate")
    her, narrator = [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]
    mixed = [0.40, 0.53, math.sqrt(1 - 0.40 ** 2 - 0.53 ** 2)]

    def img(*embs):
        return face(shape=(720, 1280, 3), faces=[face(normed_embedding=e, bbox=[0, 0, 300, 300]) for e in embs])
    files = {"her.jpg": img(her), "narrator.jpg": img(narrator), "scene.mp4": img(mixed), "empty.jpg": img()}
    monkeypatch.setattr(cast, "read_image", lambda p: files.get(os.path.basename(p)))
    monkeypatch.setattr(cast, "frames", lambda p: [files[os.path.basename(p)]] * 8)
    monkeypatch.setattr(cast, "faces_in", lambda i: list(i.faces) if i is not None else [])
    assert cast.run(["her.jpg", "scene.mp4", "--not", "narrator.jpg"]) == 1
    assert capsys.readouterr().out.strip() == \
        "CAST_GATE faces=8 sim=0.40 min=0.40 strangers=0 not=0.53 floor=0.30 verdict=FAIL"
    assert cast.run(["her.jpg", "scene.mp4"]) == 0, "without a second face the floor alone decides"
    assert " not=- " in capsys.readouterr().out
    assert cast.run(["narrator.jpg", "her.jpg"]) == 1
    assert capsys.readouterr().out.strip() == "CAST_GATE faces=1 sim=0.00 min=0.00 strangers=0 not=- floor=0.30 verdict=FAIL"
    assert cast.run(["her.jpg", "scene.mp4", "--not", "empty.jpg"]) == 64
    assert "second reference holds no face" in capsys.readouterr().out
    assert cast.run(["her.jpg", "scene.mp4", "--not"]) == 64
    two = files["scene.mp4"].faces + files["her.jpg"].faces
    assert cast.against([(two, 720), ([], 720)], files["narrator.jpg"].faces[0]) == [0.53], "a face behind her was read"


def test_every_face_on_screen_is_read_not_only_the_largest():
    """A stranger behind the presenter is still a person on screen. A second face tall enough to
    read that is not hers counts, in two sampled frames or more. A face too small to read and a
    single glitched frame do not, and a stranger larger than her is the main face and fails it."""
    from types import SimpleNamespace as face
    cast = _gate_module("cast_gate")
    ref = face(normed_embedding=[1.0, 0.0])

    def at(emb, height):
        return face(normed_embedding=emb, bbox=[0, 0, height, height])
    her, stranger, tiny = at([1.0, 0.0], 100), at([0.0, 1.0], 100), at([0.0, 1.0], 20)
    alone = [([her], 720)] * 8
    assert cast.score(alone, ref) == ([1.0] * 8, 0)
    behind = [([her, stranger], 720)] * 2 + [([her], 720)] * 6
    assert cast.score(behind, ref) == ([1.0] * 8, 2)
    assert cast.verdict(*cast.score(behind, ref)) == "FAIL"
    assert cast.score([([her, tiny], 720)] * 8, ref)[1] == 0, "a face too small to read counted as a person"
    assert cast.score([([her, stranger], 720)] + [([her], 720)] * 7, ref)[1] == 1
    assert cast.verdict(*cast.score([([stranger, her], 720)] * 8, ref)) == "FAIL"
    assert cast.score([([], 720)] * 8, ref) == ([], 0)


def test_the_cast_gate_loads_without_the_face_extra_and_says_so_when_it_needs_it(tmp_path):
    """derive.py and CI import every gate, and neither has the face model. Asked to measure
    without it, the gate must give no reading, never a verdict."""
    _gate_module("cast_gate")
    assert "insightface" not in sys.modules
    gate = os.path.join(GATES, "cast_gate.py")
    r = run([sys.executable, gate, str(tmp_path / "missing.jpg"), str(tmp_path / "missing.mp4")])
    assert r.returncode == 64 and "unreadable" in r.stdout, (r.returncode, r.stdout)
    face = tmp_path / "face.png"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=gray:s=64x64", "-frames:v", "1",
                    str(face)], check=True, timeout=60)
    r = run([sys.executable, gate, str(face), str(tmp_path / "missing.mp4")])
    assert r.returncode == 64 and "CAST_GATE unreadable" in r.stdout and "verdict=" not in r.stdout, r.stdout


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


def _script_match(tmp_path, script, stt):
    t = str(tmp_path)
    open(os.path.join(t, "script.txt"), "w").write(script)
    with open(os.path.join(t, "stt.json"), "w") as fh:
        json.dump({"text": stt}, fh)
    return subprocess.run(["bash", os.path.join(GATES, "script_match.sh"), os.path.join(t, "stt.json"),
                           os.path.join(t, "script.txt")], capture_output=True, text=True, timeout=60)


@pytest.mark.parametrize("script,stt", [
    # The Z.ai narration and its read-back as the chained run drew them, which failed twice.
    ("Your studio apartment is smaller than the problem you're solving. Z.ai puts frontier open models in "
     "anyone's hands, the same weights the big labs guard, priced for builders. Build like the room was never small.",
     "Your studio apartment is smaller than the problem you're solving. ZAI puts frontier open models in "
     "anyone's hands. The same weights the big labs guard, priced for builders. Build like the room was never small"),
    ("Z.ai puts frontier open models to work.", "Z AI puts frontier open models to work."),
    ("Send it by e-mail tonight.", "Send it by email tonight."),
    ("Send it by email tonight.", "Send it by e-mail tonight."),
    ("It is the 3-D printer.", "It is the 3D printer."),
    ("She said 'build tonight' twice.", "She said build tonight twice."),
    ("Z.ai has one two three steps.", "ZAI has 1 2 3 steps."),
    # A stray quote mark is no word, so a transcript that leaves it out still says the script.
    ("' 12 apples for 3", "12 apples for 3"),
    ("Try GPT-4 tonight.", "Try GPT4 tonight."),
])
def test_script_match_passes_a_word_split_or_joined_differently(tmp_path, script, stt):
    """The Z.ai narration failed its read-back twice because the transcript wrote the brand as one
    word. Its letters and digits ran the same in the same order and only punctuation had split the
    word, which the doctrine always ruled fine as a tokenization difference."""
    r = _script_match(tmp_path, script, stt)
    assert r.returncode == 0, r.stdout + r.stderr
    assert r.stdout.splitlines()[0] == "MATCH", r.stdout


def test_script_match_says_where_a_split_moved(tmp_path):
    """A pass on a split word says which words moved, so the ledger's read-back row shows why."""
    r = _script_match(tmp_path, "Z.ai puts models to work.", "ZAI puts models to work.")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "same words, split differently: z ai / zai" in r.stdout, r.stdout


@pytest.mark.parametrize("script,stt", [
    ("Z.ai puts frontier open models", "ZAI put frontier open models"),
    ("Z.ai puts frontier open models", "ZAI puts open models"),
    ("Z.ai puts frontier open models", "ZAI puts frontier new open models"),
    ("notice what you were actually looking for", "notice what you are actually looking for"),
    ("press one two", "press twelve"),
    ("press 1 2 3", "press 123"),
    # Only punctuation may move a split. A space that comes or goes can change the words.
    ("It is now here", "It is nowhere"),
    ("It is nowhere", "It is now here"),
    ("Go to room twenty-five", "Go to room25"),
    # A point between two digits separates two numbers, and a swap of the same length is still a swap.
    ("It costs 1.5 dollars", "It costs 15 dollars"),
    ("The mug sits still", "The mug sets still"),
    # An apostrophe inside a word is part of it, so a contraction read back as another word differs.
    ("We're ready to build", "Were ready to build"),
])
def test_script_match_still_fails_a_real_word_change(tmp_path, script, stt):
    """A changed word beside a split, a dropped word, an added word, the tense flip that shipped,
    and two numbers read back as one all still stop the render."""
    r = _script_match(tmp_path, script, stt)
    assert r.returncode == 2, r.stdout + r.stderr
    assert r.stdout.splitlines()[0] == "MISMATCH", r.stdout


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

def test_the_gate_header_only_names_probes_the_gate_runs():
    """A comment that names a check the script never runs is a false claim, and this
    repository is about claims being checked.

    Found on 2026-09-23 by re-reading the file rather than trusting the summary of it:
    the header said the closer gate required lipsync_probe not to FAIL, and
    lipsync_probe is not invoked anywhere in this script. It also still named
    sync_probe as a gate condition a month after sync_probe was demoted to a printed
    disclosure. Both read as enforcement to anyone skimming.
    """
    path = os.path.join(ROOT, "gates", "ad_gates.sh")
    with open(path) as fh:
        text = fh.read()
    header = "\n".join(ln for ln in text.splitlines() if ln.startswith("#"))
    body = "\n".join(ln for ln in text.splitlines() if not ln.lstrip().startswith("#"))

    probes = {os.path.basename(p)[:-3]
              for p in glob.glob(os.path.join(ROOT, "probes", "*.py"))
              + glob.glob(os.path.join(ROOT, "gates", "*.py"))}
    # Word boundary, not substring. `sync_probe.py in body` is TRUE whenever the body
    # mentions mouth_sync_probe.py, so deleting the real sync_probe call would leave
    # this test green while the header still described it. That is the same
    # substring-for-token mistake this repository has shipped before.
    run_here = {name for name in probes
                if re.search(rf"(?<![A-Za-z0-9_]){re.escape(name)}\.py\b", body)}
    assert run_here, "the gate runs no probe at all, so this test is checking nothing"
    assert "sync_probe" in run_here and "mouth_sync_probe" in run_here, (
        "the two probes this gate is known to run are not both detected, so the "
        "matcher is wrong rather than the header")

    # No excuse list. An earlier cut excused any line containing "not run" or "until",
    # so "lipsync_probe must not FAIL; not run here" would have passed the test written
    # to reject exactly that sentence. Instead a CLAUSE that names an unrun probe may
    # not also carry obligation language, whatever else it says.
    clauses = [c for line in header.splitlines() for c in re.split(r"[.;]", line)]
    obligation = re.compile(r"\b(must|has to|have to|needs to|required to)\b")
    for name in sorted(probes - run_here):
        for clause in clauses:
            if name not in clause or not obligation.search(clause):
                continue
            raise AssertionError(
                f"the header states {name} as a gate condition and the script never "
                f"runs it:\n  {clause.strip()}")


# the jaw and loudness gates the graph's closer and ship gate nodes call

def test_the_loudness_verdict_holds_both_sides_and_the_peak():
    loud = _gate_module("loudness_gate")
    assert loud.verdict(-16.0, -2.0) == "PASS"
    assert loud.verdict(-15.0, -1.6) == "PASS" and loud.verdict(-17.0, -1.6) == "PASS", "the edges are inside the band"
    assert loud.verdict(-14.9, -2.0) == "FAIL", "a master too loud passed"
    assert loud.verdict(-17.1, -2.0) == "FAIL", "a master too quiet passed"
    assert loud.verdict(-16.0, -1.5) == "FAIL", "a true peak at the ceiling passed"


def test_the_jaw_verdict_at_its_edges():
    jaw = _gate_module("jaw_gate")
    assert jaw.verdict(0.17, 0.70) == "PASS", "the ceiling and the coverage floor are both inclusive"
    assert jaw.verdict(0.171, 1.0) == "FAIL"
    assert jaw.verdict(0.1, 0.699) == "UNMEASURED"


def _gate_module(name):
    import importlib.util
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, "gates", f"{name}.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_the_gate_numbers_are_the_numbers_the_step_table_states():
    """The step table promises a jaw refused over 0.17 and a master within a decibel of -16
    LUFS with a true peak under -1.5 dB. Those sentences and these constants must move
    together, or the table describes a gate that is not the one that runs."""
    sys.path.insert(0, ROOT)
    from pipeline.steps import BY_NODE
    jaw, loud = _gate_module("jaw_gate"), _gate_module("loudness_gate")
    assert f"refused over {jaw.JAW_MAX}" in BY_NODE["closer"].proves
    assert (loud.TARGET_I, loud.TOLERANCE_I, loud.MAX_TP) == (-16.0, 1.0, -1.5)
    assert "within a decibel of -16 LUFS" in BY_NODE["ship_gate"].proves
    assert "true peak under -1.5 dB" in BY_NODE["ship_gate"].proves
    assert f"refused under {_gate_module('cast_gate').CAST_MIN:g} face similarity" in BY_NODE["render"].proves


def test_the_jaw_gate_rules_on_what_source_gate_measured(tmp_path):
    """source_gate needs a face model, so the measurement is stubbed through FACEPY, the
    interpreter the gate runs it with. What is under test is the ruling on its output."""
    jaw = _gate_module("jaw_gate")
    clip = tmp_path / "closer.mp4"
    clip.write_bytes(b"x")
    cases = [("0.95", "0.1167", 0, "PASS"), ("0.95", "0.1900", 1, "FAIL"),
             ("0.40", "0.1100", 64, "UNMEASURED"), ("0.95", "nan", 64, "UNMEASURED")]
    for cov, value, code, word in cases:
        stub = tmp_path / "facepy"
        stub.write_text(f"#!/bin/sh\necho face_cov {cov}\necho jaw_rubber {value}\n")
        stub.chmod(0o755)
        r = subprocess.run([sys.executable, os.path.join(ROOT, "gates", "jaw_gate.py"), str(clip)],
                           env=dict(os.environ, FACEPY=str(stub)), capture_output=True, text=True, timeout=60)
        assert r.returncode == code and f"verdict={word}" in r.stdout.splitlines()[-1], (cov, value, r.stdout)
    assert jaw.verdict(jaw.JAW_MAX, 0.9) == "PASS" and jaw.verdict(jaw.JAW_MAX + 0.001, 0.9) == "FAIL"
    r = subprocess.run([sys.executable, os.path.join(ROOT, "gates", "jaw_gate.py"), str(tmp_path / "missing.mp4")],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 64


def test_the_loudness_gate_measures_the_master(tmp_path):
    def clip(name, audio):
        out = tmp_path / f"{name}.mp4"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", audio, "-f", "lavfi",
                        "-i", "color=black:s=64x64:d=6", "-ac", "2", "-c:a", "aac", "-shortest", str(out)],
                       check=True, timeout=120)
        return out
    at_spec = clip("at_spec", "sine=frequency=440:duration=6,volume=0.3,loudnorm=I=-16:TP=-1.5:LRA=11")
    too_quiet = clip("too_quiet", "sine=frequency=440:duration=6,volume=0.02")
    silent = clip("silent", "anullsrc=r=48000:cl=stereo:d=6")
    for path, code, word in ((at_spec, 0, "PASS"), (too_quiet, 1, "FAIL")):
        r = subprocess.run([sys.executable, os.path.join(ROOT, "gates", "loudness_gate.py"), str(path)],
                           capture_output=True, text=True, timeout=120)
        assert r.returncode == code and f"verdict={word}" in r.stdout.splitlines()[-1], (path.name, r.stdout)
    # Silence has no loudness to measure, which is no verdict: 64, a reason on stderr, and no
    # machine line a caller could read as one.
    r = subprocess.run([sys.executable, os.path.join(ROOT, "gates", "loudness_gate.py"), str(silent)],
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 64 and "LOUDNESS_GATE" not in r.stdout and "silent" in r.stderr, (r.stdout, r.stderr)


def _build_text():
    with open(os.path.join(ROOT, "shoots", "build-ad.sh")) as fh:
        return fh.read()


def test_the_build_crops_the_centre_square_at_any_height(tmp_path):
    """The build cropped a fixed 1080 square at x=420, which fits only 1920x1080, and Omni now
    returns 1280x720, so the first graph run died in the build. Its replacement took the frame's
    height as the side, which fails on a portrait frame. The crop now takes the shorter side,
    centred on both axes, and scales to 1080. The expression under test is read from the build,
    so this checks what the build runs. Landscape frames must come out exactly as they did under
    both earlier crops, and a 720x1280 portrait frame must come out 1080x1080."""
    build = _build_text()
    assert "crop=1080:1080:420:0" not in build and "crop=ih:ih" not in build
    sq = re.search(r"^SQ='([^']+)'$", build, re.M)
    assert sq, "the build no longer defines its scene crop in one place"
    assert build.count("$SQ") == 3, "all three scene paths crop the same way"

    def frames(src, vf):
        r = subprocess.run(["ffmpeg", "-v", "error", "-i", str(src), "-vf", vf, "-f", "framemd5", "-"],
                           capture_output=True, text=True, timeout=120, check=True)
        size = next(ln.split(": ")[1] for ln in r.stdout.splitlines() if ln.startswith("#dimensions"))
        return size, [line.split(",")[-1] for line in r.stdout.splitlines() if not line.startswith("#")]
    for size, rate in (("1920x1080", 25), ("1280x720", 24), ("720x1280", 25)):
        src = tmp_path / f"{size}.mp4"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"testsrc2=size={size}:rate={rate}",
                        "-t", "1", "-pix_fmt", "yuv420p", str(src)], check=True, timeout=120)
        dims, got = frames(src, sq.group(1))
        assert got and dims == "1080x1080", (size, dims)
        if size != "720x1280":
            assert (dims, got) == frames(src, "crop=ih:ih:(iw-ih)/2:0,scale=1080:1080"), (
                f"a {size} scene no longer gets the crop it got before")
        if size == "1920x1080":
            assert got == frames(src, "crop=1080:1080:420:0")[1], "a 1080p scene no longer gets the old crop"


def _block(text, start, end_line_with):
    """The lines of a script from the one holding start to the one holding end_line_with."""
    a = text.index(start)
    a = text.rfind("\n", 0, a) + 1
    b = text.index("\n", text.index(end_line_with, a)) + 1
    return text[a:b]


def test_a_named_spot_takes_the_brand_tag_and_bed_it_is_given():
    """The five August spots set BRAND, TAG and BED over whatever the caller passed, so a board
    run through pipeline/live.py with its own brand shipped the August card and bed, and nothing
    said so. The case statement is run as the build runs it, once with the caller's values set
    and once with none, which must still give the August values."""
    case = _block(_build_text(), "case $AD in", "esac")
    august = {"orchard": ("Orchard Hill Coffee", "Roasted the week it lands.", "/f2/bed3.mp3"),
              "lantern": ("Lantern Street", "The page that opens the right screen.", "/f2/bed4.mp3"),
              "harbor": ("Harbor Lane Realty", "One agent. One street.", "/f2/bed3.mp3"),
              "quiet": ("Quiet Hours", "Sleep, not stats.", "/f2/bed2.mp3"),
              "slowroad": ("Slow Road Travel", "Go slower, see more.", "/f2/bed3.mp3")}
    script = 'set -euo pipefail\nAD="$T_AD"; F2=/f2\n' + case + 'printf "%s\\n" "$BRAND" "$TAG" "$BED"\n'
    base = {k: v for k, v in os.environ.items() if k not in ("BRAND", "TAG", "BED")}
    given = ("A Board Brand", "A board tag.", "/beds/board.mp3")
    for spot, values in august.items():
        r = subprocess.run(["bash", "-c", script], env=dict(base, T_AD=spot, BRAND=given[0], TAG=given[1],
                           BED=given[2]), capture_output=True, text=True, timeout=30)
        assert tuple(r.stdout.splitlines()) == given, (spot, r.stdout, r.stderr)
        r = subprocess.run(["bash", "-c", script], env=dict(base, T_AD=spot), capture_output=True, text=True,
                           timeout=30)
        assert tuple(r.stdout.splitlines()) == values, (spot, r.stdout, r.stderr)


def test_closer_autoalign_is_on_only_at_exactly_one():
    """Any value but 0 switched the probe compensation on, so CLOSER_AUTOALIGN=off or =false
    trimmed video the probe misread, the desync the default exists to prevent. The lines that
    decide it are run as the build runs them, with the probe's lag fixed at 0.25 s."""
    lines = _block(_build_text(), "COMP=$(python3 -c", '"${CLOSER_AUTOALIGN:-0}" = ')
    script = "set -euo pipefail\nMLAG=0.25\n" + lines + 'echo "$COMP"\n'
    base = {k: v for k, v in os.environ.items() if k not in ("CLOSER_AUTOALIGN", "CLOSER_NUDGE")}
    for value, on in ((None, False), ("0", False), ("off", False), ("false", False), ("no", False),
                      ("yes", False), ("true", False), ("1", True)):
        env = dict(base) if value is None else dict(base, CLOSER_AUTOALIGN=value)
        r = subprocess.run(["bash", "-c", script], env=env, capture_output=True, text=True, timeout=30)
        assert r.stdout.strip() == ("0.25" if on else "0"), (value, r.stdout, r.stderr)


def test_a_relative_takes_directory_still_joins_the_segments(tmp_path):
    """ffmpeg resolves a relative entry in a concat list against the list's own directory, so a
    relative TAKES built every scene and then failed at the join. The build's own header and
    join lines run here, from a working directory, with TAKES given relative to it."""
    build = _build_text()
    head = _block(build, "AD=$1;", "V=$T/out-")
    join = _block(build, ': > "$V/concat.txt"', "-f concat")
    out = tmp_path / "work" / "takes" / "out-spot-spot-av"
    out.mkdir(parents=True)
    for q in ("q1", "q2", "q3", "q4", "q5"):
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=64x64:rate=25",
                        "-t", "0.2", "-pix_fmt", "yuv420p", str(out / f"{q}.mp4")], check=True, timeout=60)
    # "set spot" makes spot the script's first argument, the ad name the header reads.
    r = subprocess.run(["bash", "-c", "set -euo pipefail\nset spot\n" + head + join],
                       cwd=tmp_path / "work", env=dict(os.environ, TAKES="takes"),
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 0 and (out / "video.mp4").stat().st_size > 0, r.stderr


def test_the_master_lands_under_the_true_peak_ceiling(tmp_path):
    """shoots/master.sh aimed loudnorm at a true peak of -1.5 dBTP, the gate's own ceiling, and the
    gate compares strictly on a reading rounded to a tenth, so a limited mix re-encoded to AAC
    read -1.5 and failed on every re-master. Tone bursts over a quiet tone are what makes the
    limiter work. Mastered through the script, they must pass the gate with the peak at or under
    -1.9, which the old target cannot reach."""
    built = tmp_path / "built.mp4"
    bursts = "aevalsrc=exprs='0.95*sin(2*PI*1500*t)*lt(mod(t\\,0.25)\\,0.006)+0.1*sin(2*PI*220*t)':s=48000:d=8"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", bursts, "-f", "lavfi", "-i",
                    "color=black:s=64x64:d=8:r=25", "-ac", "2", "-c:a", "aac", "-b:a", "192k", "-c:v", "libx264",
                    "-shortest", str(built)], check=True, timeout=120)
    master = tmp_path / "master.mp4"
    m = subprocess.run(["bash", os.path.join(ROOT, "shoots", "master.sh"), str(built), str(master)],
                       capture_output=True, text=True, timeout=300)
    assert m.returncode == 0, m.stdout + m.stderr
    r = subprocess.run([sys.executable, os.path.join(GATES, "loudness_gate.py"), str(master)],
                       capture_output=True, text=True, timeout=120)
    line = r.stdout.splitlines()[-1] if r.stdout.strip() else ""
    tp = re.search(r"tp=(-?[0-9.]+)", line)
    assert r.returncode == 0 and "verdict=PASS" in line and tp, (r.stdout, r.stderr)
    assert float(tp.group(1)) <= -1.9, f"the master's true peak sits at {tp.group(1)} dBTP"


def test_a_jaw_gate_that_cannot_measure_prints_no_verdict(tmp_path):
    """A crash exited 1 with nothing on stdout, and a caller reads 1 as a jaw over the ceiling,
    so a broken install stopped the run for a new look nobody needed. Every way of not
    measuring now exits 64 with one line on stderr and no JAW_GATE line to be misread."""
    clip = tmp_path / "closer.mp4"
    clip.write_bytes(b"x")
    crashes = tmp_path / "crashes"
    crashes.write_text("#!/bin/sh\necho 'Traceback: ImportError: no face model' >&2\nexit 1\n")
    silent = tmp_path / "says-nothing"
    silent.write_text("#!/bin/sh\necho 'end_ratio 0.500'\nexit 0\n")
    for stub in (crashes, silent):
        stub.chmod(0o755)
    for label, facepy in (("an interpreter that is not there", "/nonexistent/python3"),
                          ("a source_gate that crashes", str(crashes)),
                          ("a source_gate that prints neither number", str(silent))):
        r = subprocess.run([sys.executable, os.path.join(GATES, "jaw_gate.py"), str(clip)],
                           env=dict(os.environ, FACEPY=facepy), capture_output=True, text=True, timeout=60)
        assert r.returncode == 64, (label, r.returncode, r.stdout, r.stderr)
        assert "JAW_GATE" not in r.stdout, (label, r.stdout)
        assert len(r.stderr.strip().splitlines()) == 1 and "no verdict" in r.stderr, (label, r.stderr)


def test_a_loudness_gate_that_cannot_measure_prints_no_verdict(tmp_path):
    """The same failure on the loudness side: no ffmpeg raised out of the gate as a traceback
    and exit 1, which a caller reads as a master out of spec."""
    clip = tmp_path / "master.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=3",
                    "-f", "lavfi", "-i", "color=black:s=64x64:d=3", "-ac", "2", "-c:a", "aac", "-shortest",
                    str(clip)], check=True, timeout=120)
    empty = tmp_path / "no-tools"
    empty.mkdir()
    for label, path, env in (("a file that is not there", tmp_path / "missing.mp4", {}),
                             ("no ffmpeg on the PATH", clip, {"PATH": str(empty)})):
        r = subprocess.run([sys.executable, os.path.join(GATES, "loudness_gate.py"), str(path)],
                           env=dict(os.environ, **env), capture_output=True, text=True, timeout=120)
        assert r.returncode == 64, (label, r.returncode, r.stdout, r.stderr)
        assert "LOUDNESS_GATE" not in r.stdout, (label, r.stdout)
        assert len(r.stderr.strip().splitlines()) == 1 and "no verdict" in r.stderr, (label, r.stderr)


def _ad_gate_run(tmp, with_segments):
    """Run gates/ad_gates.sh on a small master whose caption manifest has no cues, so the caption
    gate fails and no pass receipt is ever written. With segments, q1 to q3 sit beside the
    manifest at one second each and the manifest places the closer audio at 3000 ms."""
    tmp.mkdir(parents=True, exist_ok=True)
    master = tmp / "master.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=160x160:rate=25",
                    "-f", "lavfi", "-i", "sine=frequency=300:duration=6", "-t", "6", "-pix_fmt", "yuv420p",
                    "-c:v", "libx264", "-c:a", "aac", str(master)], check=True, timeout=120)
    if with_segments:
        for q in ("q1", "q2", "q3"):
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=64x64:rate=25",
                            "-t", "1", "-pix_fmt", "yuv420p", str(tmp / f"{q}.mp4")], check=True, timeout=60)
    cj = manifest(str(tmp), [], [], [], closer_start=3.0)
    m = json.load(open(cj))
    m.update(closer_dur=2.0, audio_closer_ms=3000)
    json.dump(m, open(cj, "w"))
    facepy = tmp / "facepy"
    facepy.write_text("#!/bin/sh\necho 'MOUTH SYNC PASS: corr 0.40 at lag +0.00s'\nexit 0\n")
    facepy.chmod(0o755)
    return subprocess.run(["bash", os.path.join(GATES, "ad_gates.sh"), str(master), cj],
                          env=dict(os.environ, FACEPY=str(facepy), TMPDIR=str(tmp)),
                          capture_output=True, text=True, timeout=300)


def test_missing_closer_segments_read_as_unreadable_not_as_drift(tmp_path):
    """With q1 to q3 missing or corrupt beside captions.json the gate measured nothing and still
    reported drift=fail, a placement fault nobody measured, which a caller routes to a rebuild.
    It must read drift=unreadable and still refuse to pass. The control run, segments present
    and placed right, reads drift=pass, so the word is not simply always there."""
    r = _ad_gate_run(tmp_path / "missing", with_segments=False)
    result = [ln for ln in r.stdout.splitlines() if ln.startswith("AD_GATES_RESULT")]
    assert result and " drift=unreadable " in result[-1] + " ", (r.stdout, r.stderr)
    assert r.returncode != 0, "an unmeasured closer passed the gate"
    r = _ad_gate_run(tmp_path / "present", with_segments=True)
    result = [ln for ln in r.stdout.splitlines() if ln.startswith("AD_GATES_RESULT")]
    assert result and " drift=pass " in result[-1] + " ", (r.stdout, r.stderr)
    assert (tmp_path / "present" / "ad-gate-closer-master.mp4").exists(), (
        "the closer window was not cut under TMPDIR")
