"""The eight files in gates/ decide whether an ad ships, and until 2026-09-21 no test or CI step
ran any of them. An adversarial sweep that day found nine ways a gate says PASS while measuring
nothing. Every test here reproduces one of those, so a gate that goes quiet fails the build instead
of shipping the clip it was supposed to stop.

Each test names the defect it guards. Run with: python3 -m pytest tests/test_gates.py -v
"""
import base64
import glob
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import threading

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
    spot = {"brand": "Acme", "quirk": "a lamp hums", "narration": narration, "hook": "a",
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
    """The voice talks to the viewer, never about the character (the doctrine, this repo's own
    written rule for how a spot must be written, 2026-08-29), and the doctrine's own example is
    the Z.ai line. A narration with he, she, his, her, him or hers fails, whatever its case, and
    a word that only contains one of them does not."""
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
    spot = {"brand": "Acme", "quirk": "a lamp hums", "narration": "It works.", "hook": "a",
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
    # With no slots the build plays a, b and c in turn, so a chain shot in another order would be cut out of it.
    assert _chain_check(tmp_path, ["a", "c", "b"]) is False, "a chain shot out of the order the cut plays it passed"
    assert _chain_check(tmp_path, ["b", "a"]) is False, "a chain shot out of the order the cut plays it passed"


NO_SLOTS = object()


def _slots_check(tmp_path, slots=NO_SLOTS, chain=NO_CHAIN, narration="It works. It is cheap. Build it."):
    scenes = {"a": "{character} sits at a desk.", "b": "The room grows around {character}.",
              "c": "A mug sits still.", "d": "The room folds back around {character}."}
    p = os.path.join(str(tmp_path), "b.json")
    spot = {"brand": "Acme", "quirk": "a lamp hums", "narration": narration, "character_noun": "student", "hook": "a",
            "scenes": {k: v + " Mouth closed, nobody speaks." for k, v in scenes.items()}}
    if slots is not NO_SLOTS:
        spot["slots"] = slots
    if chain is not NO_CHAIN:
        spot["chain"] = chain
    json.dump({"guard": "Keep the subject in the middle third.", "spots": {"s": spot}}, open(p, "w"))
    r = run([sys.executable, os.path.join(GATES, "board_probe.py"), p, "--json"])
    return json.loads(r.stdout)["spots"]["s"]["checks"]["slots"]


def test_board_probe_holds_slots_to_the_three_sentences_the_builder_cuts(tmp_path):
    """A sentence can hold more than one shot. The slots give each of the three sentences the
    builder cuts the narration into its own shots, every scene in exactly one of them, and a chained
    scene plays in the chain's order. A spot with no slots passes, one scene to a sentence."""
    three = [["a"], ["b", "c"], ["d"]]
    assert _slots_check(tmp_path) is True
    assert _slots_check(tmp_path, three) is True
    assert _slots_check(tmp_path, three, chain=["a", "b", "c", "d"]) is True
    assert _slots_check(tmp_path, three, chain=["b", "c"]) is True, "a chain that leaves a scene out was refused"
    assert _slots_check(tmp_path, three, narration="One. Two. Three. Four. Five.") is True, (
        "a narration the builder merges down to three was refused")
    assert _slots_check(tmp_path, [["a"], ["b"], ["d"]]) is False, "a scene left out of every slot passed"
    assert _slots_check(tmp_path, [["a"], ["b", "c"], ["c", "d"]]) is False, "a scene in two slots passed"
    assert _slots_check(tmp_path, [["a"], ["b", "x"], ["c", "d"]]) is False, "a scene the spot lacks passed"
    assert _slots_check(tmp_path, [["a", "b"], ["c", "d"]]) is False, "two slots for three sentences passed"
    assert _slots_check(tmp_path, [["a"], [], ["b", "c", "d"]]) is False, "an empty slot passed"
    assert _slots_check(tmp_path, "abcd") is False, "slots that are not a list passed"
    assert _slots_check(tmp_path, [["a"], ["c", "b"], ["d"]], chain=["a", "b", "c", "d"]) is False, (
        "shots playing out of the chain's order passed")
    assert _slots_check(tmp_path, three, narration="It works. Build it.") is False, (
        "a narration the builder cannot cut into three sentences held slots")


def _probe(tmp_path, spot, as_json=True):
    """board_probe.py on a one-spot board: (the spot's report, the exit code), or the text report."""
    p = tmp_path / "hooked.json"
    p.write_text(json.dumps({"guard": "Keep the subject in the middle third.", "spots": {"s": spot}}))
    r = run([sys.executable, os.path.join(GATES, "board_probe.py"), str(p)] + (["--json"] if as_json else []))
    return (json.loads(r.stdout)["spots"]["s"], r.returncode) if as_json else (r.stdout, r.returncode)


def _hook_spot(**extra):
    """A spot that passes every other check, with four scenes, a to d, so where the film opens can move."""
    scenes = {k: f"A warehouse hums around shelf {k}. Mouth closed, nobody speaks." for k in "abcd"}
    return {"brand": "Acme", "quirk": "a lamp hums", "narration": "It works. It is cheap. Build it.",
            "scenes": scenes, **extra}


FULL = {"hook": 3, "realism": 2, "absurdity": 3, "logic": 2}


def test_board_probe_sends_back_a_spot_that_does_not_name_its_hook(tmp_path):
    """Start with the hook. A spot names the scene that opens the film in 'hook', and one that names none
    fails the board, with a reason that says what to add, the scene the film opens on now."""
    spot, code = _probe(tmp_path, _hook_spot())
    assert spot["checks"]["hook_first"] is False and code == 1, spot
    assert spot["why"] == {"hook_first": 'add "hook": "a", naming the scene that opens the film'}, spot["why"]
    for blank in (None, "", "  "):
        spot, code = _probe(tmp_path, _hook_spot(hook=blank))
        assert spot["checks"]["hook_first"] is False and spot["why"]["hook_first"].startswith('add "hook"'), (blank, spot)
    spot, code = _probe(tmp_path, _hook_spot(hook="a"))
    assert spot["checks"]["hook_first"] is True and spot["why"] == {} and code == 0, spot
    said, code = _probe(tmp_path, _hook_spot(), as_json=False)
    assert code == 1 and 'hook_first: add "hook": "a"' in said, said


def test_board_probe_sends_back_a_hook_the_film_does_not_open_on(tmp_path):
    """The first shot is the first entry of 'order' if the spot has one, else of 'chain', else the first
    shot of the first slot, else the first scene key, and the hook has to be that shot."""
    three = [["b"], ["a", "c"], ["d"]]
    for extra in (dict(hook="a"), dict(hook="b", slots=three), dict(hook="b", chain=["b", "a", "c", "d"], slots=three),
                  dict(hook="b", order=["b", "a", "c", "d"], slots=three),
                  dict(hook="b", order=["b", "a", "c", "d"], chain=["b", "a", "c", "d"], slots=three)):
        spot, code = _probe(tmp_path, _hook_spot(**extra))
        assert spot["checks"]["hook_first"] is True and code == 0, (extra, spot)
    for extra in (dict(hook="b"), dict(hook="a", slots=three), dict(hook="a", chain=["b", "a", "c", "d"], slots=three),
                  dict(hook="a", order=["b", "a", "c", "d"], slots=three)):
        spot, code = _probe(tmp_path, _hook_spot(**extra))
        assert spot["checks"]["hook_first"] is False and code == 1, (extra, spot)
        assert spot["why"]["hook_first"].startswith("hook names scene a" if extra["hook"] == "a" else "hook names scene b"), spot
    spot, _ = _probe(tmp_path, _hook_spot(hook="a", order=["b", "a", "c", "d"], slots=three))
    assert "the film opens on scene b, the first entry of its order" in spot["why"]["hook_first"], spot["why"]
    for hook in ("z", ["a"], 1):
        spot, code = _probe(tmp_path, _hook_spot(hook=hook))
        assert spot["checks"]["hook_first"] is False and "not one of this spot's scenes" in spot["why"]["hook_first"], (hook, spot)
    # A chain that names a scene the spot lacks is the chain check's to report, and the next source answers.
    spot, _ = _probe(tmp_path, _hook_spot(hook="a", chain=["x", "a"]))
    assert spot["checks"]["chain"] is False and spot["checks"]["hook_first"] is True, spot


def test_board_probe_sends_back_an_order_or_a_chain_the_build_would_not_play(tmp_path):
    """The build reads neither order nor chain for the cut. It plays each slot's shots in turn, or with no
    slots the first three scene keys, one to each sentence. So a chain that opens on another shot names a
    hook the film would not open on, and goes back whatever its hook says. An order is the board's word on
    how the whole film plays, so one that lists the shots any other way goes back, its first entry right or
    not, and a garbled one goes back before anything reads it."""
    for extra in (dict(hook="b", chain=["b", "a", "c", "d"]), dict(hook="a", chain=["b", "a", "c", "d"]),
                  dict(hook="b", order=["b", "a", "c"]), dict(hook="a", order=["b", "a", "c"]),
                  dict(hook="a", order=["a", "c", "b"]), dict(hook="a", order=["a", "b", "c", "d"]),
                  dict(hook="a", order=["a", "c", "b", "d"], slots=[["a"], ["b", "c"], ["d"]])):
        spot, code = _probe(tmp_path, _hook_spot(**extra))
        assert spot["checks"]["hook_first"] is False and code == 1, (extra, spot)
    spot, _ = _probe(tmp_path, _hook_spot(hook="b", chain=["b", "a", "c", "d"]))
    assert "the build plays scene a first, the first scene key" in spot["why"]["hook_first"], spot["why"]
    spot, _ = _probe(tmp_path, _hook_spot(hook="a", order=["a", "c", "b"]))
    assert spot["why"]["hook_first"] == ("order lists a, c, b, but the build plays a, b, c, the first three scene keys, "
                                         "one to each sentence. List the shots in the order the build plays them"), spot["why"]
    spot, _ = _probe(tmp_path, _hook_spot(hook="a", order=["a", "b", "c", "d"]))
    assert "but the build plays a, b, c," in spot["why"]["hook_first"], "an order naming a shot the build never plays passed"
    for extra in (dict(hook="a", order=["a", "b", "c"]),
                  dict(hook="a", order=["a", "b", "c", "d"], chain=["a", "b", "c", "d"], slots=[["a"], ["b", "c"], ["d"]])):
        spot, code = _probe(tmp_path, _hook_spot(**extra))
        assert spot["checks"]["hook_first"] is True and code == 0, (extra, spot)
    for order in (["a", "a"], ["a", "x"], [], "abcd", [["a"]], {"a": 1}):
        spot, code = _probe(tmp_path, _hook_spot(hook="a", order=order))
        assert spot["checks"]["hook_first"] is False and code == 1, (order, spot)
        assert spot["why"]["hook_first"].startswith("order has to list this spot's own scenes"), (order, spot)


def test_board_probe_reports_the_scores_beside_its_checks_and_never_in_its_verdict(tmp_path):
    """The four judgment rows are a person's read, so the probe reports what the spot scored, who scored
    it and what is unmet, and its verdict and exit code stay the mechanical checks' alone. Only a whole
    number from 0 to 3 counts as scored, a true or false included among the things that do not."""
    nothing = {"hook": "missing", "realism": "missing", "absurdity": "missing", "logic": "missing", "scored_by": "missing"}
    spot, code = _probe(tmp_path, _hook_spot(hook="a"))
    assert code == 0 and spot["scores"] == {"rows": {}, "unmet": nothing}, spot
    spot, code = _probe(tmp_path, _hook_spot(hook="a", scores=[3, 3, 3, 3], scored_by="a reader"))
    assert code == 0 and spot["scores"]["unmet"] == {k: v for k, v in nothing.items() if k != "scored_by"}, spot
    spot, code = _probe(tmp_path, _hook_spot(hook="a", scores=FULL, scored_by=" a reader "))
    assert code == 0 and spot["scores"] == {"rows": FULL, "scored_by": "a reader", "unmet": {}}, spot
    spot, code = _probe(tmp_path, _hook_spot(hook="a", scores={**FULL, "realism": 1, "logic": 0}, scored_by="a reader"))
    assert code == 0 and spot["scores"]["unmet"] == {"realism": "under 2", "logic": "under 2"}, spot
    assert spot["scores"]["rows"] == {**FULL, "realism": 1, "logic": 0}, spot
    for bad in (True, False, 2.5, 3.0, "3", 4, -1, None, [3]):
        spot, code = _probe(tmp_path, _hook_spot(hook="a", scores={**FULL, "logic": bad}, scored_by="a reader"))
        assert code == 0 and spot["scores"]["unmet"] == {"logic": "not a whole number from 0 to 3"}, (bad, spot)
        assert "logic" not in spot["scores"]["rows"], (bad, spot)
    for who in (None, "", "  ", 7, ["a reader"]):
        spot, _ = _probe(tmp_path, _hook_spot(hook="a", scores=FULL, scored_by=who))
        assert spot["scores"]["unmet"] == {"scored_by": "missing"} and "scored_by" not in spot["scores"], (who, spot)
    spot, code = _probe(tmp_path, _hook_spot(scores=FULL, scored_by="a reader"))
    assert code == 1 and spot["checks"]["hook_first"] is False and spot["scores"]["unmet"] == {}, (
        "full scores lifted a failed check")
    said, code = _probe(tmp_path, _hook_spot(hook="a", scores={**FULL, "realism": 1}, scored_by="a reader"), as_json=False)
    assert code == 0 and "hook 3, realism 1, absurdity 3, logic 2, by a reader; unmet: realism under 2" in said, said


def test_the_doctrine_quotes_the_judgment_rows_as_the_probe_prints_them(tmp_path):
    """pipeline/DOCTRINE.md defines the four rows a person scores, and the probe prints them for the eye. The
    two have to say the same words, or a person scores a question the page never asked."""
    bp = load("board_probe.py")
    assert [name for name, _ in bp.JUDGMENT_ROWS] == ["hook", "realism", "absurdity", "logic"]
    doctrine = open(os.path.join(ROOT, "pipeline", "DOCTRINE.md"), encoding="utf-8").read()
    printed, _ = _probe(tmp_path, _hook_spot(hook="a"), as_json=False)
    for name, text in bp.JUDGMENT_ROWS:
        line = f"{name:10s} {text}"
        assert f"\n  {line}\n" in printed, line
        assert f"\n{line}\n" in doctrine, f"pipeline/DOCTRINE.md does not quote the {name} row as the probe prints it"
    assert (bp.SCORE_TOP, bp.SCORE_PASS) == (3, 2), "the doctrine and the page say 0 to 3, and 2 to pass"


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


def test_a_face_too_small_to_read_is_no_face_not_a_reading():
    """A figure far off in a wide shot is a few pixels of face, too few for the model to recognise
    anyone. A frame whose largest face is shorter than MIN_FACE of its height counts as holding none,
    so a scene of only such frames is NOFACE, which goes to the eye, and the bound is inclusive. The
    second reference skips the same frames, so the two readings stay frame for frame."""
    from types import SimpleNamespace as face
    cast = _gate_module("cast_gate")
    ref, other = face(normed_embedding=[1.0, 0.0]), face(normed_embedding=[0.0, 1.0])

    def at(height):
        return face(normed_embedding=[1.0, 0.0], bbox=[0, 0, height, height])
    bound = int(cast.MIN_FACE * 1000)
    far = [([at(bound - 1)], 1000)] * 8
    assert cast.score(far, ref) == ([], 0)
    assert cast.verdict(*cast.score(far, ref)) == "NOFACE"
    assert cast.against(far, other) == []
    near = [([at(bound)], 1000)] * 8
    assert cast.score(near, ref) == ([1.0] * 8, 0), "a face exactly at the bound was not read"
    mixed = [([at(bound - 1)], 1000)] * 4 + [([at(bound * 3)], 1000)] * 4
    assert cast.score(mixed, ref) == ([1.0] * 4, 0) and cast.against(mixed, other) == [0.0] * 4


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
    """voice_take.sh calls voice_probe.py, and it once called it only after the TTS draws, so a
    clone without the probe spent vendor credit and then failed."""
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
    cont = _gate_module("continuity_gate")
    assert (f"moves over {cont.PAIR_BLOB} px between two frames or sits {cont.MEDIAN_BLOB} px off the clip's median"
            in BY_NODE["closer"].proves)


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
    """The build cropped a fixed 1080 square at x=420, which fits only 1920x1080, and Omni (Google's
    Gemini Omni Flash video model, one of the engines the pipeline renders scenes on, reached
    through fal) now returns 1280x720, so the first graph run died in the build. Its replacement took the frame's
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


def _switch_times():
    spec = importlib.util.spec_from_file_location("switch_times", os.path.join(ROOT, "shoots", "switch_times.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _cuts_clip(path):
    """White, black, white, two seconds each at 25 fps, so the picture cuts at 2.0 and 4.0 s."""
    parts = ("color=c=white:s=160x90:r=25:d=2[a];color=c=black:s=160x90:r=25:d=2[b];"
             "color=c=white:s=160x90:r=25:d=2[c];[a][b][c]concat=n=3:v=1:a=0,format=yuv420p[v]")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-filter_complex", parts, "-map", "[v]", str(path)],
                   check=True, timeout=120)
    return path


def _hits(mode, video="none", card="30", closer=None):
    """shoots/switches.sh's switch_hits for a mode, with the second and third sentences at 4.52 and
    13.96 s, and the closer's start as a sixth argument when one is given: its exit, KHITS, KLABELS,
    NK and SWITCHLINE, and what it said on stderr."""
    r = subprocess.run(["bash", "-c", '. "$0"; switch_hits "$1" 4520 13960 "$2" "$3" "${@:4}"; rc=$?; '
                        'printf "%s\\n%s\\n%s\\n%s\\n%s\\n" "$rc" "$KHITS" "$KLABELS" "$NK" "$SWITCHLINE"',
                        os.path.join(ROOT, "shoots", "switches.sh"), mode, str(video), card,
                        *([] if closer is None else [closer])],
                       capture_output=True, text=True, timeout=120)
    return r.stdout.split("\n")[:5], r.stderr


def test_the_switching_sound_finds_a_cut_and_a_morph_but_not_a_pop_or_a_pan():
    """A chained cut changes its picture two ways worth a whoosh, a hard cut all at once and a morph
    over about half a second. A one-frame pop in a render and a slow camera move are not scene
    changes, and neither is a picture that never stops moving. The sound goes a tenth of a second
    ahead of the frame that changes most, the first of them when two change equally."""
    st = _switch_times()
    changes = [0.8] * 750                                   # 30 s at 25 fps, a quiet baseline
    changes[99] = 70.0                                      # a hard cut arriving with frame 100, at 4.00 s
    for k, v in zip(range(293, 305), (4, 5, 6, 7, 8, 9, 10, 8, 7, 6, 5, 4), strict=True):  # pii-allow: a synthetic change curve, not a schedule
        changes[k] = v                                      # a morph over 12 frames, its biggest arriving at 12.00 s,
                                                            # no quarter second of it enough on its own
    changes[199] = 14.0                                     # a one-frame pop at 8.00 s
    for k in range(450, 500):
        changes[k] = 3.5                                    # a slow pan from 18 to 20 s
    assert st.picks(changes, 30.0) == [3.9, 11.9]
    busy = [4.5] * 750                                      # her talking, the camera drifting, every frame moving
    busy[99] = 70.0
    assert st.picks(busy, 30.0) == [3.9]
    even = [0.8] * 750
    even[99] = even[100] = 40.0                             # a change spread evenly over two frames
    assert st.picks(even, 30.0) == [3.9]


def test_the_switching_sound_keeps_the_stronger_of_two_close_changes_and_at_most_four():
    """Two changes closer than two seconds keep the stronger, and the earlier when they are equal, so
    the same picture always gets the same sound. Four is the most a cut gets, the strongest four.
    Nothing goes within a second of the card, which has its own sting, and a change with the very
    first frame cannot be led."""
    st = _switch_times()
    close = [0.8] * 1000
    close[99], close[136] = 60.0, 90.0                     # 4.00 s and 5.48 s
    assert st.picks(close, 40.0) == [5.38]
    tie = [0.8] * 1000
    tie[99], tie[124] = 60.0, 60.0                         # 4.00 s and 5.00 s, equally strong
    assert st.picks(tie, 40.0) == [3.9]
    close[136], close[149] = 0.8, 90.0                     # 4.00 s and 6.00 s, exactly two seconds apart
    assert st.picks(close, 40.0) == [3.9, 5.9]
    many = [0.8] * 1000
    for n, k in enumerate(range(99, 900, 100)):             # nine cuts, each stronger than the last
        many[k] = 60.0 + n
    assert st.picks(many, 40.0) == [23.9, 27.9, 31.9, 35.9]
    near = [0.8] * 1000
    near[99], near[974] = 70.0, 80.0                       # the second lands 0.1 s before a card at 39.1 s
    assert st.picks(near, 39.1) == [3.9]
    first = [0.8] * 500
    first[0] = 70.0
    assert st.picks(first, 20.0) == [0.0]
    assert st.picks([], 20.0) == []


def test_the_cut_to_the_closer_gets_the_switching_sound_however_little_it_changes():
    """The build puts the closer in itself, so it knows where that cut is to the frame. The cut to
    the rebuilt Z.ai closer, lit darker than the story, measured 46.5 against the line's 55, and
    the whoosh the approved cuts version had at 16.7 s was gone. Given the closer's start, the sound
    goes a tenth of a second ahead of it whatever the picture measures. A measured cut within two
    seconds of it gives way to it, it is one of the four, and it is not placed within a second of
    the card, like any other."""
    st = _switch_times()
    quiet = [0.8] * 750                                     # 30 s at 25 fps, a quiet baseline
    assert st.picks(quiet, 30.0) == [] and st.picks(quiet, 30.0, 16.76) == [16.66]
    dim = [0.8] * 750
    dim[418] = 47.3                                         # the cut to a darker closer at 16.76 s, 46.5 above the median
    assert st.picks(dim, 30.0) == [] and st.picks(dim, 30.0, 16.76) == [16.66]
    near = [0.8] * 750
    near[274] = 90.0                                        # a hard cut at 11.00 s, a second before the closer
    assert st.picks(near, 30.0) == [10.9] and st.picks(near, 30.0, 12.0) == [11.9]
    many = [0.8] * 1000
    for n, k in enumerate(range(99, 900, 100)):             # nine cuts, each stronger than the last
        many[k] = 60.0 + n
    assert st.picks(many, 40.0, 38.5) == [27.9, 31.9, 35.9, 38.4]
    assert st.picks(quiet, 30.0, 29.5) == [] and st.picks(near, 30.0, 29.5) == [10.9]
    assert st.picks([], 20.0, 16.76) == [16.66]


def test_the_switching_sound_reads_hard_cuts_off_a_real_video(tmp_path):
    """The detector reads the picture through ffmpeg. White, black and white cut at 2.0 and 4.0 s,
    so the sound goes at 1.9 and 3.9, and nothing past the card at 6 s is read."""
    clip = _cuts_clip(tmp_path / "cuts.mp4")
    r = subprocess.run([sys.executable, os.path.join(ROOT, "shoots", "switch_times.py"), str(clip), "6.0"],
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 0 and r.stdout.splitlines()[-1] == "SWITCHES mode=cuts at=1.90,3.90", r.stdout + r.stderr


def test_the_default_switching_sound_is_the_august_mix_to_the_byte():
    """A board that says nothing gets the mix the build made before there were modes, hit2 under the
    second and third sentences and nothing extra printed. The build's own mix lines are read here,
    so what they make from the snippet is exactly the two lines they replaced."""
    legacy = "[6:a]adelay=4520|4520,volume=0.4[k1];[6:a]adelay=13960|13960,volume=0.4[k2];"
    out, _ = _hits("")
    assert out == ["0", legacy, "[k1][k2]", "2", ""], out
    out, _ = _hits("slots")
    assert out == ["0", legacy, "[k1][k2]", "2", "SWITCHES mode=slots at=4.52,13.96"], out
    out, _ = _hits("off")
    assert out == ["0", "", "", "0", "SWITCHES mode=off at="], out
    out, err = _hits("loud")
    assert out[0] == "2" and "slots, off or cuts" in err, (out, err)
    build = _build_text()
    assert "[k1];[6:a]adelay=$T3MS" not in build and build.count("\n$KHITS\n") == 1, "hit2 reaches the mix another way"
    amix = "[vo][m1][m2][m3][av][bed]$KLABELS[h1]amix=inputs=$((7 + NK)):duration=first:normalize=0[a]"
    assert build.count(amix) == 1
    made = subprocess.run(["bash", "-c", '. "$0"; switch_hits "" 4520 13960 none 30; printf "%s" "' + amix + '"',
                           os.path.join(ROOT, "shoots", "switches.sh")], capture_output=True, text=True, timeout=60)
    assert made.stdout == "[vo][m1][m2][m3][av][bed][k1][k2][h1]amix=inputs=9:duration=first:normalize=0[a]", made.stdout
    assert 'switch_hits "${SWITCHES:-}"' in build, "the build passes a mode other than the board's"


def test_cuts_mode_puts_the_switching_sound_where_the_picture_changes(tmp_path):
    clip = _cuts_clip(tmp_path / "cuts.mp4")
    out, err = _hits("cuts", clip, "6.0")
    assert out == ["0", "[6:a]adelay=1900|1900,volume=0.4[k1];[6:a]adelay=3900|3900,volume=0.4[k2];",
                   "[k1][k2]", "2", "SWITCHES mode=cuts at=1.90,3.90"], (out, err)


def test_the_closers_start_reaches_the_detector_and_its_cut_sounds_once(tmp_path):
    """The build passes the closer's start through switch_hits to the detector. White, black and white
    cut at 2.0 and 4.0 s, and with the closer at 4.0 that cut is both the build's number and a change
    the detector measures, so it gets one sound, not two: 1.9 and 3.9, as without the closer. A picture
    that never changes stops a call without the closer's start, and with it gets the sound there."""
    clip = _cuts_clip(tmp_path / "cuts.mp4")
    r = subprocess.run([sys.executable, os.path.join(ROOT, "shoots", "switch_times.py"), str(clip), "6.0", "4.0"],
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 0 and r.stdout.splitlines()[-1] == "SWITCHES mode=cuts at=1.90,3.90", r.stdout + r.stderr
    out, err = _hits("cuts", clip, "6.0", "4.0")
    assert out == ["0", "[6:a]adelay=1900|1900,volume=0.4[k1];[6:a]adelay=3900|3900,volume=0.4[k2];",
                   "[k1][k2]", "2", "SWITCHES mode=cuts at=1.90,3.90"], (out, err)
    still = tmp_path / "still.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=black:s=160x90:r=25:d=6", str(still)],
                   check=True, capture_output=True, timeout=120)
    assert _hits("cuts", still, "5.0")[0][0] == "4"
    out, err = _hits("cuts", still, "5.0", "2.0")
    assert out == ["0", "[6:a]adelay=1900|1900,volume=0.4[k1];", "[k1]", "1", "SWITCHES mode=cuts at=1.90"], (out, err)


def test_a_build_asked_for_cuts_stops_when_the_detector_cannot_read_the_picture(tmp_path):
    """A build asked for the switching sound at the cuts never goes out without it. A detector that
    cannot read the picture fails switch_hits with no hits set, and the build, which runs under
    set -euo pipefail and calls it bare, stops there with the error."""
    missing = str(tmp_path / "missing.mp4")
    out, err = _hits("cuts", missing, "6.0")
    assert out[0] not in ("", "0") and out[1:4] == ["", "", "0"], (out, err)
    build = _build_text()
    call = next(line for line in build.splitlines() if line.startswith('switch_hits "${SWITCHES:-}"'))
    assert "||" not in call and "&&" not in call, call
    assert build.index("\nset -euo pipefail\n") < build.index(call)
    r = subprocess.run(["bash", "-c", 'set -euo pipefail; . "$0"; switch_hits cuts 4520 13960 "$1" 6.0; echo carried on',
                        os.path.join(ROOT, "shoots", "switches.sh"), missing], capture_output=True, text=True, timeout=120)
    assert r.returncode != 0 and "carried on" not in r.stdout, r.stdout + r.stderr


def test_a_build_asked_for_cuts_stops_when_the_picture_never_changes(tmp_path):
    """A board that asks for the switching sound at the cuts, on footage where nothing changes above
    the detector's line, gets no whoosh at all. Shipping that silently would drop the sound the board
    asked for, so switch_hits refuses with its own exit and names the way out."""
    still = tmp_path / "still.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=black:s=160x90:r=25:d=6", str(still)],
                   check=True, capture_output=True, timeout=120)
    out, err = _hits("cuts", still, "5.0")
    assert out[0] == "4" and out[3] == "0" and out[2] == "", (out, err)
    assert "slots or off" in err, err


