"""A person can pass by eye a crowd the cast gate misreads, for the one take they looked at.

The cast gate, gates/cast_gate.py, reads every scene back against the story's character, and fails one
where a second face reads under its floor in two or more of the frames it samples. A crowd of one man
fails that way on his own small, soft copies at the back of the room while his own face matches.
CAST_WAIVER, in pipeline/live.py, is a person's pass by eye on such a take, named by the take's hash.
These tests run that toolkit with every vendor call and repo script replaced by a fake. They check that
the waiver passes strangers alone on the take it names and nothing else, that a re-entry reads a passed
take again rather than paying for another, whichever of the scene's takes it was, and that a new take
never writes over one the run paid for. CAST_WAIVER holds one waiver to a line, so the last five check
that several lines each pass their own take on one pass, that a take two lines name and a line written
any other way are refused and said so, and that a value of one line reads exactly as it did.

Words used below. A spot is one short ad film and its board is the written plan for it, a boards.json
file. A scene is one generated video clip in a spot, a take is one render attempt of it, and a re-roll
sends a scene that came back broken once more. The graph, pipeline/graph.py, is the state machine that
runs a spot through its steps, and it reads each scene from the take at that scene's raw.mp4. A
re-entry runs a stopped run again. The ledger is the append-only log of every vendor request and what
came back. A spot can shoot its scenes as a chain, each from the last frame of the one before.

The fakes and the live fixture are the ones tests/test_live.py uses for the rest of the toolkit that
spends, imported from there rather than copied.
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

from test_live import (  # noqa: E402
    CG,
    NO_FACE,
    SAME,
    Vendor,
    broken,
    cast_state,
    chain_state,
    closer_take,
    held,
    scripts,
    sha,
    started_from,
    takes_and_frames,
)

# A pytest fixture, imported under its own name so pytest finds it in this module too.
from test_live import live as live  # noqa: E402

from pipeline import live as L  # noqa: E402

# A crowd of one man, as the boardroom of copies read: his own face matched at 0.52, and the small,
# soft copies at the back read under the floor as strangers in every frame.
CROWD = (1, CG.line([0.52] * 8, strangers=8))


def test_a_person_can_pass_a_crowd_the_cast_gate_misread_for_that_take_only(live, monkeypatch, tmp_path):
    """A boardroom held about forty copies of one man. His own face matched, and the small, soft copies
    at the back read under the floor in every frame, so the scene failed on strangers. A person who
    looked passed that take by eye. The waiver names the take by its hash, so a re-entry reads that take
    again instead of paying for another and passes it beside the refused reading, and the next take the
    engine draws is never passed by it."""
    tk, state = live
    monkeypatch.setenv("CLOSER_FROM", str(closer_take(tmp_path)))
    takes_and_frames(monkeypatch)
    vendor = Vendor()
    monkeypatch.setattr(L, "http", vendor)
    monkeypatch.setattr(L.LiveToolkit, "script", scripts(cast=lambda clip: CROWD if "zai-a" in clip else SAME))
    first = tk.render(cast_state(state))
    assert first["failed"] == ["a"] and first["why"]["a"].startswith("a second person on screen"), first
    digest = L.sha256(os.path.join(tk.takes, "zai-a", "raw.mp4"))
    paid = [r["request_id"] for r in tk.ledger.rows() if r["kind"] == "request" and r.get("scene") == "zai-a"]
    monkeypatch.setenv("CAST_WAIVER", f"{digest[:12]}:author:the back row is the same man, small and soft")
    posts = len(vendor.posts())
    again = L.LiveToolkit(state["run_dir"], tk.ledger.run_id).render(dict(cast_state(state), verdict={"render": first}))
    assert again["failed"] == [] and again["fresh"] == [] and len(vendor.posts()) == posts, "the waived take was paid for again"
    rows = tk.ledger.rows()
    cast = [r for r in rows if r.get("scene") == "zai-a" and str(r.get("check", "")).startswith("cast")]
    assert cast[-2]["check"] == "cast" and cast[-2]["passed"] is False and "strangers=8" in cast[-2]["reading"], cast[-2]
    waived = cast[-1]
    assert waived["check"] == "cast waived by a person" and waived["passed"] is True, waived
    assert (waived["waived_by"], waived["waiver"]) == ("author", "the back row is the same man, small and soft"), waived
    assert waived["sha256"] == digest and waived["reading"] == cast[-2]["reading"] and waived["against"] == "character"
    reused = [(r["request_id"], r["sha256"]) for r in rows if r.get("status") == "REUSED" and r.get("scene") == "zai-a"]
    assert reused == [(paid[0], digest)], reused
    assert [r["sha256"] for r in rows if r.get("check") == "continuity" and r.get("scene") == "zai-a"] == [digest], \
        "the waived take was never read for continuity"
    # A person who sends the scene back gets a new take, and the waiver for the old one does not pass it.
    sent = tk.render(dict(cast_state(state), verdict={"render": again}, changes={"scene": "a", "reason": "a new crowd"}))
    assert sent["failed"] == ["a"] and sent["fresh"] == ["a"] and len(vendor.posts()) == posts + 1, \
        "the waiver carried over to another take"


def test_a_cast_waiver_passes_strangers_alone_and_nothing_else(live, monkeypatch):
    """The waiver is for faces the gate reads as strangers beside a main face it matched, on the one take
    it names. It never passes another take's hash, a prefix too short to name one, a waiver that names
    nobody, a main face under the floor, a scene that reads at least as close to the narrator as to the
    character, or a scene where the gate found no face or gave no reading, which stay with the eye."""
    tk, _ = live
    raw = os.path.join(tk.dir("zai-a"), "raw.mp4")
    open(raw, "wb").write(b"a boardroom of one man")
    digest = L.sha256(raw)
    refs = {"character": "her.jpg", "presenter": "narrator.jpg"}
    ok = f"{digest[:12]}:author:the back row is the same man"
    fail = ((CROWD, f"{'0' * 12}:author:passed by eye", "a waiver for another take passed this one"),
            (CROWD, f"{digest[:11]}:author:passed by eye", "a waiver naming too little of the hash passed"),
            (CROWD, f"{digest[:12]}: : ", "a waiver naming nobody and no reason passed"),
            ((1, CG.line([0.24] * 8, strangers=8)), ok, "a main face under the floor was waived"),
            ((1, CG.line([0.40] * 8, strangers=3, others=[0.53] * 8)), ok, "a scene nearer the narrator was waived"))
    look = ((NO_FACE, "no face found"), ((64, "CAST_GATE unreadable: no frame could be read from the scene"), "could not read"))
    for answer, waiver, why in fail + tuple((answer, ok, f"{said} was waived") for answer, said in look):
        monkeypatch.setattr(L.LiveToolkit, "script", scripts(cast=answer))
        monkeypatch.setenv("CAST_WAIVER", waiver)
        failed, said, flags = [], {}, {}
        tk.cast_check("zai", "a", raw, refs, failed, said, flags)
        assert failed == ["a"] or "a" in flags, why
    assert not [r for r in tk.ledger.rows() if r.get("check") == "cast waived by a person"], "a waiver passed what it may not"
    assert [r["passed"] for r in tk.ledger.rows() if r.get("check") == "cast"] == [False] * 7
    monkeypatch.setattr(L.LiveToolkit, "script", scripts(cast=CROWD))
    failed, said, flags = [], {}, {}
    tk.cast_check("zai", "a", raw, refs, failed, said, flags)
    assert failed == [] and said == {} and flags == {}, (failed, said, flags)
    assert [r["sha256"] for r in tk.ledger.rows() if r.get("check") == "cast waived by a person"] == [digest]


def test_a_take_a_person_passed_is_read_again_on_a_re_entry_whichever_take_it_was(live, monkeypatch, tmp_path):
    """The crowd failed on its take and on its re-roll, and the person who looked passed the first take.
    The re-roll kept that take beside the scene under its hash rather than writing over it, and the
    person put it back where the graph reads the scene. A re-entry reads that take again and pays for
    nothing, and its reuse names the request that paid for it. With the waiver unset, the take fails its
    reading again and nothing is sent to replace it, since only a person's ask renders over a take a
    person passed. A file this run never landed for the scene is never brought in by a waiver."""
    tk, state = live
    monkeypatch.setenv("CLOSER_FROM", str(closer_take(tmp_path)))
    takes_and_frames(monkeypatch)
    vendor = Vendor()
    monkeypatch.setattr(L, "http", vendor)
    monkeypatch.setattr(L.LiveToolkit, "script", scripts(cast=lambda clip: CROWD if "zai-a" in clip else SAME))
    first = tk.render(cast_state(state))
    raw = os.path.join(tk.takes, "zai-a", "raw.mp4")
    take1 = open(raw, "rb").read()
    second = tk.render(dict(cast_state(state), verdict={"render": first}))
    assert second["failed"] == ["a"] and open(raw, "rb").read() != take1 and len(vendor.posts()) == 4, second
    kept = os.path.join(tk.takes, "zai-a", f"take-{sha(take1)}.mp4")
    assert open(kept, "rb").read() == take1, "the re-roll wrote over a take this run paid for"
    os.replace(raw, os.path.join(tk.takes, "zai-a", f"take-{L.sha256(raw)}.mp4"))
    os.replace(kept, raw)
    digest = L.sha256(raw)
    monkeypatch.setenv("CAST_WAIVER", f"{digest[:12]}:author:the back row is the same man")
    again = L.LiveToolkit(state["run_dir"], tk.ledger.run_id).render(dict(cast_state(state), verdict={"render": second}))
    assert again["failed"] == [] and len(vendor.posts()) == 4, "a take a person passed was paid for again"
    paid = [r["request_id"] for r in tk.ledger.rows() if r["kind"] == "request" and r.get("scene") == "zai-a"]
    reused = [(r["request_id"], r["sha256"]) for r in tk.ledger.rows() if r.get("status") == "REUSED" and r.get("scene") == "zai-a"]
    assert len(paid) == 2 and reused == [(paid[0], digest)], (paid, reused)
    monkeypatch.delenv("CAST_WAIVER")
    stopped = L.LiveToolkit(state["run_dir"], tk.ledger.run_id).render(dict(cast_state(state), verdict={"render": second}))
    assert stopped["failed"] == ["a"] and len(vendor.posts()) == 4, "a take a person passed was rendered over"
    assert stopped["why"]["a"].endswith("A person passed this take by eye before, and CAST_WAIVER no longer names it")
    open(raw, "wb").write(b"a take from another run")
    monkeypatch.setenv("CAST_WAIVER", f"{L.sha256(raw)[:12]}:author:passed by eye")
    elsewhere = tk.render(dict(cast_state(state), verdict={"render": second}))
    assert elsewhere["fresh"] == ["a"] and len(vendor.posts()) == 5, "a file this run never landed was brought in by a waiver"


def test_a_cast_waiver_never_brings_back_a_take_the_continuity_judge_failed(live, monkeypatch, tmp_path):
    """The waiver passes a cast reading and nothing else. A take the continuity judge failed is rendered
    again even when a waiver names it, rather than read again until the judge says something else."""
    tk, state = live
    monkeypatch.setenv("CLOSER_FROM", str(closer_take(tmp_path)))
    takes_and_frames(monkeypatch)
    vendor = Vendor()
    monkeypatch.setattr(L, "http", vendor)
    monkeypatch.setattr(L.LiveToolkit, "script", scripts(continuity=lambda args: broken() if "zai-a" in args[0] else held(args)))
    first = tk.render(cast_state(state))
    assert first["failed"] == ["a"] and len(vendor.posts()) == 3, first
    monkeypatch.setenv("CAST_WAIVER", f"{L.sha256(os.path.join(tk.takes, 'zai-a', 'raw.mp4'))[:12]}:author:passed by eye")
    again = tk.render(dict(cast_state(state), verdict={"render": first}))
    assert again["fresh"] == ["a"] and len(vendor.posts()) == 4, "a take the continuity judge failed was brought back"
    assert not [r for r in tk.ledger.rows() if r.get("status") == "REUSED"], again


def test_a_chained_take_a_person_passed_is_read_again_and_the_chain_goes_on_from_it(live, monkeypatch, tmp_path):
    """A chain stops at a crowd the cast gate misread. Once a person passes that take by eye, a re-entry
    reads it again instead of paying for it, and the scenes after it start from its last frame."""
    tk, state = live
    monkeypatch.setenv("CLOSER_FROM", str(closer_take(tmp_path)))
    takes_and_frames(monkeypatch)
    sent = []
    vendor = Vendor(on_post=lambda url, body: sent.append(json.loads(body)) if "queue" in url else None)
    monkeypatch.setattr(L, "http", vendor)
    monkeypatch.setattr(L.LiveToolkit, "script", scripts(cast=lambda clip: CROWD if "zai-a" in clip else SAME))
    first = tk.render(chain_state(state))
    assert first["failed"] == ["a"] and len(vendor.posts()) == 1, first
    monkeypatch.setenv("CAST_WAIVER", f"{sha(b'take 1')[:12]}:author:the back row is the same man")
    again = tk.render(chain_state(state, verdict={"render": first}))
    assert again["failed"] == [] and again["fresh"] == ["b", "c"] and len(vendor.posts()) == 3, again
    assert started_from(sent[1:]) == [b"last frame of take 1", b"last frame of take 2"], "the chain left the passed take"
    assert [r["scene"] for r in tk.ledger.rows() if r.get("status") == "REUSED"] == ["zai-a"]


# Several waivers, one to a line.

# A main face the reference missed, under the gate's floor, which no pass by eye may cover.
MISSED = (1, CG.line([0.24] * 8, strangers=8))


def crowds(live, monkeypatch, tmp_path, readings=None):
    """A first pass where scenes a and b are crowds the cast gate misread, and c passes, unless `readings`
    says otherwise for a scene. Returns the toolkit, the state, the vendor, the first verdict, and each
    scene's take by its sha256."""
    tk, state = live
    monkeypatch.setenv("CLOSER_FROM", str(closer_take(tmp_path)))
    takes_and_frames(monkeypatch)
    vendor = Vendor()
    monkeypatch.setattr(L, "http", vendor)
    read = {"zai-a": CROWD, "zai-b": CROWD, **(readings or {})}
    monkeypatch.setattr(L.LiveToolkit, "script", scripts(cast=lambda clip: next((v for k, v in read.items() if k in clip), SAME)))
    first = tk.render(cast_state(state))
    takes = {s: L.sha256(os.path.join(tk.takes, f"zai-{s}", "raw.mp4")) for s in "abc"}
    return tk, state, vendor, first, takes