def test_the_board_gate_the_toolkit_and_the_build_know_the_same_switching_modes(tmp_path):
    """A gate that knew a mode the build does not would pass a board the build then refuses, after
    the spend. So every mode the board gate passes, the build accepts, and any other it refuses."""
    spec = importlib.util.spec_from_file_location("board_probe", os.path.join(GATES, "board_probe.py"))
    bp = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bp)
    sys.path.insert(0, ROOT)
    from pipeline.toolkit import SWITCHES
    assert tuple(bp.SWITCHES) == tuple(SWITCHES) == ("slots", "off", "cuts")
    clip = _cuts_clip(tmp_path / "cuts.mp4")
    for mode in SWITCHES:
        assert _hits(mode, clip, "6.0")[0][0] == "0", mode
    assert _hits("cut", clip, "6.0")[0][0] == "2"


def test_board_probe_refuses_a_switching_mode_the_build_does_not_know(tmp_path):
    def switches(value):
        p = tmp_path / "b.json"
        spot = {"brand": "Acme", "quirk": "a lamp hums", "narration": "It works.", "hook": "a",
                "scenes": {"a": "A warehouse hums. Mouth closed, nobody speaks."}}
        if value is not None:
            spot["switches"] = value
        p.write_text(json.dumps({"guard": "Keep the subject in the middle third.", "spots": {"s": spot}}))
        r = run([sys.executable, os.path.join(GATES, "board_probe.py"), str(p), "--json"])
        return json.loads(r.stdout)["spots"]["s"]["checks"]["switches"]
    assert switches(None) and switches("slots") and switches("off") and switches("cuts")
    assert not switches("scenes") and not switches("") and not switches(["cuts"])


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