def re_enter(tk, state, first):
    return L.LiveToolkit(state["run_dir"], tk.ledger.run_id).render(dict(cast_state(state), verdict={"render": first}))


def passed_by(tk):
    return {r["scene"]: (r["sha256"], r["waived_by"], r["waiver"]) for r in tk.ledger.rows()
            if r.get("check") == "cast waived by a person"}


def test_two_waivers_one_to_a_line_pass_two_crowds_on_one_pass(live, monkeypatch, tmp_path):
    """Two scenes of the boardroom failed on the copies at the back, and the person who looked passed both.
    CAST_WAIVER carries a line for each, so one re-entry reads both takes again, pays for neither, and
    writes a row beside each refused reading naming that take, who passed it and why."""
    tk, state, vendor, first, takes = crowds(live, monkeypatch, tmp_path)
    assert first["failed"] == ["a", "b"], first
    posts = len(vendor.posts())
    monkeypatch.setenv("CAST_WAIVER", f"{takes['a'][:12]}:author:the back row is the same man\n"
                                      f"{takes['b'][:16]}:editor:the bowing copy is the same man\n")
    again = re_enter(tk, state, first)
    assert again["failed"] == [] and again["fresh"] == [] and len(vendor.posts()) == posts, again
    assert passed_by(tk) == {"zai-a": (takes["a"], "author", "the back row is the same man"),
                             "zai-b": (takes["b"], "editor", "the bowing copy is the same man")}, passed_by(tk)
    reused = {r["scene"]: r["sha256"] for r in tk.ledger.rows() if r.get("status") == "REUSED"}
    assert reused == {"zai-a": takes["a"], "zai-b": takes["b"]}, reused