# --------------------------------------------------------------------------------------
# continuity_gate.py
# --------------------------------------------------------------------------------------

LAPTOP = "an open laptop on the desk"
PAPER = "flying paper"


def _still(path, size="64x48", color="gray"):
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"color=c={color}:s={size}", "-frames:v", "1", str(path)],
                   check=True, timeout=60)
    return path


def _shot(path, seconds=2):
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=320x180:rate=25", "-t", str(seconds),
                    "-pix_fmt", "yuv420p", str(path)], check=True, timeout=120)
    return path


def _judge(tmp, answer):
    """A stand-in for the claude CLI. `answer` is one answer for every call, or a list the calls take in
    turn: the votes run at once, so each call claims the next number by creating its file, which only one
    process can do. Each keeps the arguments and the message the gate sent it in a file of its own, and ends
    its stream-json the way the real one does, with a result event whose text is its answer. An answer of
    None ends with no result at all, a call that died."""
    answers = answer if isinstance(answer, list) else [answer]
    stub = tmp / "claude"
    stub.write_text(f"#!{sys.executable}\nimport json, os, sys\nanswers, d, n = {answers!r}, {str(tmp)!r}, 0\n"
                    "while True:\n"
                    "    try:\n"
                    "        os.close(os.open(os.path.join(d, f'call-{n}'), os.O_CREAT | os.O_EXCL))\n"
                    "        break\n"
                    "    except FileExistsError:\n"
                    "        n += 1\n"
                    "json.dump({'argv': sys.argv[1:], 'message': sys.stdin.read()}, open(os.path.join(d, f'seen-{n}.json'), 'w'))\n"
                    "print(json.dumps({'type': 'system', 'subtype': 'init'}))\n"
                    "a = answers[n % len(answers)]\n"
                    "if a is not None:\n"
                    "    print(json.dumps({'type': 'result', 'subtype': 'success', 'is_error': False, 'result': a,\n"
                    "                      'total_cost_usd': 0.01}))\n")
    stub.chmod(0o755)
    return stub, tmp


def _continuity(tmp, answer, *args):
    """The real gate as a process, its judge the stand-in above. Returns the run and the directory holding
    what each judge call was sent, one seen file per call."""
    stub, seen = _judge(tmp, answer)
    r = subprocess.run([sys.executable, os.path.join(GATES, "continuity_gate.py"), *map(str, args)],
                       env=dict(os.environ, CONTINUITY_CLAUDE=str(stub)), capture_output=True, text=True, timeout=300)
    return r, seen


def _vote(t=None, what="the lid is gone"):
    """One vote on the laptop, holding when t is None and changing form at t otherwise, the background still."""
    prop = {"n": 1, "ok": True, "first_break": None} if t is None else \
        {"n": 1, "ok": False, "first_break": t, "kind": "changes form", "what": what}
    return {"props": [prop], "background": {"ok": True, "breaks": []}}


def _voting(c, monkeypatch, answers):
    """Put a judge in the gate's place that hands each call the next answer in turn, whichever thread asks
    first. An answer is the judge's JSON as a dict, prose as a string, or None for a call that died. Returns
    the questions it was asked, in the order they came."""
    lock, asked = threading.Lock(), []

    def judge(text, images):
        with lock:
            asked.append((text, tuple(images)))
            a = answers[(len(asked) - 1) % len(answers)]
        if a is None:
            return None
        return {"text": a if isinstance(a, str) else json.dumps(a), "cost_usd": 0.02, "model": c.MODEL}
    monkeypatch.setattr(c, "ask", judge)
    return asked


def _moving_square(path, y):
    """Two seconds of flat grey with a white square crossing it at height y."""
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=gray:s=216x216:r=25:d=2",
                    "-f", "lavfi", "-i", "color=c=white:s=30x30:r=25:d=2",
                    "-filter_complex", f"[0][1]overlay=x='10+t*60':y={y}:shortest=1", "-pix_fmt", "yuv420p", str(path)],
                   check=True, timeout=120)
    return path


def test_the_continuity_verdict_is_a_break_then_a_split_then_nothing_unread():
    """A break on either axis fails the take whatever the other says, since no reading of the other could
    save it. Short of a break, a split sends it to the eye, then a question that could not be read leaves no
    verdict, and a take passes only when every question asked was answered."""
    c = _gate_module("continuity_gate")
    assert c.verdict("-", "ok") == "PASS" and c.verdict("ok", "ok") == "PASS"
    assert c.verdict("fail", "ok") == "FAIL" and c.verdict("ok", "fail") == "FAIL" and c.verdict("-", "fail") == "FAIL"
    assert c.verdict("fail", None) == "FAIL" and c.verdict(None, "fail") == "FAIL", "an unread axis saved a broken take"
    assert c.verdict("fail", "split") == "FAIL" and c.verdict("split", "fail") == "FAIL", "a split softened a break"
    assert c.verdict("split", "ok") == "REVIEW" and c.verdict("ok", "split") == "REVIEW" and c.verdict("-", "split") == "REVIEW"
    assert c.verdict("split", None) == "REVIEW" and c.verdict(None, "split") == "REVIEW", "a split was lost to an unread axis"
    assert c.verdict(None, "ok") == "UNREAD" and c.verdict("ok", None) == "UNREAD" and c.verdict("-", "-") == "UNREAD"
    assert c.EXIT == {"PASS": 0, "FAIL": 1, "REVIEW": 2, "UNREAD": 64}, "REVIEW is not the code ad_gates.sh reads as review"


def test_an_axis_fails_only_when_every_vote_names_the_break():
    """One reading failed a cut the author passed where two passed it, so no one reading rules. An axis
    fails when every vote read it and named a break, splits when some did and not all, holds when none did
    and most read it clean, and is otherwise unread."""
    c = _gate_module("continuity_gate")
    assert c.VOTES == 3 and c.tally(["fail"] * 3) == "fail"
    for split in (["fail", "fail", "ok"], ["fail", "ok", "ok"], ["fail", "fail", None], ["fail", None, None]):
        assert c.tally(split) == "split", split
    assert c.tally(["ok"] * 3) == "ok" and c.tally(["ok", "ok", None]) == "ok"
    assert c.tally(["ok", None, None]) is None and c.tally([None] * 3) is None


@pytest.mark.parametrize("votes, code, said", [
    ([_vote(1.25)] * 3, 1, "props=fail background=ok first_break=1.25 verdict=FAIL"),
    ([_vote(1.25), _vote(1.5), _vote()], 2, "props=split background=ok first_break=1.25 verdict=REVIEW"),
    ([_vote(1.5), _vote(), _vote()], 2, "props=split background=ok first_break=1.50 verdict=REVIEW"),
    ([_vote(), _vote(), "It all looks continuous."], 0, "props=ok background=ok first_break=- verdict=PASS"),
    ([_vote(), "It all looks continuous.", None], 64, "props=- background=- first_break=- verdict=UNREAD"),
], ids=["3/3 fail", "2/3 fail", "1/3 fail", "2 ok 1 unread", "1 ok 2 unread"])
def test_three_votes_fail_a_break_outright_and_send_a_split_to_the_eye(tmp_path, monkeypatch, capsys, votes, code, said):
    """Three votes, each asked the same question over the same frames. Every vote naming the laptop's break
    fails the take, one or two naming it is a split for the eye, which points at the earliest break a
    dissenting vote named, and a vote that could not be read does not stop two clean ones passing it, while
    one clean vote beside two unread ones is no reading."""
    c = _gate_module("continuity_gate")
    asked = _voting(c, monkeypatch, votes)
    assert c.main([str(_shot(tmp_path / "shot.mp4")), "--prop", LAPTOP, "--out", str(tmp_path / "found.json")]) == code
    assert capsys.readouterr().out.strip().splitlines()[-1] == f"CONTINUITY_GATE {said}"
    assert len(asked) == c.VOTES and len(set(asked)) == 1, "the votes were not asked one question over the same frames"