def test_one_waiver_holds_while_the_other_is_refused(live, monkeypatch, tmp_path):
    """Both lines are well formed, but the second names a take whose main face missed the reference, which
    no pass by eye may cover. Each line meets the conditions a single waiver does, on its own take, so
    the first take passes and the second fails as it did, read again rather than shot again, with no row
    saying anyone passed it."""
    tk, state, vendor, first, takes = crowds(live, monkeypatch, tmp_path, {"zai-b": MISSED})
    assert first["failed"] == ["a", "b"], first
    posts = len(vendor.posts())
    monkeypatch.setenv("CAST_WAIVER", f"{takes['a'][:12]}:author:the back row is the same man\n"
                                      f"{takes['b'][:12]}:author:passed by eye")
    again = re_enter(tk, state, first)
    assert again["failed"] == ["b"] and again["fresh"] == [] and len(vendor.posts()) == posts, again
    assert again["why"]["b"] == first["why"]["b"], again["why"]
    assert passed_by(tk) == {"zai-a": (takes["a"], "author", "the back row is the same man")}, passed_by(tk)


def test_a_take_two_lines_name_is_passed_by_neither_and_the_run_says_so(live, monkeypatch, tmp_path):
    """Two lines name the first crowd's take by the same prefix, with different people and reasons.
    Picking one would be a guess, so neither passes it, while the third line still passes its own take.
    The take two lines name is read again rather than paid for again and fails as it did. The refused
    reading stays on the ledger with no row beside it, the reason it failed names both lines, and that
    reason is on the ledger once the run closes. A longer prefix of the same hash names the take too."""
    tk, state, vendor, first, takes = crowds(live, monkeypatch, tmp_path)
    posts = len(vendor.posts())
    monkeypatch.setenv("CAST_WAIVER", f"{takes['a'][:12]}:author:the back row is the same man\n"
                                      f"{takes['a'][:12]}:editor:the copies at the back look down\n"
                                      f"{takes['b'][:12]}:author:the bowing copy is the same man")
    again = re_enter(tk, state, first)
    assert again["failed"] == ["a"] and again["fresh"] == [] and len(vendor.posts()) == posts, again
    assert again["why"]["a"] == first["why"]["a"] + ". CAST_WAIVER names this take on lines 1 and 2, so none of them passes it"
    assert passed_by(tk) == {"zai-b": (takes["b"], "author", "the bowing copy is the same man")}, passed_by(tk)
    refused = [r for r in tk.ledger.rows() if r.get("scene") == "zai-a" and str(r.get("check", "")).startswith("cast")][-1]
    assert refused["check"] == "cast" and refused["passed"] is False and "strangers=8" in refused["reading"], refused
    tk.close(dict(cast_state(state), trail=["board", "render"], verdict={"render": again}))
    closed = [r for r in tk.ledger.rows() if r["kind"] == "close"][-1]
    assert closed["because"]["why"]["a"] == again["why"]["a"], closed
    monkeypatch.setenv("CAST_WAIVER", f"{takes['a'][:12]}:author:passed by eye\n{takes['a'][:20]}:author:passed by eye")
    assert tk.cast_waiver(takes["a"]) == ({}, [1, 2], []), "a longer prefix of the same take was not read as naming it"