def test_a_fail_points_at_the_median_vote_and_keeps_every_vote(tmp_path, monkeypatch, capsys):
    """One vote naming a stray early frame cannot move where a FAIL points: breaks at 0.25, 1.25 and 1.5 point
    at 1.25. Every vote's breaks are kept, each tagged with its vote, and the judge block holds all three
    answers and what they cost together."""
    c = _gate_module("continuity_gate")
    _voting(c, monkeypatch, [_vote(0.25, "a stray early frame"), _vote(1.25), _vote(1.5)])
    out = tmp_path / "found.json"
    assert c.main([str(_shot(tmp_path / "shot.mp4")), "--prop", LAPTOP, "--out", str(out)]) == 1
    assert capsys.readouterr().out.strip().splitlines()[-1].endswith("first_break=1.25 verdict=FAIL")
    record = json.load(open(out))
    assert record["first"]["t"] == 1.25 and record["axes"]["props"]["votes"] == ["fail"] * 3, record["first"]
    assert sorted(f["t"] for f in record["findings"]) == [0.25, 1.25, 1.5], record["findings"]
    assert sorted(f["vote"] for f in record["findings"]) == [1, 2, 3], record["findings"]
    assert len(record["judge"]["answers"]) == 3 and record["judge"]["cost_usd"] == 0.06, record["judge"]


def test_the_votes_are_asked_at_once(tmp_path, monkeypatch):
    """Each vote waits on the network, so the three are asked together, not one after another. A judge that
    answers only once all three are waiting proves it, since asked in turn the first would wait alone."""
    c = _gate_module("continuity_gate")
    together = threading.Barrier(c.VOTES, timeout=10)

    def judge(text, images):
        together.wait()
        return {"text": json.dumps(_vote()), "cost_usd": 0.0, "model": c.MODEL}
    monkeypatch.setattr(c, "ask", judge)
    assert c.main([str(_shot(tmp_path / "shot.mp4")), "--prop", LAPTOP, "--out", str(tmp_path / "found.json")]) == 0


def test_a_judge_answer_is_the_asked_json_or_no_reading():
    """The judge answers strict JSON that names frames by their stamps. Anything else is no reading rather
    than a guess: prose, a prop left out, a break with no frame or a frame the clip does not have, a kind
    nobody asked for, a prop that holds with a break named, a background that fails with nothing named or
    holds with something named. A time no frame carries is no reading either, and neither is an answer
    that leaves a prop out or answers one twice, or a breaks list holding something that is not a break.
    A code fence around the JSON is tolerated."""
    c = _gate_module("continuity_gate")
    times = [0.0, 0.25, 0.5, 0.75, 1.0]
    still = {"ok": True, "breaks": []}
    held = {"props": [{"n": 1, "ok": True, "first_break": None}], "background": still}
    assert c.read_answer(held, [LAPTOP], True, times) == ("ok", "ok", [])
    assert c.answer_of("```json\n" + json.dumps(held) + "\n```") == held
    assert c.answer_of("The laptop looks fine to me.") is None and c.answer_of("[1, 2]") is None
    assert c.read_answer(None, [LAPTOP], True, times) == (None, None, [])
    broke = {"n": 1, "ok": False, "first_break": 0.75, "kind": "changes form", "what": "a flat keyboard is left"}
    p, b, found = c.read_answer({"props": [broke], "background": still}, [LAPTOP], True, times)
    assert (p, b) == ("fail", "ok") and found == [{"axis": "props", "prop": LAPTOP, "t": 0.75, "kind": "changes form",
                                                   "what": "a flat keyboard is left"}], found
    p, b, found = c.read_answer({"props": [dict(broke, first_break=0.7501)], "background": still}, [LAPTOP], True, times)
    assert p == "fail" and found[0]["t"] == 0.75, "a time within the rounding of a frame did not snap to it"
    p, b, found = c.read_answer({"props": [broke], "background": still}, [LAPTOP, PAPER], True, times)
    assert p is None and found == [], "a prop the answer left out did not leave the whole axis unread"
    for bad, why in (([], "a prop left out"), ([dict(broke, first_break=None)], "a break with no frame"),
                     ([dict(broke, first_break=9.0)], "a frame the clip does not have"),
                     ([dict(broke, first_break=0.6)], "a time between two frames"),
                     ([dict(broke, first_break=1.1)], "a time past the last frame, which the old code accepted"),
                     ([dict(broke, kind="melts")], "a kind nobody asked for"),
                     ([dict(broke, n=2)], "an answer about a prop never named"),
                     ([dict(broke, n=True)], "an n that is not really an int"),
                     ([broke, dict(broke, first_break=0.5)], "the same prop answered twice"),
                     ([{"n": 1, "ok": True, "first_break": 0.5}], "a prop that holds with a break named")):
        assert c.read_answer({"props": bad, "background": still}, [LAPTOP], True, times)[0] is None, why
    looped = {"t": 1.0, "kind": "repeats", "what": "the car loops"}
    for bad, why in (({"ok": False, "breaks": []}, "a background that fails with nothing named"),
                     ({"ok": True, "breaks": [looped]}, "a background that holds with a break named"),
                     ({"ok": False, "breaks": [looped, dict(looped, t=None)]}, "a break with no frame"),
                     ({"ok": False, "breaks": [looped, "a car"]}, "a breaks list holding something that is not a break"),
                     ("fine", "prose where the object goes")):
        assert c.read_answer({"background": bad}, [], True, times)[1] is None, why
    assert c.read_answer({"background": {"ok": False, "breaks": [looped]}}, [], True, times) == \
        ("-", "fail", [dict(looped, axis="background")])


def test_the_continuity_gate_exits_on_its_verdict_and_never_writes_over_a_reading(tmp_path):
    """PASS exits 0 and FAIL 1 with the second of the first break, and a judge that answers no JSON, or
    ends with no answer at all, reads UNREAD and exits 64. The machine line is always the last line, and
    the findings beside it name the break. A second reading of the same take goes beside the first."""
    shot = _shot(tmp_path / "shot.mp4")
    held = json.dumps({"props": [{"n": 1, "ok": True, "first_break": None}], "background": {"ok": True, "breaks": []}})
    broke = json.dumps({"props": [{"n": 1, "ok": False, "first_break": 1.25, "kind": "changes form", "what": "the lid is gone"}],
                        "background": {"ok": True, "breaks": []}})
    for i, (answer, code, said) in enumerate(((held, 0, "props=ok background=ok first_break=- verdict=PASS"),
                                              (broke, 1, "props=fail background=ok first_break=1.25 verdict=FAIL"),
                                              ("The laptop looks fine to me.", 64, "props=- background=- first_break=- verdict=UNREAD"),
                                              (None, 64, "props=- background=- first_break=- verdict=UNREAD"))):
        tmp = tmp_path / f"answer{i}"
        tmp.mkdir()
        r, _ = _continuity(tmp, answer, shot, "--prop", LAPTOP, "--out", tmp / "found.json")
        assert r.returncode == code, (answer, r.stdout, r.stderr)
        assert r.stdout.strip().splitlines()[-1] == f"CONTINUITY_GATE {said}", r.stdout
        record = json.load(open(tmp / "found.json"))
        assert record["verdict"] == said.rsplit("=", 1)[1] and record["line"] == f"CONTINUITY_GATE {said}", record
        if code == 1:
            assert record["findings"][0]["t"] == 1.25 and record["findings"][0]["prop"] == LAPTOP, record["findings"]
    first = (tmp_path / "answer0" / "found.json").read_bytes()
    r, _ = _continuity(tmp_path / "answer0", held, shot, "--prop", LAPTOP, "--out", tmp_path / "answer0" / "found.json")
    assert r.returncode == 0 and (tmp_path / "answer0" / "found-v2.json").is_file(), r.stdout
    assert (tmp_path / "answer0" / "found.json").read_bytes() == first, "a second reading overwrote the first"


def test_the_judge_is_called_lean_with_the_frames_as_images_in_one_message(tmp_path):
    """A judge that loads its host's settings, tools or servers is not detached, and costs forty times the
    tokens. Every flag that keeps it lean is on the call, the model is named, and the frames go in over
    stdin as one stream-json user message, the question first and then each grid as a JPEG. Five seconds
    read four times a second is twenty frames, sixteen to a grid."""
    shot = _shot(tmp_path / "shot.mp4", seconds=5)
    r, seen = _continuity(tmp_path, json.dumps({"background": {"ok": True, "breaks": []}}), shot,
                          "--story", "A warehouse hums.", "--out", tmp_path / "found.json")
    assert r.returncode == 0, r.stdout + r.stderr
    sent = [json.load(open(f)) for f in sorted(seen.glob("seen-*.json"))]
    assert len(sent) == 3 and all(x == sent[0] for x in sent), "the three votes were not sent the same call"
    got = sent[0]
    argv = got["argv"]
    for flag, value in (("--setting-sources", ""), ("--tools", ""), ("--mcp-config", '{"mcpServers":{}}'),
                        ("--model", "claude-opus-5-5"), ("--input-format", "stream-json"), ("--output-format", "stream-json")):
        assert argv[argv.index(flag) + 1] == value, (flag, argv)
    for flag in ("-p", "--strict-mcp-config", "--no-session-persistence", "--disable-slash-commands", "--system-prompt", "--verbose"):
        assert flag in argv, flag
    message = json.loads(got["message"])
    assert message["type"] == "user" and message["message"]["role"] == "user"
    text, *images = message["message"]["content"]
    assert text["type"] == "text" and "A warehouse hums." in text["text"] and "BACKGROUND" in text["text"], text
    assert "PROPS" not in text["text"], "the judge was asked about props when none were named"
    assert len(images) == 2 and all(i["type"] == "image" and i["source"]["media_type"] == "image/jpeg" for i in images)
    assert all(base64.b64decode(i["source"]["data"])[:2] == b"\xff\xd8" for i in images)
    judge = json.load(open(tmp_path / "found.json"))["judge"]
    assert judge["cost_usd"] == 0.03 and len(judge["answers"]) == 3, judge


def test_a_continuity_gate_that_cannot_read_never_reads_as_a_break(tmp_path, monkeypatch, capsys):
    """Exit 1 is a break to every caller, and an uncaught crash exits 1. So a clip that is not there,
    findings with nowhere to go, a presenter take read without the matte's torch and a crash anywhere
    inside all read UNREAD and exit 64, each saying why, and none of the first three pays for a judge
    call. Named nothing, it prints its usage and no verdict."""
    shot = _shot(tmp_path / "shot.mp4")
    cases = [("a clip that is not there", [tmp_path / "missing.mp4"]),
             ("findings with nowhere to go", [shot, "--out", tmp_path / "no" / "dir" / "found.json"])]
    if importlib.util.find_spec("torch") is None:
        cases.append(("a presenter take without torch", [shot, "--presenter", "--out", tmp_path / "found.json"]))
    for label, args in cases:
        r, seen = _continuity(tmp_path, "{}", *args)
        assert r.returncode == 64, (label, r.stdout, r.stderr)
        assert r.stdout.strip().splitlines()[-1] == "CONTINUITY_GATE props=- background=- first_break=- verdict=UNREAD", label
        assert "continuity: no reading" in r.stdout and "Traceback" not in r.stderr, (label, r.stdout, r.stderr)
        assert not list(seen.glob("seen-*.json")), f"{label}: a judge was paid with nothing to read"
    r, _ = _continuity(tmp_path, "{}")
    assert r.returncode == 64 and "--prop" in r.stdout and "CONTINUITY_GATE" not in r.stdout, r.stdout
    c = _gate_module("continuity_gate")

    def died(*args, **kwargs):
        raise RuntimeError("the decoder died")
    monkeypatch.setattr(c, "sample", died)
    assert c.main([str(shot), "--out", str(tmp_path / "died.json")]) == 64
    said = capsys.readouterr().out.strip().splitlines()
    assert said[-1].endswith("verdict=UNREAD") and "the decoder died" in said[-2], said