def test_a_line_written_any_other_way_passes_nothing_and_holds_a_crowd_it_may_be_for(live, monkeypatch, tmp_path):
    """The second line was meant for the second crowd but names too little of its hash, and the fourth is
    no waiver at all. The first line still passes its take. Nothing guesses which take the others meant,
    so neither passes anything. The crowd still failing is read again rather than shot again, since a line
    meant for it may be among them, and the reason it failed names both lines. A scene whose main face
    missed is no crowd, so no line could have been for it, and it is shot again as before."""
    tk, state, vendor, first, takes = crowds(live, monkeypatch, tmp_path, {"zai-c": MISSED})
    assert first["failed"] == ["a", "b", "c"], first
    posts = len(vendor.posts())
    monkeypatch.setenv("CAST_WAIVER", f"{takes['a'][:12]}:author:the back row is the same man\n"
                                      f"{takes['b'][:11]}:author:the bowing copy is the same man\n\n"
                                      "passed by eye\n")
    again = re_enter(tk, state, first)
    assert again["failed"] == ["b", "c"] and again["fresh"] == ["c"] and len(vendor.posts()) == posts + 1, again
    assert again["why"]["b"] == first["why"]["b"] + (". Nothing on CAST_WAIVER's lines 2 and 4 passes a take, since a waiver "
                                                     "is written <sha256 prefix>:<who>:<why>"), again["why"]
    assert passed_by(tk) == {"zai-a": (takes["a"], "author", "the back row is the same man")}, passed_by(tk)
    reused = [r["scene"] for r in tk.ledger.rows() if r.get("status") == "REUSED"]
    assert sorted(reused) == ["zai-a", "zai-b"], reused