def test_a_decode_that_fails_or_stops_short_is_no_frames(tmp_path, monkeypatch, capsys):
    """sample() kept whatever whole frames ffmpeg wrote and never read its exit code, so a take whose file
    lost its second half was judged, and could pass, on the frames before the cut. Frames from an ffmpeg that
    exits non-zero, even every frame, or frames that stop short of the span are none, and a shot with none
    reads UNREAD with no judge asked. A whole decode still comes back whole."""
    c = _gate_module("continuity_gate")
    shot, size = _shot(tmp_path / "shot.mp4"), (64, 36)
    assert [t for t, _ in c.sample(str(shot), 0.0, 2.0, size)] == [0.0, 0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 1.75]
    assert c.sample(str(shot), 0.0, 3.0, size) == [], "two seconds of frames passed for a three second span"
    failing = tmp_path / "failing"
    failing.mkdir()
    (failing / "ffmpeg").write_text(f"#!{sys.executable}\nimport subprocess, sys\n"
                                    f"subprocess.run([{shutil.which('ffmpeg')!r}, *sys.argv[1:]])\nsys.exit(1)\n")
    (failing / "ffmpeg").chmod(0o755)
    with monkeypatch.context() as m:
        m.setenv("PATH", f"{failing}{os.pathsep}{os.environ['PATH']}")
        assert c.sample(str(shot), 0.0, 2.0, size) == [], "every frame of a decode ffmpeg said failed was kept"
    whole, cut = tmp_path / "whole.mp4", tmp_path / "cut.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=320x180:rate=25", "-t", "2",
                    "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(whole)], check=True, timeout=120)
    cut.write_bytes(whole.read_bytes()[:whole.stat().st_size // 2])   # its header, up front, still says two seconds
    asked = _voting(c, monkeypatch, [_vote()])
    assert c.main([str(cut), "--prop", LAPTOP, "--out", str(tmp_path / "found.json")]) == 64
    said = capsys.readouterr().out.strip().splitlines()
    assert said[-1] == "CONTINUITY_GATE props=- background=- first_break=- verdict=UNREAD", said
    assert asked == [], "a judge was paid to read a take cut off halfway"


def test_the_command_line_is_read_whole_or_refused():
    """A prop is a line of text, a region to ignore is four fractions of the frame in order, and a span runs
    forward from zero. Anything else, an unknown flag or a second clip included, is refused with the reason
    before anything is measured or paid for."""
    c = _gate_module("continuity_gate")
    o = c.options(["take.mp4", "--prop", " an open laptop on the desk ", "--ignore", "0.2,0.1,0.8,1", "--span", "0:13.84",
                   "--story", "A warehouse hums.", "--out", "found.json"])
    assert o == {"clip": "take.mp4", "props": ["an open laptop on the desk"], "story": "A warehouse hums.",
                 "ignore": [0.2, 0.1, 0.8, 1.0], "span": [0.0, 13.84], "presenter": False, "out": "found.json"}, o
    assert c.options(["take.mp4", "--presenter", "--prop", "a mug"])["presenter"] is True
    for bad in (["take.mp4", "--prop", " "], ["take.mp4", "--ignore", "0.8,0.1,0.2,1"], ["take.mp4", "--ignore", "0,0,1"],
                ["take.mp4", "--span", "5:2"], ["take.mp4", "--span", "-1:2"], ["take.mp4", "--frames", "8"],
                ["take.mp4", "other.mp4"], ["take.mp4", "--out"], []):
        with pytest.raises(ValueError):
            c.options(bad)


def test_a_presenter_take_is_measured_whole_so_a_span_is_refused(capsys):
    """A presenter take is read whole against its own median, so --span naming part of one is refused."""
    c = _gate_module("continuity_gate")
    with pytest.raises(ValueError, match="measured whole"):
        c.options(["clip.mp4", "--presenter", "--span", "0:2"])
    o = c.options(["clip.mp4", "--span", "0:2"])
    assert o["span"] == [0.0, 2.0]
    assert c.main(["clip.mp4", "--presenter", "--span", "0:2"]) == 64
    capsys.readouterr()


def test_a_region_to_ignore_is_painted_out_and_named_to_the_judge():
    """The judge is not asked about what it cannot see. The region is flat grey in every frame of every grid,
    the rest of the frame is left as it was, and the question says what the grey box is."""
    import io

    import numpy as np
    from PIL import Image
    c = _gate_module("continuity_gate")
    frames = [(t / 4, np.full((100, 160, 3), 250, np.uint8)) for t in range(18)]
    sheets = c.grids(frames, ignore=[0.25, 0.25, 0.75, 0.75])
    assert len(sheets) == 2, "eighteen frames are one grid of sixteen and one of two"
    first = np.asarray(Image.open(io.BytesIO(sheets[0])).convert("RGB")).astype(int)
    assert abs(first[50, 80] - 128).max() <= 8, first[50, 80]
    assert abs(first[10, 150] - 250).max() <= 8, first[10, 150]
    asked = c.prompt([], "A presenter speaks.", [0.25, 0.25, 0.75, 0.75], True, 0.0, 4.25, 2)
    assert "flat grey box" in asked and "hides the speaker" in asked, asked
    assert "grey box" not in c.prompt([], "A presenter speaks.", None, True, 0.0, 4.25, 2)


def test_the_ruler_fails_what_moves_behind_her_and_passes_what_she_does(tmp_path):
    """Her matte is her region. A square crossing the frame above her is the background moving, the bicycle
    behind the Grok presenter, and it fails on both measures from its first frames. The same square crossing
    where she is moves with her and passes. A matte that covers the whole frame leaves nothing to measure,
    which is no reading, never a still background."""
    import numpy as np
    c = _gate_module("continuity_gate")
    her = np.zeros((216, 216))
    her[120:, :] = 1.0
    area = her.size
    above = c.measure(str(_moving_square(tmp_path / "above.mp4", 20)), matte=lambda f: her)
    state, first, found = c.rule(above)
    assert state == "fail" and {f["measure"] for f in found} == {"pair", "vs_median"} and first <= 0.2, (state, first, found)
    assert max(r["blob"] for r in above["pair"]) >= c.PAIR_BLOB * area / c.REF_AREA
    inside = c.measure(str(_moving_square(tmp_path / "inside.mp4", 160)), matte=lambda f: her)
    assert c.rule(inside)[0] == "ok", ([r["blob"] for r in inside["pair"]], [r["blob"] for r in inside["vs_median"]])
    assert c.rule(c.measure(str(tmp_path / "above.mp4"), matte=lambda f: np.ones(f.shape[:2]))) == (None, None, [])


def test_a_presenter_take_is_measured_not_judged(tmp_path, monkeypatch, capsys):
    """Behind a presenter the camera holds still, so the background is the ruler's to read and no judge is
    asked. Its findings carry the limits it was held to, and the frames with her greyed out go beside
    them for the eye."""
    import numpy as np
    c = _gate_module("continuity_gate")
    her = np.zeros((216, 216))
    her[120:, :] = 1.0
    monkeypatch.setattr(c, "rvm", lambda: (lambda f: her))
    monkeypatch.setattr(c, "ask", lambda *a: pytest.fail("a judge was asked about a presenter's background"))
    out = tmp_path / "found.json"
    assert c.main([str(_moving_square(tmp_path / "take.mp4", 20)), "--presenter", "--out", str(out)]) == 1
    said = capsys.readouterr().out.strip().splitlines()[-1]
    assert re.fullmatch(r"CONTINUITY_GATE props=- background=fail first_break=[0-9.]+ verdict=FAIL", said), said
    ruler = json.load(open(out))["ruler"]
    assert (ruler["pair_limit"], ruler["median_limit"]) == (c.PAIR_BLOB, c.MEDIAN_BLOB) and ruler["strip"], ruler
    assert all((tmp_path / name).is_file() for name in ruler["strip"])


def test_the_matte_is_loaded_only_from_the_local_hub_cache(tmp_path, monkeypatch, capsys):
    """rvm() loaded the matte through torch.hub trusting its GitHub repository, so a hub cache without it
    downloaded that repository's hubconf and ran it, code nobody here had reviewed. It now loads only from the
    local cache TORCH_HOME names, weights included, since the hubconf fetches weights it cannot find and
    unpickles them. A cache missing either reads UNREAD saying the matte has to be put there by hand, never
    that torch is missing. This interpreter carries no torch, so a stand-in answers for its hub."""
    from types import SimpleNamespace
    c = _gate_module("continuity_gate")
    hub, loaded = tmp_path / "hub", []
    with pytest.raises(ImportError, match="not in the local torch hub cache that TORCH_HOME names") as e:
        c.matte_repo(str(hub))
    assert e.value.name == c.MATTE_REPO and "put there once by hand" in str(e.value), e.value
    (hub / c.MATTE_REPO).mkdir(parents=True)
    with pytest.raises(ImportError, match="rvm_mobilenetv3.pth"):
        c.matte_repo(str(hub))
    (hub / "checkpoints").mkdir()
    (hub / c.MATTE_WEIGHTS).write_bytes(b"")
    assert c.matte_repo(str(hub)) == str(hub / c.MATTE_REPO)
    model = SimpleNamespace(to=lambda dev: model, eval=lambda: model)
    torch = SimpleNamespace(hub=SimpleNamespace(get_dir=lambda: str(hub), load=lambda *a, **k: loaded.append((a, k)) or model),
                            backends=SimpleNamespace(mps=SimpleNamespace(is_available=lambda: False)))
    monkeypatch.setitem(sys.modules, "torch", torch)
    c.rvm()
    assert loaded == [((str(hub / c.MATTE_REPO), "mobilenetv3"), {"source": "local"})], loaded
    shutil.rmtree(hub)
    assert c.main([str(_shot(tmp_path / "take.mp4")), "--presenter", "--out", str(tmp_path / "found.json")]) == 64
    said = capsys.readouterr().out.strip().splitlines()
    assert said[-1].endswith("verdict=UNREAD") and "put there once by hand" in said[-2] and "MATTEPY" not in said[-2], said
    assert len(loaded) == 1, "the matte was loaded from a cache that does not hold it"


def test_a_fail_for_the_wrong_reason_or_a_split_on_a_real_break_is_a_miss():
    """--validate agrees with a FAIL label only when the gate fails the labelled axis with its break inside
    the labelled window, so a gate that fails the Perplexity master for flying paper has not seen the laptop
    go, and a split on a real break is a miss, since a real break has to be caught outright. A split on a
    take the author passed is deferred to the eye, a look and not a miss. No reading is a miss, and a null
    window is the whole clip, for a break named by what moved rather than when."""
    c = _gate_module("continuity_gate")
    laptop = {"label": "FAIL", "axis": "props", "window": [4.0, 8.0]}

    def axes(state, t, axis="props"):
        return {axis: {"state": state, "first": {"t": t}}}
    assert c.agrees(laptop, "FAIL", axes("fail", 7.25)) == "agree"
    assert c.agrees(laptop, "FAIL", axes("fail", 2.0)) == "miss", "a break before he saw it go"
    assert c.agrees(laptop, "FAIL", axes("fail", 7.25, "background")) == "miss", "a break on the other axis"
    assert c.agrees(laptop, "REVIEW", axes("split", 7.25)) == "miss", "a real break was only sent to the eye"
    assert c.agrees(laptop, "PASS", {}) == "miss" and c.agrees(laptop, "UNREAD", {}) == "miss"
    assert c.agrees(dict(laptop, window=None), "FAIL", axes("fail", 0.0)) == "agree"
    passed = {"label": "PASS"}
    assert c.agrees(passed, "PASS", {}) == "agree" and c.agrees(passed, "REVIEW", axes("split", 4.75)) == "deferred"
    assert c.agrees(passed, "FAIL", axes("fail", 4.75)) == "miss" and c.agrees(passed, "UNREAD", {}) == "miss"


def test_validate_defers_a_split_on_a_passed_take_and_misses_one_on_a_broken_take(tmp_path, monkeypatch, capsys):
    """The labels as --validate reads them, each run through the real gate with a judge that splits on every
    take, one vote of three naming the laptop's break. On a take the author passed that is deferred to the
    eye, the tally says how close it was, and the run exits 0. Beside a take he failed it is a miss, and the
    run exits 1."""
    c = _gate_module("continuity_gate")
    shot = _shot(tmp_path / "shot.mp4")
    stub, _ = _judge(tmp_path, [json.dumps(_vote(1.25)), json.dumps(_vote()), json.dumps(_vote())])
    monkeypatch.setenv("CONTINUITY_CLAUDE", str(stub))
    passed = {"id": "passed-take", "clip": str(shot), "story": "A laptop sits open on a desk.", "props": [LAPTOP],
              "label": "PASS"}
    broken = dict(passed, id="broken-take", label="FAIL", axis="props", window=[0.0, 2.0])
    labels = tmp_path / "labels.json"
    labels.write_text(json.dumps({"cases": [passed]}))
    assert c.validate(str(labels), out_root=str(tmp_path / "reports")) == 0
    said = capsys.readouterr().out
    assert "props 1/3 fail 2/3 ok" in said and "0 agree, 1 deferred to the eye, 0 missed" in said, said
    labels.write_text(json.dumps({"cases": [passed, broken]}))
    assert c.validate(str(labels), out_root=str(tmp_path / "reports")) == 1
    said = capsys.readouterr().out
    assert "0 agree, 1 deferred to the eye, 1 missed" in said, said


def test_the_continuity_labels_are_whole_and_say_where_each_break_is():
    """--validate holds the gate to these. Every case names its clip and, by hash, the file that was
    labelled. A FAIL names its axis and a window, or none for a break named by what moved, and one on the
    props axis names the prop. A presenter case is measured, so it carries no words for a judge, and every
    other case does. The three breaks caught on 2026-09-27 are all there as FAILs, beside the takes passed."""
    cases = json.load(open(os.path.join(ROOT, "evals", "continuity-labels.json")))["cases"]
    ids = [case["id"] for case in cases]
    assert len(ids) == len(set(ids)), ids
    for case in cases:
        assert case["label"] in ("PASS", "FAIL") and re.fullmatch(r"[0-9a-f]{64}", case["sha256"]), case["id"]
        if case["label"] == "FAIL":
            window = case["window"]
            assert case["axis"] in ("props", "background"), case["id"]
            assert window is None or (len(window) == 2 and 0 <= window[0] < window[1]), case["id"]
            assert case["axis"] != "props" or case.get("props"), f"{case['id']} fails on a prop it never names"
        if case.get("presenter"):
            assert not case.get("board") and not case.get("story"), case["id"]
        else:
            assert (case.get("board") and case.get("spot")) or case.get("story"), f"{case['id']} has no words beside it"
    fails = {case["id"] for case in cases if case["label"] == "FAIL"}
    assert {"perplexity-v4-laptop", "perplexity-v4-face", "grok-av6", "grok-av8"} <= fails, fails
    assert {"zai-v2-mug", "zai-av-v1-august", "grok-av7"} <= set(ids) - fails


def test_a_labelled_master_is_judged_with_its_boards_own_lines(tmp_path):
    """The words beside a labelled master are each shot's line from its board, in the order they were
    shot, with the character named the way the render names her."""
    c = _gate_module("continuity_gate")
    story = c.story_of({"board": "shoots/graph-zai-chain/boards.json", "spot": "zai"})
    assert story.startswith("Shot a: ") and " Shot b: " in story and " Shot c: " in story, story
    assert "{character}" not in story and "the student" in story, story


# --------------------------------------------------------------------------------------
# continuity_gate.py --first-frame
# --------------------------------------------------------------------------------------

def _first_frame_vote(visible=True, what="on the desk"):
    return {"props": [{"n": 1, "visible": visible, "what": what}]}


@pytest.mark.parametrize("votes, code, said", [
    ([_first_frame_vote(False)] * 3, 1, "props=0/1 absent=1 verdict=FAIL"),
    ([_first_frame_vote(False), _first_frame_vote(True), _first_frame_vote(True)], 2, "props=0/1 absent=- verdict=REVIEW"),
    (["not json"] * 3, 64, "props=0/1 absent=- verdict=UNREAD"),
    ([_first_frame_vote(True)] * 3, 0, "props=1/1 absent=- verdict=PASS"),
], ids=["3/3 absent", "split", "malformed", "3/3 visible"])
def test_a_first_frame_check_fails_only_when_every_vote_says_absent(tmp_path, monkeypatch, capsys, votes, code, said):
    """One question of one still: is the named prop visible? Absent only when every vote says so, split
    when the votes disagree, no reading at all when none of that could be trusted, and otherwise visible,
    the same tally the props axis of a full clip uses."""
    c = _gate_module("continuity_gate")
    _voting(c, monkeypatch, votes)
    still = _still(tmp_path / "still.png")
    assert c.main(["--first-frame", str(still), "--prop", LAPTOP, "--out", str(tmp_path / "found.json")]) == code
    assert capsys.readouterr().out.strip().splitlines()[-1] == f"CONTINUITY_FIRST_FRAME {said}"


def test_a_first_frame_check_reads_every_prop_independently(tmp_path, monkeypatch, capsys):
    """Two props, one absent by every vote and one visible by every vote: the verdict follows the worse of
    the two, the machine line counts both, the findings name which one broke and why, and the still
    reaches the judge as exactly one JPEG image, never a grid of several."""
    c = _gate_module("continuity_gate")
    votes = [{"props": [{"n": 1, "visible": False, "what": "not on the desk"},
                        {"n": 2, "visible": True, "what": "closed on the desk"}]}] * 3
    asked = _voting(c, monkeypatch, votes)
    still = _still(tmp_path / "still.png")
    out = tmp_path / "found.json"
    assert c.main(["--first-frame", str(still), "--prop", LAPTOP, "--prop", "a closed laptop",
                  "--out", str(out)]) == 1
    assert capsys.readouterr().out.strip().splitlines()[-1] == "CONTINUITY_FIRST_FRAME props=1/2 absent=1 verdict=FAIL"
    record = json.load(open(out))
    assert record["absent"] == [1] and record["tally"] == ["fail", "ok"], record
    assert sorted(f["vote"] for f in record["findings"]) == [1, 2, 3] and all(f["n"] == 1 for f in record["findings"])
    assert re.fullmatch(r"[0-9a-f]{64}", record["image_sha256"])
    assert len(asked) == c.VOTES and len(set(asked)) == 1, "the votes were not asked one question over the same image"
    _text, images = asked[0]
    assert len(images) == 1 and images[0][:2] == b"\xff\xd8", "the still was not sent as one JPEG block"


def test_a_first_frame_answer_is_the_asked_json_or_no_reading():
    """The judge names every prop by number, visible or not, and an answer that does not account for every
    one exactly once is no reading for any of them, whatever it says about the ones it did name. An entry
    whose own "visible" cannot be read spares the props answered beside it. A code fence is tolerated."""
    c = _gate_module("continuity_gate")
    props = [LAPTOP, PAPER]
    held = {"props": [{"n": 1, "visible": True, "what": "on the desk"}, {"n": 2, "visible": True, "what": "on the floor"}]}
    assert c.read_first_frame(held, props) == (["ok", "ok"], [])
    assert c.answer_of("```json\n" + json.dumps(held) + "\n```") == held
    broke = {"props": [{"n": 1, "visible": False, "what": "not in frame"}, held["props"][1]]}
    states, found = c.read_first_frame(broke, props)
    assert states == ["fail", "ok"] and found == [{"n": 1, "prop": LAPTOP, "what": "not in frame"}], found
    assert c.read_first_frame(None, props) == ([None, None], [])
    assert c.read_first_frame("prose where the object goes", props) == ([None, None], [])
    for bad, why in (([held["props"][0]], "a prop left out"),
                     ([dict(held["props"][0], n=3), held["props"][1]], "a number naming no prop"),
                     ([held["props"][0], held["props"][0]], "the same prop answered twice"),
                     ([dict(held["props"][0], n=True), held["props"][1]], "an n that is not really an int")):
        assert c.read_first_frame({"props": bad}, props)[0] == [None, None], why
    partial = {"props": [{"n": 1, "visible": "yes", "what": "x"}, held["props"][1]]}
    assert c.read_first_frame(partial, props)[0] == [None, "ok"], "one bad entry spared the prop answered beside it"


def test_the_first_frame_command_line_is_read_whole_or_refused():
    """An image and at least one prop are needed, a prop is a line of text, and anything else, an unknown
    flag or a second image included, is refused with the reason before any judge is paid."""
    c = _gate_module("continuity_gate")
    o = c.first_frame_options(["still.jpg", "--prop", " a ceramic mug on the desk ", "--prop", "a closed laptop",
                               "--out", "found.json"])
    assert o == {"image": "still.jpg", "props": ["a ceramic mug on the desk", "a closed laptop"], "out": "found.json"}, o
    for bad in (["still.jpg"], ["still.jpg", "--prop", " "], ["still.jpg", "--prop", "a mug", "other.jpg"],
               ["still.jpg", "--out"], []):
        with pytest.raises(ValueError):
            c.first_frame_options(bad)


def test_the_first_frame_image_is_one_jpeg_block_scaled_like_a_frame(tmp_path):
    """The still reaches the judge as exactly one JPEG, kept at its own size when that already fits the
    grid's own limits, and only ever scaled down, never up, when it does not."""
    c = _gate_module("continuity_gate")
    import io

    from PIL import Image
    small = _still(tmp_path / "small.png")
    data = c.first_frame_image(str(small))
    assert data[:2] == b"\xff\xd8"
    im = Image.open(io.BytesIO(data))
    assert im.size == (64, 48), im.size
    big = tmp_path / "big.png"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=blue:s=3000x2000", "-frames:v", "1", str(big)],
                   check=True, timeout=60)
    im2 = Image.open(io.BytesIO(c.first_frame_image(str(big))))
    assert im2.size[0] * im2.size[1] <= c.GRID_PIXELS and max(im2.size) <= c.GRID_EDGE, im2.size
    assert im2.size[0] < 3000, "a still past the grid's limits was not scaled down"


def test_a_first_frame_check_that_cannot_read_never_pays_a_judge(tmp_path, monkeypatch, capsys):
    """A still that is not there, findings with nowhere to go, or a crash while opening the image all read
    UNREAD and exit 64, each saying why, and none of them pays for a judge call. Named no image or no
    prop, it prints its usage and no verdict."""
    c = _gate_module("continuity_gate")
    monkeypatch.setattr(c, "ask", lambda *a: pytest.fail("a judge was asked with nothing readable"))
    still = _still(tmp_path / "still.png")
    cases = [("a still that is not there", [str(tmp_path / "missing.png"), "--prop", LAPTOP]),
             ("findings with nowhere to go", [str(still), "--prop", LAPTOP,
                                              "--out", str(tmp_path / "no" / "dir" / "found.json")])]
    for label, args in cases:
        assert c.main(["--first-frame", *args]) == 64, label
        said = capsys.readouterr().out.strip().splitlines()
        assert said[-1] == "CONTINUITY_FIRST_FRAME props=0/1 absent=- verdict=UNREAD", label
        assert "continuity: no reading" in said[0], label
    assert c.main(["--first-frame"]) == 64
    said = capsys.readouterr().out
    assert "no image named" in said and "CONTINUITY_FIRST_FRAME" not in said, said

    def died(*args, **kwargs):
        raise RuntimeError("the file is corrupt")
    monkeypatch.setattr(c, "first_frame_image", died)
    assert c.main(["--first-frame", str(still), "--prop", LAPTOP, "--out", str(tmp_path / "died.json")]) == 64
    said = capsys.readouterr().out.strip().splitlines()
    assert said[-1].endswith("verdict=UNREAD") and "the file is corrupt" in said[-2], said


def test_board_probe_holds_props_to_lines_of_plain_words(tmp_path):
    """A spot's props are what the continuity gate holds every shot to, so a malformed list would be a
    question nobody can answer, asked after the spend. None passes, a list of lines passes, and an empty
    list, a blank line, a line that is not text, the same line twice, or a bare string fails."""
    def props(value):
        p = tmp_path / "b.json"
        spot = {"brand": "Acme", "quirk": "a lamp hums", "narration": "It works.", "hook": "a",
                "scenes": {"a": "A warehouse hums. Mouth closed, nobody speaks."}}
        if value is not None:
            spot["props"] = value
        p.write_text(json.dumps({"guard": "Keep the subject in the middle third.", "spots": {"s": spot}}))
        r = run([sys.executable, os.path.join(GATES, "board_probe.py"), str(p), "--json"])
        return json.loads(r.stdout)["spots"]["s"]["checks"]["props"], r.returncode
    assert props(None) == (True, 0)
    assert props([LAPTOP, "a ceramic mug on the desk beside the keyboard"]) == (True, 0)
    for bad in ([], [""], ["  "], [3], ["a mug", "A mug"], LAPTOP, {"laptop": True}):
        assert props(bad) == (False, 1), bad


def test_a_first_frame_prop_most_votes_miss_refuses_the_board_even_with_one_vote_unread():
    """Before any spend a missing prop is refused when most votes miss it and none sees it, so one unreadable
    vote cannot wave through the board that cost six paid takes on the Grok redo."""
    c = _gate_module("continuity_gate")
    assert c.first_frame_tally(["fail", "fail", None]) == "fail"
    assert c.first_frame_tally(["fail", "fail", "fail"]) == "fail"
    assert c.first_frame_tally(["fail", "ok", "fail"]) == "split"
    assert c.first_frame_tally(["fail", None, None]) == "split"
    assert c.first_frame_tally(["ok", "ok", None]) == "ok"
    assert c.first_frame_tally([None, None, "ok"]) is None


# --------------------------------------------------------------------------------------
# frontload_gate.py


def test_frontload_flag_fires_only_past_the_limit():
    """FRONTLOAD_MAX brackets the labelled exemplars in evals/labels.csv: 1.22 is the slowest
    open the author approved and 2.3 is the one sent back, so it flags past itself and not at
    or under it, naming the measured time and the limit."""
    fg = load("frontload_gate.py")
    assert fg.flag(fg.FRONTLOAD_MAX) is None
    assert fg.flag(1.22) is None
    assert fg.flag(0.0) is None
    assert fg.flag(2.3) == "FRONTLOAD: the first big change lands at 2.30s, later than the 1.75s limit. Look before shipping."
    assert fg.flag(fg.FRONTLOAD_MAX + 0.01) is not None


def test_frontload_flag_never_crashes_on_nothing_measured():
    """An empty read is not a late one. A build with no cuts-mode measurement, or a broken one,
    passes None, NaN or a non-number here, and none of them ever flags or raises."""
    fg = load("frontload_gate.py")
    assert fg.flag(None) is None
    assert fg.flag(float("nan")) is None
    assert fg.flag("not a number") is None
    assert fg.flag([]) is None