def test_a_value_of_one_line_reads_exactly_as_it_did(live, monkeypatch):
    """Every value a single waiver was read from before reads the same now, newlines around it and a
    carriage return included, and every value that held no waiver still holds none and passes nothing.
    The reading of one line is checked against the parse it replaced, written out here as it stood."""
    tk, _ = live
    raw = os.path.join(tk.dir("zai-a"), "raw.mp4")
    open(raw, "wb").write(b"a boardroom of one man")
    digest = L.sha256(raw)

    def before(value):
        m = L.WAIVER.fullmatch(value.strip())
        if not m or not m.group(2).strip() or not m.group(3).strip() or not digest.startswith(m.group(1)):
            return {}
        return {"waived_by": m.group(2).strip(), "waiver": m.group(3).strip()}

    values = (f"{digest[:12]}:author:the back row is the same man", f"\n  {digest[:12]}:author:the back row\r\n",
              f"{digest}:author:the whole hash", f"{digest[:12]}:author:a reason: with a colon in it",
              f"{digest[:12]}:author:a reason\u2028that runs on", f"{digest[:11]}:author:too little of the hash",
              f"{digest[:12].upper()}:author:capitals", f"{digest[:12]}: : ", f"{digest[:12]}:author:",
              f"{digest[:12]}::no one named", f"{'0' * 12}:author:another take", f"{digest[:12]} author passed by eye", "")
    now = []
    for v in values:
        monkeypatch.setenv("CAST_WAIVER", v)
        now.append(tk.cast_waiver(digest)[0])
    assert now == [before(v) for v in values], now
    assert sum(1 for v in values if before(v)) == 5, "the values that held a waiver before are no longer the ones checked"
    monkeypatch.setattr(L.LiveToolkit, "script", scripts(cast=CROWD))
    refs = {"character": "her.jpg", "presenter": "narrator.jpg"}
    monkeypatch.setenv("CAST_WAIVER", f"{digest[:12]}:author:the back row is the same man")
    failed, why, flags = [], {}, {}
    tk.cast_check("zai", "a", raw, refs, failed, why, flags)
    assert (failed, why, flags) == ([], {}, {}), (failed, why, flags)
    assert passed_by(tk) == {"zai-a": (digest, "author", "the back row is the same man")}, passed_by(tk)
