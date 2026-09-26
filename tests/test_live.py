"""The toolkit that spends, tested without spending.

pipeline/live.py is the only code in the repo that reaches a vendor, so its promises are
checked here with every vendor call and every repo script replaced by a fake. A request goes on
the ledger before it is sent. A rejection is recorded with the vendor's own text. No identity
id or local path reaches a ledger that gets committed, whatever a script prints. Nothing is
spent until everything a run needs is present. A run re-entered after a failure collects what
it already paid for instead of paying again. The closer's guards run before anything is paid,
the voice included. A reused closer must say this spot's line. A scene that shows the story's
character is rendered from her face and read back against it, and never passes as the narrator.
And the gates' exits and
machine lines become the causes the graph routes on. Several tests exist because a mutation of
the code they name survived the suite.
"""
import hashlib
import importlib.util
import json
import os
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from pipeline import live as L  # noqa: E402

REAL_GUARD = L.LiveToolkit.guard
BOARD = os.path.join(ROOT, "shoots", "ads8-real", "boards.json")
VOICE = "VOICEIDXYZ1234567890"  # pii-allow: a made-up id
LOOK = "LOOKID0123456789ABCDEF"
PINNED = "PINNEDAVATAR99887766"  # pii-allow: a made-up id
GROUP = "GROUPID5566778899"
NAME = "a-long-voice-name-v7"
CLOSER = json.load(open(BOARD))["spots"]["zai"]["closer"]
CAST_BOARD = os.path.join(ROOT, "shoots", "graph-zai-character", "boards.json")
REF_ENGINE = "google/gemini-omni-flash/reference-to-video"


def _cast_gate():
    spec = importlib.util.spec_from_file_location("cast_gate", os.path.join(ROOT, "gates", "cast_gate.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# The cast gate's own line format, so a stub cannot drift from what the gate prints.
CG = _cast_gate()
SAME = (0, CG.line([0.46, 0.44, 0.48]))
OTHER = (1, CG.line([0.06, 0.04, 0.05]))
NO_FACE = (3, CG.line([]))
# The character's reference read against the narrator's: someone else, as the Z.ai girl is (0.15).
APART = (1, CG.line([0.15]))


def done(code=0, out="", err=""):
    return subprocess.CompletedProcess([], code, out, err)


class Vendor:
    """Answers the fal queue, speech-to-text and HeyGen, and records every call. A test can
    make a result fetch reject, a status poll fail on the network or kill the process, or
    check the ledger at the moment of a POST."""

    def __init__(self, reject=(), on_post=None, net_fail=0, heygen_status="completed", die_on_status=False, locked=(), empty=(),
                 dropped=(),
                 post_fail=(), post_noid=()):
        self.calls, self.reject, self.on_post, self.locked, self.empty = [], set(reject), on_post, set(locked), set(empty)
        self.dropped = set(dropped)     # jobs the vendor no longer has, by id
        self.net_fail, self.heygen_status, self.die_on_status = net_fail, heygen_status, die_on_status
        self.post_fail, self.post_noid = set(post_fail), set(post_noid)   # which queue POSTs, by count, go wrong

    def __call__(self, method, url, headers, body=None, timeout=120):
        self.calls.append((method, url))
        if method == "POST" and self.on_post:
            self.on_post(url, body)
        if url.endswith("/speech-to-text"):
            return 200, json.dumps({"text": "read back", "words": []}).encode()
        if "heygen" in url:
            if url.endswith("/v3/assets"):
                return 200, b'{"data": {"asset_id": "asset1"}}'
            if url.endswith("/v3/videos"):
                if "closer" in self.post_fail:
                    return 0, b"TimeoutError: The read operation timed out"
                return 200, b'{"data": {"video_id": "vid1"}}'
            return 200, json.dumps({"data": {"status": self.heygen_status, "video_url": "https://files/c.mp4"}}).encode()
        if method == "POST":
            n = sum(1 for m, u in self.calls if m == "POST" and "queue" in u)
            if n in self.post_fail:
                return 0, b"TimeoutError: The read operation timed out"
            if n in self.post_noid:
                return 200, b"{}"
            rid = f"fal-{n}"
            return 200, json.dumps({"request_id": rid, "status_url": f"https://queue/{rid}/status",
                                    "response_url": f"https://queue/{rid}"}).encode()
        if url.endswith("/status") and url.split("/")[-2] in self.dropped:
            return 404, b'{"status": "NOT_FOUND"}'
        if url.endswith("/status"):
            if self.die_on_status:
                raise KeyboardInterrupt("the process died mid-poll")
            if self.net_fail:
                self.net_fail -= 1
                return 0, b"URLError: <urlopen error [Errno 8] nodename nor servname provided>"
            return 200, b'{"status": "COMPLETED"}'
        if url.rsplit("/", 1)[-1] in self.dropped:
            return 404, b'{"detail": "Request not found"}'
        if url.rsplit("/", 1)[-1] in self.empty:
            return 200, b'{"video": null}'
        if url.rsplit("/", 1)[-1] in self.locked:
            return 403, b'{"detail": "User is locked. Reason: TOP_UP."}'
        if url.rsplit("/", 1)[-1] in self.reject:
            return 422, b'{"detail": "Output video has sensitive content"}'
        return 200, json.dumps({"video": {"url": "https://files/x.mp4"}}).encode()

    def posts(self):
        return [u for m, u in self.calls if m == "POST" and "queue" in u]


def scripts(voice_ok=True, jaw=(0, "JAW_GATE jaw=0.11 face_cov=1.0 max=0.17 verdict=PASS"), ship=(0, "SHIP-GATE PASS"),
            loud=(0, "LOUDNESS_GATE i=-16.0 tp=-2.0 verdict=PASS"), gates=None, build=None, edge=(0, "EDGE CLEAN"),
            match=(0, "SCRIPT-MATCH PASS"), cast=SAME, reference_ok=True, distinct=APART):
    """Stand-ins for the repo scripts the toolkit runs, keyed on the script's path. `cast` is
    one (exit, line) for every clip, or a function of the clip's path returning one. `distinct`
    answers the read of the character's reference against the narrator's. A read asked for a
    second face gets one, the narrator somewhere else (0.10), unless the answer already names it."""
    seen = []

    def run(self, *args, env=None, drop=(), timeout=1800, python=None):
        seen.append((args, env or {}, drop, python))
        name = args[0]
        if name == "gates/cast_gate.py":
            if args[1] == "--reference":
                if not reference_ok:
                    return done(64, "CAST_REFERENCE none: no face in the source")
                face = b"a presenter's face"
                if "character" in args[3]:
                    face = b"the character's face" + (b"" if os.path.basename(args[2]) == "character.jpg"
                                                      else b" from " + os.path.basename(args[2]).encode())
                open(args[3], "wb").write(face)
                return done(0, "CAST_REFERENCE face=0.91")
            if args[2].endswith(os.path.join("-character", "reference.jpg")) and "--not" not in args:
                return done(*distinct)
            code, out = cast(args[2]) if callable(cast) else cast
            if "--not" in args and " not=-" in out:
                out = out.replace(" not=-", " not=nan" if "faces=0 " in out else " not=0.10")
            return done(code, out)
        if name == "gates/voice_take.sh":
            if not voice_ok:
                return done(1, "draws disagreed")
            open(args[2], "wb").write(b"mp3")
            return done(0, f"SURVIVOR: {args[2]}\n")
        if name == "gates/script_match.sh":
            return done(*match)
        if name == "gates/edge_clip_probe.py":
            return done(*edge)
        if name == "gates/jaw_gate.py":
            return done(*jaw)
        if name == "guards/ship_gate.sh":
            return done(*ship)
        if name == "gates/loudness_gate.py":
            return done(*loud)
        if name == "gates/ad_gates.sh":
            return done(*(gates or (0, "MOUTH SYNC PASS: corr 0.43 at lag +0.04s\n"
                                       "AD_GATES_RESULT caption=pass drift=pass mouth=pass")))
        if name == "shoots/build-ad.sh":
            if build:
                return build(self, args, env)
            out = os.path.join(env["TAKES"], f"out-{args[1]}-{args[2]}")
            os.makedirs(out, exist_ok=True)
            open(os.path.join(out, "ad.mp4"), "wb").write(b"ad")
            return done(0, f"built {out}/ad.mp4\n")
        if name == "shoots/master.sh":
            open(args[2], "wb").write(b"master")
            return done(0, "")
        return done(0, "")
    run.seen = seen
    return run


def calls_to(run, name):
    return [s for s in run.seen if s[0][0] == name]


@pytest.fixture
def live(tmp_path, monkeypatch):
    pins = tmp_path / "pins.json"
    pins.write_text(json.dumps({"voice_id": VOICE, "voice_name": NAME, "avatar_id": PINNED, "avatar_group_id": GROUP}))
    bed = tmp_path / "bed.mp3"
    bed.write_bytes(b"bed")
    film2 = tmp_path / "film2"
    film2.mkdir()
    still = tmp_path / "still.jpg"
    still.write_bytes(b"a presenter's still")
    her = tmp_path / "character.jpg"
    her.write_bytes(b"the character's still")
    for k, v in {"FAL_KEY": "k", "ELEVENLABS_API_KEY": "k", "ELEVENLABS_VOICE_ID": VOICE, "IDENTITY_PINS": str(pins),
                 "BED": str(bed), "FILM2": str(film2), "HEYGEN_API_KEY": "k", "CLOSER_LOOK_ID": LOOK,
                 "PRESENTER_STILL": str(still), "CHARACTER_FROM": str(her)}.items():
        monkeypatch.setenv(k, v)
    monkeypatch.delenv("CLOSER_FROM", raising=False)
    monkeypatch.setattr(L.time, "sleep", lambda s: None)
    monkeypatch.setattr(L, "duration", lambda p: 5.0)
    monkeypatch.setattr(L, "frame_size", lambda p: (1280, 720))
    monkeypatch.setattr(L.urllib.request, "urlretrieve", lambda url, path: open(path, "wb").write(b"video"))
    monkeypatch.setattr(L.LiveToolkit, "guard", lambda self, name, payload: (0, ""))
    run_dir = tmp_path / "run"
    return L.LiveToolkit(str(run_dir)), {"board": BOARD, "spot": "zai", "run_dir": str(run_dir),
                                         "attempts": {}, "verdict": {}, "artifacts": {}, "changes": {}}


def ledger_text(tk):
    return open(tk.ledger.path).read()


# setup

@pytest.mark.parametrize("missing", ["FAL_KEY", "ELEVENLABS_VOICE_ID", "IDENTITY_PINS", "BED", "FILM2", "HEYGEN_API_KEY"])
def test_nothing_starts_without_what_the_run_needs(live, monkeypatch, tmp_path, missing):
    monkeypatch.delenv(missing)
    with pytest.raises(L.LiveSetupError):
        L.LiveToolkit(str(tmp_path / "another"))
    assert not (tmp_path / "another").exists(), "a run started before its setup was checked"


def test_a_reused_closer_needs_no_heygen_key(live, monkeypatch, tmp_path):
    monkeypatch.delenv("HEYGEN_API_KEY")
    monkeypatch.delenv("CLOSER_LOOK_ID")
    monkeypatch.setenv("CLOSER_FROM", str(tmp_path))
    L.LiveToolkit(str(tmp_path / "another"))


def test_nothing_is_spent_on_a_voice_without_a_pin_file(live, monkeypatch):
    tk, state = live
    monkeypatch.setenv("IDENTITY_PINS", "/nonexistent/pins.json")
    with pytest.raises(L.LiveSetupError):
        L.LiveToolkit(state["run_dir"])


def test_an_engine_with_no_recorded_shape_is_refused_before_any_request(live, monkeypatch, tmp_path):
    tk, state = live
    board = json.load(open(BOARD))
    board["spots"]["zai"]["engine"] = "someone/unknown-engine"
    path = tmp_path / "board.json"
    path.write_text(json.dumps(board))
    vendor = Vendor()
    monkeypatch.setattr(L, "http", vendor)
    with pytest.raises(L.LiveSetupError):
        tk.render(dict(state, board=str(path)))
    assert not vendor.calls


# render

def test_a_request_is_on_the_ledger_before_it_is_sent_and_its_landing_shares_its_id(live, monkeypatch):
    tk, state = live
    before = []
    vendor = Vendor(on_post=lambda url, body: before.append(tk.ledger.rows()[-1]))
    monkeypatch.setattr(L, "http", vendor)
    monkeypatch.setattr(L.LiveToolkit, "script", scripts())
    tk.render(state)
    scene_posts = [r for r in before if r.get("engine") == "google/gemini-omni-flash"]
    assert len(scene_posts) == 3 and all(r["kind"] == "request" for r in scene_posts), before
    rows = tk.ledger.rows()
    asked = {r["request_id"] for r in rows if r["kind"] == "request"}
    landed = {r["request_id"] for r in rows if r["kind"] == "landing" and "request_id" in r}
    assert asked == landed and all(i.startswith("req_") for i in asked), (asked, landed)
    queued = [r for r in rows if r["kind"] == "queued"]
    assert len(queued) == 3 and all(r["vendor_id"].startswith("fal-") for r in queued), "a vendor id was not kept"


def test_a_rejected_render_is_recorded_with_the_vendors_words_and_counted_as_broken(live, monkeypatch):
    tk, state = live
    monkeypatch.setattr(L, "http", Vendor(reject={"fal-2"}))
    monkeypatch.setattr(L.LiveToolkit, "script", scripts())
    v = tk.render(state)
    assert v["failed"] == ["b"], v
    rejected = [r for r in tk.ledger.rows() if r.get("status") == "REJECTED"]
    assert len(rejected) == 1 and "sensitive content" in rejected[0]["error"]


def test_a_network_failure_mid_poll_is_one_more_poll_not_an_exception(live, monkeypatch):
    """A dropped connection used to raise out of the poll and lose the paid request's id with
    it. Now it is one more poll, and the scene lands."""
    tk, state = live
    monkeypatch.setattr(L, "http", Vendor(net_fail=2))
    monkeypatch.setattr(L.LiveToolkit, "script", scripts())
    v = tk.render(state)
    assert v["failed"] == [], v


def test_a_real_urlerror_comes_back_as_status_zero(monkeypatch):
    def boom(req, timeout):
        raise L.urllib.error.URLError("no route")
    monkeypatch.setattr(L.urllib.request, "urlopen", boom)
    code, data = L.http("GET", "https://queue.example/x", {})
    assert code == 0 and b"no route" in data


def test_a_re_entry_collects_a_request_it_already_sent_instead_of_paying_again(live, monkeypatch):
    """The first pass died after the POSTs. Re-entered, the render polls the queued requests
    and pays for nothing new."""
    tk, state = live
    vendor = Vendor(die_on_status=True)
    monkeypatch.setattr(L, "http", vendor)
    monkeypatch.setattr(L.LiveToolkit, "script", scripts())
    with pytest.raises(KeyboardInterrupt):
        tk.render(state)
    posts = len(vendor.posts())
    assert posts == 3
    vendor.die_on_status = False
    v = L.LiveToolkit(state["run_dir"], tk.ledger.run_id).render(state)
    assert v["failed"] == [] and len(vendor.posts()) == posts, "the re-entry sent the scenes again"


def test_a_re_entry_reuses_scenes_it_already_holds(live, monkeypatch):
    tk, state = live
    vendor = Vendor()
    monkeypatch.setattr(L, "http", vendor)
    run = scripts()
    monkeypatch.setattr(L.LiveToolkit, "script", run)
    assert tk.render(state)["fresh"] == ["a", "b", "c"]
    posts, voices = len(vendor.posts()), len(calls_to(run, "gates/voice_take.sh"))
    v = L.LiveToolkit(state["run_dir"], tk.ledger.run_id).render(state)
    assert v["failed"] == [] and len(vendor.posts()) == posts, "a scene this run holds was paid for again"
    assert v["fresh"] == [], "a take reused as it stood was reported as a new picture"
    assert len(calls_to(run, "gates/voice_take.sh")) == voices, "the narration was redrawn"
    assert len([r for r in tk.ledger.rows() if r.get("status") == "REUSED"]) == 3


def test_a_request_the_vendor_never_confirmed_is_not_sent_again_until_a_person_re_enters(live, monkeypatch):
    """A POST that failed on the network may still have been taken and billed. It stops the scene
    for a person, the next pass does not send it again, and only a re-entry, a person's call made
    after looking at the vendor's queue, sends it once more."""
    tk, state = live
    vendor = Vendor(post_fail={2})
    monkeypatch.setattr(L, "http", vendor)
    run = scripts()
    monkeypatch.setattr(L.LiveToolkit, "script", run)
    v = tk.render(state)
    assert v["unconfirmed"] == ["b"] and v["failed"] == [], v
    # Nothing new is paid for after it: scene c is not sent and the narration is not drawn.
    assert len(vendor.posts()) == 2 and "not sent" in v["why"]["c"], (vendor.posts(), v["why"])
    assert not calls_to(run, "gates/voice_take.sh"), "the narration was paid for behind an unconfirmed request"
    assert [r["status"] for r in tk.ledger.rows() if r["kind"] == "landing" and r.get("request_id")][:1] == ["UNCONFIRMED"]
    posts = len(vendor.posts())
    again = tk.render(dict(state, verdict={"render": v}))
    assert again["unconfirmed"] == ["b"] and len(vendor.posts()) == posts, "an unconfirmed request was sent again"
    tk.ledger.append("resumed", "render", reason="checked the queue, nothing there", trail=[])
    vendor.post_fail = set()
    after = tk.render(dict(state, verdict={"render": v}))
    assert after["unconfirmed"] == [] and len(vendor.posts()) == posts + 2, after   # b again, and c for the first time


def test_a_reply_with_no_id_and_a_death_mid_post_are_both_unconfirmed(live, monkeypatch):
    tk, state = live
    vendor = Vendor(post_noid={1})
    monkeypatch.setattr(L, "http", vendor)
    monkeypatch.setattr(L.LiveToolkit, "script", scripts())
    assert tk.render(state)["unconfirmed"] == ["a"]
    other = dict(state, run_dir=state["run_dir"] + "-2")
    tk2 = L.LiveToolkit(other["run_dir"])
    prompt = L.scene_prompt(json.load(open(BOARD)), json.load(open(BOARD))["spots"]["zai"]["scenes"]["c"])
    tk2.ledger.append("request", "render", request_id="req_died", spot="zai", scene="zai-c", engine="google/gemini-omni-flash",
                      prompt=prompt)
    vendor2 = Vendor()
    monkeypatch.setattr(L, "http", vendor2)
    v = tk2.render(other)
    # The request for c may have been billed, so a and b wait with it rather than being sent ahead of it.
    assert v["unconfirmed"] == ["c"] and len(vendor2.posts()) == 0, (v, vendor2.posts())


def test_an_unconfirmed_closer_render_stops_and_says_where_to_look(live, monkeypatch):
    tk, state = live
    monkeypatch.setattr(L, "http", Vendor(post_fail={"closer"}))
    monkeypatch.setattr(L.LiveToolkit, "script", scripts())
    ok, why = tk.render_closer("zai", {"closer": CLOSER}, tk.dir("zai-av"), {})
    assert not ok and "zai closer" in why and "never confirmed" in why, why
    assert [r for r in tk.ledger.rows() if r.get("status") == "UNCONFIRMED"], "the unknown render is not on the record"


def test_a_timed_out_scene_is_collected_on_its_retry_not_sent_twice(live, monkeypatch):
    tk, state = live
    vendor = Vendor()
    monkeypatch.setattr(L, "http", vendor)
    monkeypatch.setattr(L.LiveToolkit, "script", scripts())
    monkeypatch.setattr(L, "WAIT_LIMIT", -1)       # every poll times out at once
    v = tk.render(state)
    assert sorted(v["failed"]) == ["a", "b", "c"], v
    monkeypatch.setattr(L, "WAIT_LIMIT", 60)
    posts = len(vendor.posts())
    v = tk.render(dict(state, verdict={"render": v}))
    assert v["failed"] == [] and len(vendor.posts()) == posts, "a timed-out request was sent again"


def test_a_finished_render_the_vendor_holds_back_is_collected_not_sent_again(live, monkeypatch):
    """Z.ai's re-shoot ran the account dry. Two scenes finished at fal, which then refused to hand
    over the results until a top-up. Logged as FAILED, the re-roll sent both again, and only the
    locked account stopped the second charge. A held-back result is owed: the next pass collects
    it, a refused re-send in between hides nothing, and nothing is sent for it twice."""
    tk, state = live
    vendor = Vendor(locked={"fal-2"})
    monkeypatch.setattr(L, "http", vendor)
    monkeypatch.setattr(L.LiveToolkit, "script", scripts())
    v = tk.render(state)
    assert v["failed"] == ["b"] and "held back" in v["why"]["b"], v
    held = [r for r in tk.ledger.rows() if r.get("status") == "UNCOLLECTED"]
    assert held and held[0]["http"] == 403 and held[0]["during"] == "result", held
    posts = len(vendor.posts())
    vendor.locked = set()
    after = tk.render(dict(state, verdict={"render": v}))
    assert after["failed"] == [] and len(vendor.posts()) == posts, "a finished render was paid for again"


def test_a_result_that_is_gone_is_rendered_again_not_waited_on(live, monkeypatch):
    """A 404 on a finished job's result means it is gone, and waiting will not bring it back. The
    scene is sent again on the next pass. A 403 behind a locked account is the one to wait for."""
    tk, state = live
    vendor = Vendor()
    monkeypatch.setattr(L, "http", vendor)
    monkeypatch.setattr(L.LiveToolkit, "script", scripts())
    real = vendor.__call__

    def gone(method, url, headers, body=None, timeout=120):
        if method == "GET" and url.rsplit("/", 1)[-1] == "fal-2":
            vendor.calls.append((method, url))
            return 404, b'{"detail": "Not found"}'
        return real(method, url, headers, body, timeout)
    monkeypatch.setattr(L, "http", gone)
    v = tk.render(state)
    assert v["failed"] == ["b"] and "gone" in v["why"]["b"], v
    assert [r["status"] for r in tk.ledger.rows() if r.get("http") == 404] == ["FAILED"]
    posts = len(vendor.posts())
    monkeypatch.setattr(L, "http", vendor)
    after = tk.render(dict(state, verdict={"render": v}))
    assert after["failed"] == [] and len(vendor.posts()) == posts + 1, "a gone result was waited on instead of sent again"
    assert [L.held_back(c) for c in (403, 402, 429, 503, 404, 410, 400)] == [True, True, True, True, False, False, False]


def test_a_spot_with_nobody_written_in_it_and_no_face_source_runs_without_one(live, monkeypatch):
    """No scene shows a character and no face source is set, so there is nothing to read back
    against. The run goes ahead, and nothing asks for a face it never needed."""
    tk, state = live
    monkeypatch.delenv("PRESENTER_STILL")
    monkeypatch.setattr(L, "http", Vendor())
    run = scripts()
    monkeypatch.setattr(L.LiveToolkit, "script", run)
    v = tk.render(state)
    assert v["failed"] == [], v
    assert not calls_to(run, "gates/cast_gate.py"), "a face was asked for with nothing to hold it to"


def test_a_job_the_vendor_dropped_is_sent_again_in_the_same_pass(live, monkeypatch):
    """fal dropped two finished jobs while the account was locked, and their status came back
    NOT_FOUND. Owed, they were polled for forty minutes and timed out, and the run stopped with
    nothing to show. A dropped job is asked about once, recorded as gone, and sent again in the
    same pass, so the re-entry that pays for it also collects it. Gone means the vendor said so
    twice, for the status and the result alike."""
    tk, state = live
    monkeypatch.setattr(L, "WAIT_LIMIT", 1)   # a wait that never ends fails the test, not the clock
    board = json.load(open(BOARD))
    prompt = L.scene_prompt(board, board["spots"]["zai"]["scenes"]["b"])
    tk.ledger.append("request", "render", request_id="req_b1", spot="zai", scene="zai-b", engine="google/gemini-omni-flash",
                     prompt=prompt)
    tk.ledger.append("queued", "render", request_id="req_b1", vendor_id="fal-b1", status_url="https://queue/fal-b1/status",
                     response_url="https://queue/fal-b1")
    tk.ledger.append("landing", "render", request_id="req_b1", vendor_id="fal-b1", status="TIMEOUT", last=None)
    vendor = Vendor(dropped={"fal-b1"})
    monkeypatch.setattr(L, "http", vendor)
    monkeypatch.setattr(L.LiveToolkit, "script", scripts())
    v = tk.render(dict(state, verdict={"render": {"failed": ["b"]}}))
    assert v["failed"] == [] and len(vendor.posts()) == 1, (v, vendor.posts())
    gone = [r for r in tk.ledger.rows() if r.get("request_id") == "req_b1" and r.get("during") == "status"]
    assert gone and gone[0]["status"] == "FAILED" and gone[0]["http"] == 404, gone
    polls = [u for m, u in vendor.calls if u == "https://queue/fal-b1/status"]
    assert len(polls) == 2, f"a dropped job is confirmed twice, a poll apart, and was asked {len(polls)} times"


def test_a_lapsed_status_with_its_result_still_there_is_collected_not_paid_for_again(live, monkeypatch):
    """A status lookup that says NOT_FOUND is not proof the job is gone. When the result is still
    there, the scene is collected, and nothing is sent for it again."""
    tk, state = live
    monkeypatch.setattr(L, "WAIT_LIMIT", 1)
    vendor = Vendor()
    real = vendor.__call__

    def lapsed(method, url, headers, body=None, timeout=120):
        if method == "GET" and url == "https://queue/fal-2/status":
            vendor.calls.append((method, url))
            return 404, b'{"status": "NOT_FOUND"}'
        return real(method, url, headers, body, timeout)
    monkeypatch.setattr(L, "http", lapsed)
    monkeypatch.setattr(L.LiveToolkit, "script", scripts())
    v = tk.render(state)
    assert v["failed"] == [] and len(vendor.posts()) == 3, (v, vendor.posts())
    assert not [r for r in tk.ledger.rows() if r.get("during") == "status"], "a lapsed status was taken for a dropped job"


def test_an_owed_job_whose_status_lapsed_is_collected_before_anything_is_sent(live, monkeypatch):
    """The check before waiting on an owed job reads the result too. A lapsed status with the
    result still there is a finished render to collect, never a scene to pay for again."""
    tk, state = live
    monkeypatch.setattr(L, "WAIT_LIMIT", 1)
    board = json.load(open(BOARD))
    prompt = L.scene_prompt(board, board["spots"]["zai"]["scenes"]["b"])
    tk.ledger.append("request", "render", request_id="req_b1", spot="zai", scene="zai-b", engine="google/gemini-omni-flash",
                     prompt=prompt)
    tk.ledger.append("queued", "render", request_id="req_b1", vendor_id="fal-b1", status_url="https://queue/fal-b1/status",
                     response_url="https://queue/fal-b1")
    tk.ledger.append("landing", "render", request_id="req_b1", vendor_id="fal-b1", status="TIMEOUT", last=None)
    vendor = Vendor()
    real = vendor.__call__

    def lapsed(method, url, headers, body=None, timeout=120):
        if method == "GET" and url == "https://queue/fal-b1/status":
            vendor.calls.append((method, url))
            return 404, b'{"status": "NOT_FOUND"}'
        return real(method, url, headers, body, timeout)
    monkeypatch.setattr(L, "http", lapsed)
    monkeypatch.setattr(L.LiveToolkit, "script", scripts())
    v = tk.render(dict(state, verdict={"render": {"failed": ["b"]}}))
    assert v["failed"] == [] and vendor.posts() == [], (v, vendor.posts())


def test_a_job_dropped_while_it_is_polled_stops_the_wait(live, monkeypatch):
    """A job that turns NOT_FOUND mid-poll will never complete, so the wait ends there and the
    scene fails, rather than running the clock out to a timeout that reads as still owed."""
    tk, state = live
    monkeypatch.setattr(L, "WAIT_LIMIT", 1)   # a wait that never ends fails the test, not the clock
    vendor = Vendor(dropped={"fal-2"})
    monkeypatch.setattr(L, "http", vendor)
    monkeypatch.setattr(L.LiveToolkit, "script", scripts())
    v = tk.render(state)
    assert v["failed"] == ["b"] and "no longer has" in v["why"]["b"], v
    assert not [r for r in tk.ledger.rows() if r.get("status") == "TIMEOUT"], "a dropped job was waited out"


def test_a_render_that_came_back_with_no_video_is_sent_again(live, monkeypatch):
    """Owed means a finished video is waiting. A result that arrived and held no video has nothing
    to collect, so the next pass sends the scene once more."""
    tk, state = live
    vendor = Vendor(empty={"fal-2"})
    monkeypatch.setattr(L, "http", vendor)
    monkeypatch.setattr(L.LiveToolkit, "script", scripts())
    v = tk.render(state)
    assert v["failed"] == ["b"] and v["why"]["b"] == "no video came back", v
    posts = len(vendor.posts())
    vendor.empty = set()
    after = tk.render(dict(state, verdict={"render": v}))
    assert after["failed"] == [] and len(vendor.posts()) == posts + 1, "a scene with no video was waited on instead of sent"


def test_a_held_back_render_logged_the_old_way_is_still_collected(live, monkeypatch):
    """The re-shoot's own ledger holds the old shape. Scene b finished, its result was refused
    with a 403 and logged as FAILED, and the re-roll's request was then refused at the queue.
    The re-entry after a top-up has to find the finished job behind the refused one and collect
    it, and send nothing."""
    tk, state = live
    board = json.load(open(BOARD))
    prompt = L.scene_prompt(board, board["spots"]["zai"]["scenes"]["b"])
    tk.ledger.append("request", "render", request_id="req_b1", spot="zai", scene="zai-b", engine="google/gemini-omni-flash",
                     prompt=prompt)
    tk.ledger.append("queued", "render", request_id="req_b1", vendor_id="fal-b1", status_url="https://queue/fal-b1/status",
                     response_url="https://queue/fal-b1")
    tk.ledger.append("landing", "render", request_id="req_b1", vendor_id="fal-b1", status="FAILED", http=403,
                     error='{"detail": "User is locked. Reason: TOP_UP."}')
    tk.ledger.append("request", "render", request_id="req_b2", spot="zai", scene="zai-b", engine="google/gemini-omni-flash",
                     prompt=prompt)
    tk.ledger.append("landing", "render", request_id="req_b2", status="REFUSED", http=403, error="Exhausted balance")
    vendor = Vendor()
    monkeypatch.setattr(L, "http", vendor)
    monkeypatch.setattr(L.LiveToolkit, "script", scripts())
    v = tk.render(dict(state, verdict={"render": {"failed": ["b"]}}))
    assert v["failed"] == [] and vendor.posts() == [], (v, vendor.posts())
    assert ("GET", "https://queue/fal-b1") in vendor.calls, "the finished job was not collected"


def test_a_finished_scene_that_failed_to_download_is_collected_not_paid_for_again(live, monkeypatch):
    tk, state = live
    vendor = Vendor()
    monkeypatch.setattr(L, "http", vendor)
    monkeypatch.setattr(L.LiveToolkit, "script", scripts())
    tries = []

    def flaky(url, path):
        tries.append(url)
        if len(tries) == 1:
            raise OSError("connection reset during download")
        open(path, "wb").write(b"video")
    monkeypatch.setattr(L.urllib.request, "urlretrieve", flaky)
    v = tk.render(state)
    assert v["failed"] == ["a"], v
    assert [r["status"] for r in tk.ledger.rows() if r["kind"] == "landing" and "request_id" in r][0] == "UNCOLLECTED"
    posts = len(vendor.posts())
    v = tk.render(dict(state, verdict={"render": v}))
    assert v["failed"] == [] and len(vendor.posts()) == posts, "a finished scene was paid for again"


def test_a_re_roll_sends_only_the_broken_scene_and_keeps_the_narration(live, monkeypatch):
    tk, state = live
    vendor = Vendor(reject={"fal-2"})
    monkeypatch.setattr(L, "http", vendor)
    run = scripts()
    monkeypatch.setattr(L.LiveToolkit, "script", run)
    v = tk.render(state)
    vendor.reject = set()
    posts = len(vendor.posts())
    tk.render(dict(state, verdict={"render": v}))
    sent = [r["scene"] for r in tk.ledger.rows() if r["kind"] == "request" and r.get("engine", "").startswith("google")]
    assert len(vendor.posts()) == posts + 1 and sent[-1] == "zai-b", sent
    assert len(calls_to(run, "gates/voice_take.sh")) == 1, "the narration was redrawn on a re-roll"


def test_a_scene_named_in_an_answer_must_be_one_of_the_spots(live, monkeypatch):
    tk, state = live
    vendor = Vendor()
    monkeypatch.setattr(L, "http", vendor)
    monkeypatch.setattr(L.LiveToolkit, "script", scripts())
    v = tk.render(dict(state, changes={"scene": "zai-a", "prompt": "a calmer take", "reason": "the author"}))
    req = [r for r in tk.ledger.rows() if r["kind"] == "request" and r.get("scene") == "zai-a"][-1]
    assert v["rendered"] == ["a"] and req["prompt"].startswith("a calmer take") and req["why"] == "the author", req
    posts = len(vendor.posts())
    with pytest.raises(L.LiveSetupError):
        tk.render(dict(state, changes={"scene": "zai-zai-a", "prompt": "x"}))
    assert len(vendor.posts()) == posts, "a request went out for a scene the board does not have"


def test_an_edge_flag_comes_back_in_the_verdict_and_an_unreadable_scene_is_flagged_too(live, monkeypatch):
    tk, state = live
    monkeypatch.setattr(L, "http", Vendor())
    flag = "EDGE CLIP: bright compact prop straddles the frame edge at left 2.8-2.9s. Look before shipping."
    monkeypatch.setattr(L.LiveToolkit, "script", scripts(edge=(3, flag + "\n")))
    v = tk.render(state)
    assert v["flags"] == {"a": flag, "b": flag, "c": flag}, v
    monkeypatch.setattr(L.LiveToolkit, "script", scripts(edge=(64, "")))
    v = tk.render(dict(state, changes={"scene": "a"}))
    assert "could not read" in v["flags"]["a"], v


# what reaches the ledger

def test_no_identity_id_or_local_path_reaches_the_ledger(live, monkeypatch, tmp_path):
    tk, state = live
    monkeypatch.setattr(L, "http", Vendor())
    monkeypatch.setattr(L.LiveToolkit, "script", scripts())
    tk.render(state)
    text = ledger_text(tk)
    assert VOICE not in text, "the voice id reached the ledger"
    assert str(tmp_path) not in text, "an absolute path reached the ledger"
    assert L.fingerprint(VOICE) in text, "the voice is not identified by its fingerprint"


def test_what_the_build_and_the_gates_print_is_scrubbed(live, monkeypatch, tmp_path):
    """Script output quotes absolute paths and, on a refusal, identities. Every row a step
    writes from it is checked here, the build log, a build failure, the ad gates and the ship
    gate, since each of those once reached the ledger raw."""
    tk, state = live
    noisy = f"{tk.run_dir}/masters/zai-v1.mp4 {os.path.expanduser('~')}/x {PINNED} {VOICE} {NAME} /tmp/.receipt"
    monkeypatch.setattr(L.LiveToolkit, "script", scripts(
        gates=(0, f"{noisy}\nMOUTH SYNC PASS: corr 0.43 at lag +0.04s\nAD_GATES_RESULT caption=pass drift=pass mouth=pass"),
        ship=(0, f"{noisy}\nSHIP-GATE PASS: /tmp/.ship-gate-zai"),
        loud=(0, f"{noisy}\nLOUDNESS_GATE i=-16.0 tp=-2.0 verdict=PASS")))
    v = tk.build(state)
    assert v["pass"], v
    art = dict(state, artifacts=dict(v["artifacts"]))
    with open(art["artifacts"]["captions"], "w") as fh:
        json.dump({"closer_start": 15.0, "closer_dur": 10.0}, fh)
    tk.ad_gates(art)
    tk.ship_gate(art)

    def failing(self, args, env):
        return done(1, f"ffmpeg: {noisy}\nError opening input")
    monkeypatch.setattr(L.LiveToolkit, "script", scripts(build=failing))
    assert tk.build(state) == {"pass": False}
    text = ledger_text(tk)
    for leak in (str(tmp_path), os.path.expanduser("~") + "/", PINNED, VOICE, NAME, "/tmp/"):
        assert leak not in text, f"{leak!r} reached the ledger"


def test_a_refused_look_costs_nothing_and_names_no_identity(live, monkeypatch):
    """The guards run before the voice is drawn, so a refused look pays for nothing. The
    refusal quotes the look, the pinned id, its name and its group, and none of them may
    reach the ledger, the look even when it is on the line that is kept."""
    tk, state = live
    refusal = (f"BLOCKED: {LOOK} is not the pinned clone and is not a look inside her avatar group\n\n"
               f"  used:   {LOOK}\n  pinned: {PINNED}  ({NAME})\n  group:  {GROUP}\n"
               f"Pins: {os.environ['IDENTITY_PINS']}\n")
    monkeypatch.setattr(L.LiveToolkit, "guard", REAL_GUARD)
    monkeypatch.setattr(L.subprocess, "run", lambda *a, **k: done(1, refusal))
    run = scripts()
    monkeypatch.setattr(L.LiveToolkit, "script", run)
    vendor = Vendor()
    monkeypatch.setattr(L, "http", vendor)
    ok, why = tk.render_closer("zai", {"closer": CLOSER}, tk.dir("zai-av"), {"look": LOOK})
    assert not ok and "refused" in why
    assert not vendor.calls and not calls_to(run, "gates/voice_take.sh"), "the voice was paid for before the guards ruled"
    text = ledger_text(tk)
    for leak in (LOOK, PINNED, GROUP, NAME, "Pins:", "pins.json"):
        assert leak not in text, f"{leak!r} reached the ledger"
    assert L.fingerprint(LOOK) in text


# closer

def test_a_reused_closer_must_say_this_spots_line(live, monkeypatch, tmp_path):
    tk, state = live
    src = tmp_path / "ads8-real" / "zai-av"
    src.mkdir(parents=True)
    for name in ("render.mp4", "upload.mp3", "stt.json"):
        (src / name).write_bytes(b"x")
    monkeypatch.setenv("CLOSER_FROM", str(src))
    (src / "script.txt").write_text(CLOSER + "\n")
    monkeypatch.setattr(L.LiveToolkit, "script", scripts())
    v = tk.closer(state)
    assert v["pass"] is True
    reused = [r for r in tk.ledger.rows() if r.get("status") == "REUSED"][0]
    assert reused["source"] == "ads8-real/zai-av", reused
    monkeypatch.setattr(L.LiveToolkit, "script", scripts(jaw=(1, "JAW_GATE jaw=0.21 face_cov=1.0 max=0.17 verdict=FAIL")))
    os.remove(os.path.join(tk.takes, "zai-av", "render.mp4"))
    assert tk.closer(state)["pass"] is False, "a jaw over the ceiling passed"
    os.remove(os.path.join(tk.takes, "zai-av", "render.mp4"))
    (src / "script.txt").write_text("a different closer line\n")
    run = scripts()
    monkeypatch.setattr(L.LiveToolkit, "script", run)
    assert tk.closer(state)["pass"] is False
    assert not calls_to(run, "gates/jaw_gate.py"), "measured a take it should have refused"
    assert not os.path.exists(os.path.join(tk.takes, "zai-av", "render.mp4")), "the wrong take was left as this run's closer"
    # The sidecar can say the right line while the audio says another. The read-back decides.
    (src / "script.txt").write_text(CLOSER + "\n")
    run = scripts(match=(1, "SCRIPT-MATCH FAIL: heard a different line"))
    monkeypatch.setattr(L.LiveToolkit, "script", run)
    assert tk.closer(state)["pass"] is False, "a take whose audio says another line was reused"
    assert not calls_to(run, "gates/jaw_gate.py")
    assert not os.path.exists(os.path.join(tk.takes, "zai-av", "render.mp4"))
    assert reused["identity"] == "unrecorded", reused


def test_a_jaw_gate_that_gave_no_verdict_is_unreadable_not_a_fail(live, monkeypatch):
    tk, state = live
    open(os.path.join(tk.dir("zai-av"), "render.mp4"), "wb").write(b"x")
    run = scripts(jaw=(1, ""))
    monkeypatch.setattr(L.LiveToolkit, "script", run)
    v = tk.closer(state)
    assert v["pass"] is False and v["unreadable"] is True, v
    args, env, drop, _ = calls_to(run, "gates/jaw_gate.py")[0]
    assert "SG_START" in drop and "SG_DUR" in drop, "a caller's SG_START would cut the closer the jaw gate reads"


def test_asking_for_a_new_look_renders_a_new_closer_once(live, monkeypatch):
    tk, state = live
    open(os.path.join(tk.dir("zai-av"), "render.mp4"), "wb").write(b"old")
    called = []
    monkeypatch.setattr(L.LiveToolkit, "render_closer", lambda self, *a: called.append(a) or (True, ""))
    monkeypatch.setattr(L.LiveToolkit, "script", scripts())
    v = tk.closer(dict(state, changes={"look": "ANOTHERLOOK1234567"}))
    assert called and v["artifacts"]["closer_inputs"][0] == L.fingerprint("ANOTHERLOOK1234567"), v
    called.clear()
    tk.closer(dict(state, changes={"look": "ANOTHERLOOK1234567"}, artifacts={"closer_inputs": v["artifacts"]["closer_inputs"]}))
    assert not called, "the same look was rendered twice"


def test_a_closer_render_is_on_the_ledger_whole_and_collected_not_recreated(live, monkeypatch):
    tk, state = live
    vendor = Vendor(heygen_status="processing")
    monkeypatch.setattr(L, "http", vendor)
    monkeypatch.setattr(L.LiveToolkit, "script", scripts())
    monkeypatch.setattr(L, "WAIT_LIMIT", -1)
    ok, _ = tk.render_closer("zai", {"closer": CLOSER}, tk.dir("zai-av"), {})
    assert not ok
    rows = tk.ledger.rows()
    assert [r for r in rows if r["kind"] == "request" and r.get("engine") == "heygen/assets"], "the paid upload has no request row"
    timeout = [r for r in rows if r["kind"] == "landing" and r.get("status") == "TIMEOUT"]
    assert timeout and timeout[0]["vendor_id"] == "vid1", "a timed-out render lost its video id"
    render_req = [r for r in rows if r["kind"] == "request" and r.get("engine") == "heygen/avatar_iii"][0]
    assert LOOK not in json.dumps(render_req) and "avatar_id" not in render_req["params"], render_req
    vendor.heygen_status = "completed"
    monkeypatch.setattr(L, "WAIT_LIMIT", 60)
    creates = sum(1 for m, u in vendor.calls if u.endswith("/v3/videos"))
    ok, _ = tk.render_closer("zai", {"closer": CLOSER}, tk.dir("zai-av"), {})
    assert ok and sum(1 for m, u in vendor.calls if u.endswith("/v3/videos")) == creates, "a render owed was created again"


# build, gates and delivery

def test_the_build_records_its_parameters_before_it_runs(live, monkeypatch):
    tk, state = live
    order = []

    def run(self, *args, env=None, drop=(), timeout=1800):
        order.append(("script", args[0], dict(env or {})))
        order.append(("rows", len(tk.ledger.rows())))
        return done(1, "stopped on purpose")
    monkeypatch.setattr(L.LiveToolkit, "script", run)
    tk.build(dict(state, changes={"nudge": -0.12}))
    build_row = [r for r in tk.ledger.rows() if r["kind"] == "build"][0]
    assert build_row["seq"] <= order[1][1], "the parameters were recorded after the build ran"
    assert build_row["closer_nudge"] == -0.12 and build_row["closer_autoalign"] == 0 and build_row["bed"] == "bed.mp3"
    assert build_row["scene_px"] == {"a": "1280x720", "b": "1280x720", "c": "1280x720"} and build_row["upscale"] == 1.5
    env = order[0][2]
    assert env["CLOSER_AUTOALIGN"] == "0" and env["CLOSER_NUDGE"] == "-0.12", env


SHOTS_BOARD = os.path.join(ROOT, "shoots", "graph-zai-shots", "boards.json")


def _ffmpeg(*args):
    subprocess.run(["ffmpeg", "-v", "error", "-y", *args], check=True, timeout=300)


def _probe(path, entries, stream="v:0"):
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", stream, "-show_entries", entries, "-of", "csv=p=0",
                        path], capture_output=True, text=True, timeout=60)
    return r.stdout.strip()


def _colour_at(path, t):
    """The average colour of one frame, as (r, g, b)."""
    r = subprocess.run(["ffmpeg", "-v", "error", "-ss", str(t), "-i", path, "-frames:v", "1", "-vf", "scale=1:1",
                        "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True, timeout=60)
    return tuple(r.stdout[:3])


def _shot(path, head, body, size, rate, sound=True, length=2.0):
    """A shot whose first 0.4 s is one colour and the rest another, with or without sound."""
    args = ["-f", "lavfi", "-i", f"color=c={head}:s={size}:r={rate}:d=0.4",
            "-f", "lavfi", "-i", f"color=c={body}:s={size}:r={rate}:d={length - 0.4}"]
    if sound:
        args += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={length}"]
    args += ["-filter_complex", "[0:v][1:v]concat=n=2:v=1:a=0[v]", "-map", "[v]"]
    if sound:
        args += ["-map", "2:a", "-c:a", "aac"]
    _ffmpeg(*args, "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path))


def test_the_shots_of_a_sentence_join_in_order_and_each_later_one_loses_its_head(tmp_path):
    """The first shot keeps its head for the builder to drop, every later shot loses the same
    SHOT_HEAD at the cut, and the clip carries the first shot's size, 25 frames a second and 48 kHz
    stereo throughout, with silence where a shot had no sound."""
    first, second, out = tmp_path / "b.mp4", tmp_path / "c.mp4", tmp_path / "slot.mp4"
    _shot(first, "yellow", "red", "1280x720", 24)
    _shot(second, "green", "blue", "640x360", 30, sound=False)
    assert L.join_shots([str(first), str(second)], str(out))
    seconds = L.duration(str(out))
    assert abs(seconds - (2.0 + 2.0 - L.SHOT_HEAD)) < 0.1, seconds
    assert _probe(str(out), "stream=width,height") == "1280,720"
    assert _probe(str(out), "stream=r_frame_rate") == "25/1"
    assert _probe(str(out), "stream=sample_rate,channels", "a:0") == "48000,2"

    def is_(colour, t):
        r, g, b = _colour_at(str(out), t)
        return {"yellow": r > 180 and g > 180 and b < 90, "red": r > 180 and g < 90 and b < 90,
                "green": g > 90 and r < 90 and b < 90, "blue": b > 180 and r < 90 and g < 90}[colour]
    assert is_("yellow", 0.1), "the first shot lost its head, which the builder drops itself"
    assert is_("red", 1.5), "the first shot does not come first"
    assert is_("blue", 2.1), "the second shot kept the head the builder would have dropped"
    assert is_("blue", 3.4)
    assert abs(float(_probe(str(out), "stream=duration", "a:0")) - seconds) < 0.15, "the silent shot left a gap in the sound"


def test_a_join_whose_probe_or_encode_hangs_is_a_failed_join_not_a_crash(tmp_path, monkeypatch):
    first = tmp_path / "b.mp4"
    _shot(first, "gray", "gray", "320x180", 25)

    def hang(cmd, **kw):
        raise subprocess.TimeoutExpired(cmd, kw.get("timeout", 0))
    monkeypatch.setattr(L.subprocess, "run", hang)
    assert L.join_shots([str(first), str(first)], str(tmp_path / "slot.mp4")) is False

    def missing(cmd, **kw):
        raise FileNotFoundError(cmd[0])
    monkeypatch.setattr(L.subprocess, "run", missing)
    assert L.join_shots([str(first), str(first)], str(tmp_path / "slot.mp4")) is False


def test_two_joined_shots_cover_the_long_sentence_the_old_build_froze_on(tmp_path):
    """The chained Z.ai run's middle sentence ran 9.28 s. One five second shot covers 4.55 s after
    the head the builder drops, so the builder slowed it to 1.6 times and held its last frame. Two
    joined shots cover it at the pace they were shot, within two percent."""
    first, second, out = tmp_path / "b.mp4", tmp_path / "c.mp4", tmp_path / "slot.mp4"
    _shot(first, "gray", "gray", "1280x720", 24, length=5.0)
    _shot(second, "gray", "gray", "1280x720", 24, length=5.0)
    assert L.join_shots([str(first), str(second)], str(out))
    sentence, dropped = 9.28, 0.45     # shoots/build-ad.sh counts a clip as its length less 0.45 s
    assert sentence / (L.duration(str(first)) - dropped) > 1.6, "one shot would not have frozen"
    assert sentence / (L.duration(str(out)) - dropped) < 1.02, L.duration(str(out))


def test_a_sentence_that_holds_two_shots_gets_them_joined_before_the_build(live, monkeypatch):
    """The build row names the shots under each sentence before anything runs. A lone shot goes to
    the builder as it is, and two shots are joined in order into the sentence's own clip first."""
    tk, state = live
    joined = []

    def join(self, srcs, out):
        joined.append(([os.path.basename(os.path.dirname(x)) for x in srcs], os.path.basename(os.path.dirname(out))))
        open(out, "wb").write(b"joined")
        return True
    monkeypatch.setattr(L.LiveToolkit, "join", join)
    monkeypatch.setattr(L, "has_audio", lambda path: True)
    run = scripts()
    monkeypatch.setattr(L.LiveToolkit, "script", run)
    assert tk.build(dict(state, board=SHOTS_BOARD))["pass"]
    assert joined == [(["zai-b", "zai-c"], "zai-slot2")], joined
    env = calls_to(run, "shoots/build-ad.sh")[0][1]
    assert (env["SCENE_A"], env["SCENE_B"], env["SCENE_C"]) == tuple(
        os.path.join(tk.takes, d, "raw.mp4") for d in ("zai-a", "zai-slot2", "zai-d")), env
    row = [r for r in tk.ledger.rows() if r["kind"] == "build"][0]
    assert row["slots"] == [["a"], ["b", "c"], ["d"]] and sorted(row["scene_px"]) == ["a", "b", "c", "d"], row


def test_a_lone_shot_with_no_sound_is_joined_alone_so_the_builder_has_sound_to_mix(live, monkeypatch):
    tk, state = live
    joined = []

    def join(self, srcs, out):
        joined.append(([os.path.basename(os.path.dirname(x)) for x in srcs], os.path.basename(os.path.dirname(out))))
        open(out, "wb").write(b"joined")
        return True
    monkeypatch.setattr(L.LiveToolkit, "join", join)
    monkeypatch.setattr(L, "has_audio", lambda path: os.path.basename(os.path.dirname(path)) != "zai-d")
    run = scripts()
    monkeypatch.setattr(L.LiveToolkit, "script", run)
    assert tk.build(dict(state, board=SHOTS_BOARD))["pass"]
    assert joined == [(["zai-b", "zai-c"], "zai-slot2"), (["zai-d"], "zai-slot3")], joined
    env = calls_to(run, "shoots/build-ad.sh")[0][1]
    assert env["SCENE_A"].endswith(os.path.join("zai-a", "raw.mp4")) and env["SCENE_C"].endswith(
        os.path.join("zai-slot3", "raw.mp4")), env


def test_one_shot_joined_alone_keeps_its_head_and_gains_silence(tmp_path):
    shot, out = tmp_path / "d.mp4", tmp_path / "slot.mp4"
    _shot(shot, "yellow", "red", "320x180", 24, sound=False)
    assert L.join_shots([str(shot)], str(out))
    assert abs(L.duration(str(out)) - 2.0) < 0.1 and L.has_audio(str(out))


def test_a_spot_without_slots_builds_one_scene_to_a_sentence_as_before(live, monkeypatch):
    tk, state = live
    monkeypatch.setattr(L.LiveToolkit, "join", lambda self, srcs, out: pytest.fail("a spot without slots joined shots"))
    run = scripts()
    monkeypatch.setattr(L.LiveToolkit, "script", run)
    assert tk.build(state)["pass"]
    env = calls_to(run, "shoots/build-ad.sh")[0][1]
    assert not any(k.startswith("SCENE_") for k in env), env
    assert "slots" not in [r for r in tk.ledger.rows() if r["kind"] == "build"][0]


def test_a_sentence_whose_shots_cannot_be_joined_stops_the_build(live, monkeypatch, tmp_path):
    """A failed join is recorded and the builder never runs, and so is a board whose slots do not
    come to the three sentences the builder cuts, which the board gate refuses before a run."""
    tk, state = live
    run = scripts()
    monkeypatch.setattr(L.LiveToolkit, "script", run)
    monkeypatch.setattr(L.LiveToolkit, "join", lambda self, srcs, out: False)
    assert tk.build(dict(state, board=SHOTS_BOARD)) == {"pass": False}
    failed = [r for r in tk.ledger.rows() if r["kind"] == "landing" and r["step"] == "build"]
    assert failed[-1]["status"] == "FAILED" and failed[-1]["during"] == "join", failed
    board = json.load(open(SHOTS_BOARD))
    board["spots"]["zai"]["slots"] = [["a", "b"], ["c", "d"]]
    two = tmp_path / "two.json"
    two.write_text(json.dumps(board))
    tried = []

    def join(self, srcs, out):
        tried.append(srcs)
        open(out, "wb").write(b"joined")
        return True
    monkeypatch.setattr(L.LiveToolkit, "join", join)
    assert tk.build(dict(state, board=str(two))) == {"pass": False}
    assert "gives 2 slots" in [r for r in tk.ledger.rows() if r["kind"] == "landing"][-1]["error"]
    assert not tried, "shots were joined for slots the builder cannot cut"
    assert not calls_to(run, "shoots/build-ad.sh"), "the builder ran without its clips"


def test_each_build_is_a_new_master_even_after_a_re_entry(live, monkeypatch):
    tk, state = live
    monkeypatch.setattr(L.LiveToolkit, "script", scripts())
    first = tk.build(state)["artifacts"]["master"]
    second = L.LiveToolkit(state["run_dir"], tk.ledger.run_id).build(state)["artifacts"]["master"]
    assert first.endswith("zai-v1.mp4") and second.endswith("zai-v2.mp4"), (first, second)


def test_the_ad_gates_verdicts_are_read_off_their_machine_lines(live, monkeypatch, tmp_path):
    tk, state = live
    art = dict(state, artifacts={"master": str(tmp_path / "m.mp4"), "captions": str(tmp_path / "c.json")})
    cases = [
        ((0, "MOUTH SYNC PASS: corr 0.43 at lag +0.04s\nAD_GATES_RESULT caption=pass drift=pass mouth=pass"),
         {"caption": "pass", "mouth": "pass", "lag_s": 0.04}),
        ((1, "AD_GATES_RESULT caption=pass drift=pass mouth=fail"), {"unreadable": True, "mouth": "unreadable"}),
        ((1, "AD_GATES_RESULT caption=pass drift=unreadable mouth=pass"), {"unreadable": True, "drift": "unreadable"}),
        ((64, "no result line at all"), {"unreadable": True}),
    ]
    for out, want in cases:
        monkeypatch.setattr(L.LiveToolkit, "script", scripts(gates=out))
        v = tk.ad_gates(art)
        assert all(v.get(k) == val for k, val in want.items()), (out, v)


def test_the_ship_gates_exits_become_the_causes_the_graph_routes_on(live, monkeypatch, tmp_path):
    tk, state = live
    captions = tmp_path / "captions.json"
    captions.write_text(json.dumps({"closer_start": 15.08, "closer_dur": 10.0}))
    state = dict(state, artifacts={"master": str(tmp_path / "m.mp4"), "captions": str(captions),
                                   "srt": str(tmp_path / "c.srt")})
    holds, ok = L.SHIP_HOLDS, (0, "LOUDNESS_GATE i=-16.0 tp=-2.0 verdict=PASS")
    cases = [((0, "SHIP-GATE PASS"), ok, None),
             ((1, f"{holds['letterbox']} 1280 720"), ok, "letterbox"),
             ((3, f"{holds['directional']} - READ"), ok, "directional"),
             ((3, f"{holds['replay']} (avatar_iii refill)"), ok, "replay"),
             ((3, "SHIP-GATE HOLD: something new"), ok, "held"),
             ((0, "SHIP-GATE PASS"), (1, "LOUDNESS_GATE i=-12.0 tp=-1.0 verdict=FAIL"), "loudness"),
             ((0, "SHIP-GATE PASS"), (1, ""), "unreadable"),
             ((64, "SHIP-GATE ERROR: input not readable"), ok, "unreadable")]
    for ship, loud, cause in cases:
        monkeypatch.setattr(L.LiveToolkit, "script", scripts(ship=ship, loud=loud))
        v = tk.ship_gate(state)
        assert v["cause"] == cause and v["pass"] is (cause is None), (ship, loud, v)
    row = [r for r in tk.ledger.rows() if r["step"] == "ship_gate"][-1]
    assert row["overrides"]["time"] == L.AD_FICTION and row["overrides"]["replay"] is None, row


def test_the_ship_gate_is_run_with_the_overrides_people_gave_and_no_others(live, monkeypatch, tmp_path):
    tk, state = live
    captions = tmp_path / "captions.json"
    captions.write_text(json.dumps({"closer_start": 15.08, "closer_dur": 10.0}))
    base = dict(state, artifacts={"master": str(tmp_path / "m.mp4"), "captions": str(captions), "srt": str(tmp_path / "c.srt")})
    monkeypatch.setenv("REPLAYOK", "left over in the caller's shell")
    run = scripts()
    monkeypatch.setattr(L.LiveToolkit, "script", run)
    tk.ship_gate(base)
    args, env, drop, _ = calls_to(run, "guards/ship_gate.sh")[-1]
    assert "--arrow-ok" not in args and "REPLAYOK" not in env and "REPLAYOK" in drop, (args, env, drop)
    assert env["ARROW_WINDOW"] == "0:15.08" and env["TIMEOK"] == L.AD_FICTION, env
    tk.ship_gate(dict(base, changes={"arrow_ok": "reader", "replay_ok": "a still room, read by r"}))
    args, env, drop, _ = calls_to(run, "guards/ship_gate.sh")[-1]
    assert "--arrow-ok" in args and env["REPLAYOK"] == "a still room, read by r", (args, env)


def test_the_scan_a_person_is_asked_to_read_is_kept_with_the_run(live, monkeypatch, tmp_path):
    tk, state = live
    captions = tmp_path / "captions.json"
    captions.write_text(json.dumps({"closer_start": 15.08, "closer_dur": 10.0}))
    masters = os.path.join(tk.run_dir, "masters")
    os.makedirs(masters, exist_ok=True)
    scan = os.path.join(masters, "zai-v1.replay.png")
    open(scan, "wb").write(b"png")
    hold = (f"  PROBE REPLAYS: turned about t=20.0s at 2% of control\nslit-scan: {scan}\nreplay vertex: t=20.0s\n"
            f"{L.SHIP_HOLDS['replay']} (avatar_iii refill)")
    monkeypatch.setattr(L.LiveToolkit, "script", scripts(ship=(3, hold)))
    v = tk.ship_gate(dict(state, artifacts={"master": os.path.join(masters, "zai-v1.mp4"), "captions": str(captions),
                                            "srt": str(tmp_path / "c.srt")}))
    assert v["cause"] == "replay" and v["slit"] == "evidence/zai-v1.replay.png", v
    assert os.path.isfile(os.path.join(tk.run_dir, "evidence", "zai-v1.replay.png"))
    assert v["replay_turn_s"] == 20.0 and v["replay"].endswith("t=20.0s at 2% of control"), v


def test_a_second_delivery_says_what_it_replaces(live, monkeypatch):
    tk, state = live
    for v in (1, 2):
        m = os.path.join(tk.run_dir, "masters", f"zai-v{v}.mp4")
        os.makedirs(os.path.dirname(m), exist_ok=True)
        open(m, "wb").write(b"cut")
        tk.deliver(dict(state, artifacts={"master": m}))
    rows = [r for r in tk.ledger.rows() if r["kind"] == "deliver"]
    assert rows[0]["supersedes"] is None and rows[1]["supersedes"] == "delivered/zai-v1.mp4", rows


# the story's character's face

def cast_state(state, board=CAST_BOARD):
    return dict(state, board=board)


def closer_take(tmp_path, line=CLOSER):
    """A closer take to reuse, standing in for the one CLOSER_FROM names."""
    src = tmp_path / "ads8-real" / "zai-av"
    src.mkdir(parents=True, exist_ok=True)
    for name in ("render.mp4", "upload.mp3", "stt.json"):
        (src / name).write_bytes(b"x")
    (src / "script.txt").write_text(line + "\n")
    return src


def test_a_scene_that_shows_the_character_is_rendered_from_her_face(live, monkeypatch, tmp_path):
    """The Z.ai scenes named "a student", and the girl changed from one scene to the next. A scene
    that writes {character} goes to the reference path with her face, the request row names that
    face by hash and never carries the image, and a scene with nobody in it stays on the plain path.
    Her face is held apart from the narrator's before anything is sent, and every scene is read back
    against hers and the narrator's with the face extra's interpreter, on a reused take too."""
    tk, state = live
    board = json.load(open(CAST_BOARD))
    board["spots"]["zai"]["scenes"]["b"] = ("The vast warehouse of workstations hums, screens scrolling, a ceramic "
                                            "coffee mug perfectly still. Mouth closed, nobody speaks.")
    path = tmp_path / "board.json"
    path.write_text(json.dumps(board))
    monkeypatch.setenv("CLOSER_FROM", str(closer_take(tmp_path)))
    monkeypatch.setenv("FACEPY", "/opt/face/bin/python")
    bodies = []
    vendor = Vendor(on_post=lambda url, body: bodies.append((url, json.loads(body))) if "queue" in url else None)
    monkeypatch.setattr(L, "http", vendor)
    # Scene b has nobody in it, so the gate finds no face there, which is what it should find.
    run = scripts(cast=lambda clip: (3, CG.line([])) if "zai-b" in clip else SAME)
    monkeypatch.setattr(L.LiveToolkit, "script", run)
    v = tk.render(cast_state(state, str(path)))
    assert v["failed"] == [] and v["flags"] == {}, v
    ref_url, plain_url = f"{L.FAL}/{REF_ENGINE}", f"{L.FAL}/google/gemini-omni-flash"
    assert [u for u, _ in bodies] == [ref_url, plain_url, ref_url], bodies
    face = bodies[0][1]["image_urls"][0]
    assert face.startswith("data:image/jpeg;base64,")
    assert L.base64.b64decode(face.split(",", 1)[1]) == b"the character's face", "the scene was not sent her face"
    assert "the student in <IMAGE_REF_0>" in bodies[0][1]["prompt"] and "the student in <IMAGE_REF_0>" in bodies[2][1]["prompt"]
    assert not any("{character}" in b["prompt"] for _, b in bodies), "the placeholder reached the engine"
    assert "image_urls" not in bodies[1][1], "a scene with nobody in it was sent a face"
    rows = tk.ledger.rows()
    her = os.path.join(tk.takes, "zai-character", "reference.jpg")
    narrator = os.path.join(tk.takes, "zai-presenter", "reference.jpg")
    requests = [r for r in rows if r["kind"] == "request" and r["step"] == "render" and r.get("scene")]
    assert [r["engine"] for r in requests] == [REF_ENGINE, "google/gemini-omni-flash", REF_ENGINE], requests
    assert [r.get("reference_sha256") for r in requests] == [L.sha256(her), None, L.sha256(her)]
    assert "data:image" not in ledger_text(tk), "the face itself reached the ledger"
    cuts = {r["note"]: r for r in rows if str(r.get("note", "")).endswith("reference")}
    assert (cuts["the character's reference"]["source"], cuts["the character's reference"]["file"]) == \
        ("still", "takes/zai-character/reference.jpg"), cuts
    assert (cuts["the presenter's reference"]["source"], cuts["the presenter's reference"]["file"]) == \
        ("closer take", "takes/zai-presenter/reference.jpg"), cuts
    assert [r["passed"] for r in rows if r.get("check") == "distinct"] == [True]
    checks = calls_to(run, "gates/cast_gate.py")
    assert [c[0][1] for c in checks[:2]] == ["--reference", "--reference"], checks
    reads = [c[0] for c in checks[2:]]
    assert reads[0][1:] == ("gates/cast_gate.py", narrator, her)[1:], "the character was not held apart from the narrator first"
    assert len(reads) == 4 and all(c[1] == her and c[3:] == ("--not", narrator) for c in reads[1:]), reads
    assert {c[3] for c in checks} == {"/opt/face/bin/python"}, "the cast gate ran without the face extra"
    assert [r["scene"] for r in rows if r.get("check") == "cast" and r["passed"]] == ["zai-a", "zai-c"]
    assert {r["against"] for r in rows if r.get("check") == "cast"} == {"character"}
    posts = len(vendor.posts())
    again = L.LiveToolkit(state["run_dir"], tk.ledger.run_id).render(cast_state(state, str(path)))
    assert again["failed"] == [] and len(vendor.posts()) == posts, again
    # Three more reads of the reused takes, and the pair that already passed is not read again.
    assert len(calls_to(run, "gates/cast_gate.py")) == 9, "a reused take was not read back, or the pair was read twice"


def test_no_face_to_hold_the_character_to_stops_before_anything_is_sent(live, monkeypatch, tmp_path):
    tk, state = live
    vendor = Vendor()
    monkeypatch.setattr(L, "http", vendor)
    monkeypatch.setattr(L.LiveToolkit, "script", scripts())
    monkeypatch.delenv("CHARACTER_FROM")
    with pytest.raises(L.LiveSetupError, match="needs her face"):
        tk.render(cast_state(state))
    monkeypatch.setenv("CHARACTER_FROM", str(tmp_path / "nowhere.jpg"))
    with pytest.raises(L.LiveSetupError, match="is not a file"):
        tk.render(cast_state(state))
    monkeypatch.setenv("CHARACTER_FROM", str(tmp_path / "character.jpg"))
    monkeypatch.setattr(L.LiveToolkit, "script", scripts(reference_ok=False))
    with pytest.raises(L.LiveSetupError, match="no face could be cut"):
        tk.render(cast_state(state))
    assert vendor.calls == [], "something was sent for a scene with no face to hold it to"


def test_a_character_who_reads_as_the_narrator_stops_before_anything_is_sent(live, monkeypatch, tmp_path):
    """The story's girl is someone other than the narrator. Her reference is read against the
    narrator's before any scene is paid for. One that reads as the narrator stops the run, and so
    does one the gate finds no face in, or one over the floor that failed only on a stranger. A
    pair that passed is not read again."""
    tk, state = live
    vendor = Vendor()
    monkeypatch.setattr(L, "http", vendor)
    for answer, said in (((0, CG.line([0.46])), r"reads as the narrator \(face similarity 0.46"),
                         (NO_FACE, "no face the gate could find"),
                         ((1, CG.line([0.50], strangers=2)), r"reads as the narrator \(face similarity 0.50"),
                         ((64, "CAST_GATE unreadable: the reference holds no face"), "no reading the gate could make")):
        monkeypatch.setattr(L.LiveToolkit, "script", scripts(distinct=answer))
        with pytest.raises(L.LiveSetupError, match=said):
            tk.render(cast_state(state))
    assert vendor.calls == [], "a scene was paid for before the character was held apart from the narrator"
    assert [r["passed"] for r in tk.ledger.rows() if r.get("check") == "distinct"] == [False] * 4
    run = scripts()
    monkeypatch.setattr(L.LiveToolkit, "script", run)
    assert tk.render(cast_state(state))["failed"] == []
    assert tk.render(cast_state(state))["failed"] == []
    pairs = [c for c in calls_to(run, "gates/cast_gate.py") if c[0][1] != "--reference" and "--not" not in c[0]]
    assert len(pairs) == 1, "a pair of faces that passed was read again"
    # A new face for her is a new pair, and it is read before anything else happens.
    os.remove(os.path.join(tk.takes, "zai-character", "reference.jpg"))
    other = tmp_path / "another-girl.jpg"
    other.write_bytes(b"another girl")
    monkeypatch.setenv("CHARACTER_FROM", str(other))
    tk.render(cast_state(state))
    pairs = [c for c in calls_to(run, "gates/cast_gate.py") if c[0][1] != "--reference" and "--not" not in c[0]]
    assert len(pairs) == 2, "a new face for the character was never held apart from the narrator"


def test_a_scene_that_reads_closer_to_the_narrator_fails_whatever_the_floor_says(live, monkeypatch):
    """The narrator rendered into one of the girl's scenes read 0.40 against the girl, over the
    floor, and 0.53 against the narrator. A scene that reads at least as close to the narrator as
    to the character is the narrator, so it fails and says so."""
    tk, state = live
    monkeypatch.setattr(L, "http", Vendor())
    narrator = (1, CG.line([0.40] * 8, 0, [0.53] * 8))
    monkeypatch.setattr(L.LiveToolkit, "script", scripts(cast=lambda clip: narrator if "zai-a" in clip else SAME))
    v = tk.render(cast_state(state))
    assert v["failed"] == ["a"], v
    assert v["why"]["a"] == ("the narrator, not the story's character, face similarity 0.53 to the narrator "
                             "against 0.40 to her"), v["why"]


def test_a_re_roll_of_a_scene_without_her_is_still_read_against_her(live, monkeypatch, tmp_path):
    """A spot with a character reads every scene against her face, including a re-roll of a scene
    she is not written into, where a stranger or the narrator would otherwise pass unread."""
    tk, state = live
    board = json.load(open(CAST_BOARD))
    board["spots"]["zai"]["scenes"]["b"] = ("The vast warehouse of workstations hums, screens scrolling, a ceramic "
                                            "coffee mug perfectly still. Mouth closed, nobody speaks.")
    path = tmp_path / "board.json"
    path.write_text(json.dumps(board))
    vendor = Vendor(reject={"fal-2"})
    monkeypatch.setattr(L, "http", vendor)
    run = scripts(cast=lambda clip: (3, CG.line([])) if "zai-b" in clip else SAME)
    monkeypatch.setattr(L.LiveToolkit, "script", run)
    first = tk.render(cast_state(state, str(path)))
    assert first["failed"] == ["b"], first
    vendor.reject = set()
    seen = len(run.seen)
    again = tk.render(dict(cast_state(state, str(path)), verdict={"render": first}))
    assert again["failed"] == [] and again["fresh"] == ["b"], again
    reads = [c[0] for c in run.seen[seen:] if c[0][0] == "gates/cast_gate.py"]
    her = os.path.join(tk.takes, "zai-character", "reference.jpg")
    assert [c[1] for c in reads] == [her] and "--not" in reads[0], reads


def test_a_character_spot_with_no_narrator_face_stops_before_anything_is_sent(live, monkeypatch):
    """A closer rendered fresh leaves the run no face for the narrator until after the scenes are
    paid for, and then nothing could hold the character apart from her or read the closer back.
    A spot with a character needs the narrator's face before anything is sent."""
    tk, state = live
    monkeypatch.delenv("PRESENTER_STILL")
    vendor = Vendor()
    monkeypatch.setattr(L, "http", vendor)
    monkeypatch.setattr(L.LiveToolkit, "script", scripts())
    with pytest.raises(L.LiveSetupError, match="the narrator's face is needed"):
        tk.render(cast_state(state))
    assert vendor.calls == [], "a scene was paid for with no narrator to hold the character apart from"


def test_recasting_her_on_a_re_entry_cuts_her_face_again_and_renders_the_scenes_again(live, monkeypatch, tmp_path):
    """A re-entry after someone points CHARACTER_FROM at another girl renders every scene of hers
    from the new face. The old reference is cut again, and the takes sent with the old face are
    never reused, since a request sent with another face is not this one."""
    tk, state = live
    vendor = Vendor()
    monkeypatch.setattr(L, "http", vendor)
    monkeypatch.setattr(L.LiveToolkit, "script", scripts())
    assert tk.render(cast_state(state))["failed"] == []
    her = os.path.join(tk.takes, "zai-character", "reference.jpg")
    first_face = L.sha256(her)
    other = tmp_path / "another-girl.jpg"
    other.write_bytes(b"another girl")
    monkeypatch.setenv("CHARACTER_FROM", str(other))
    posts = len(vendor.posts())
    again = L.LiveToolkit(state["run_dir"], tk.ledger.run_id).render(cast_state(state))
    assert again["failed"] == [] and sorted(again["fresh"]) == ["a", "b", "c"], again
    assert L.sha256(her) != first_face, "the old face was kept after she was recast"
    assert len(vendor.posts()) == posts + 3, "a scene rendered from the old face was reused"
    rows = tk.ledger.rows()
    assert not [r for r in rows if r.get("status") == "REUSED"]
    requests = [r for r in rows if r["kind"] == "request" and r.get("scene")]
    assert {r["reference_sha256"] for r in requests[-3:]} == {L.sha256(her)}
    cuts = [r for r in rows if r.get("note") == "the character's reference"]
    assert len(cuts) == 2 and cuts[0]["source_sha256"] != cuts[1]["source_sha256"], cuts
    # The same source again is not a recast, so nothing is cut or sent.
    posts = len(vendor.posts())
    tk.render(cast_state(state))
    assert len(vendor.posts()) == posts and len([r for r in tk.ledger.rows() if r.get("note") == "the character's reference"]) == 2
    # A reference file changed by hand is not the face the ledger recorded, so it is cut again from
    # the source rather than sent.
    kept = open(her, "rb").read()
    open(her, "wb").write(b"a face nobody recorded")
    tk.render(cast_state(state))
    assert open(her, "rb").read() == kept, "a reference changed by hand was sent to the engine"
    assert len([r for r in tk.ledger.rows() if r.get("note") == "the character's reference"]) == 3


def test_a_scene_that_writes_the_narrator_in_is_never_sent(live, monkeypatch, tmp_path):
    """Boards from before the story had its own character wrote the narrator into their scenes as
    {presenter}. The narrator appears only in the closer, and the placeholder would otherwise reach
    the engine as text, so a re-entry on such a board refuses the scene before anything is sent."""
    tk, state = live
    vendor = Vendor()
    monkeypatch.setattr(L, "http", vendor)
    monkeypatch.setattr(L.LiveToolkit, "script", scripts())
    old = os.path.join(ROOT, "shoots", "graph-zai-cast", "boards.json")
    v = tk.render(dict(state, board=old))
    assert v["failed"] == ["a", "b", "c"], v
    assert v["why"]["a"] == "the scene writes the narrator in with {presenter}, and she appears only in the closer", v
    assert vendor.calls == [], "a scene that writes the narrator in was sent"


def test_a_different_person_fails_the_scene_and_no_face_goes_to_the_eye(live, monkeypatch, tmp_path):
    """A different person re-rolls the scene. A scene with no face, or one the gate could not
    read, is not a pass either, so it goes to the eye as a flag."""
    tk, state = live
    monkeypatch.setenv("CLOSER_FROM", str(closer_take(tmp_path)))
    monkeypatch.setattr(L, "http", Vendor())
    answers = {"zai-a": OTHER, "zai-b": NO_FACE, "zai-c": (64, "CAST_GATE unreadable: no frame could be read")}
    monkeypatch.setattr(L.LiveToolkit, "script", scripts(cast=lambda clip: answers[os.path.basename(os.path.dirname(clip))]))
    v = tk.render(cast_state(state))
    assert v["failed"] == ["a"], v
    assert v["why"]["a"] == "a different person from the story's character, face similarity 0.05 under the gate's 0.30", \
        v["why"]
    assert v["flags"]["b"] == "CAST: no face found to match against the story's character. Look before shipping.", \
        v["flags"]
    assert v["flags"]["c"] == "CAST: the cast gate could not read this scene, so it needs a look", v["flags"]
    gates = [(r["scene"], r["passed"], r.get("unreadable", False)) for r in tk.ledger.rows() if r.get("check") == "cast"]
    assert gates == [("zai-a", False, False), ("zai-b", False, False), ("zai-c", False, True)], gates


def by_scene(answers):
    """A cast gate stand-in that answers per scene, read off the take's directory. An answer of
    None kills the process mid read-back, the way a crash between a landing and its reading would."""
    def cast(clip):
        answer = answers[os.path.basename(os.path.dirname(clip))]
        if answer is None:
            raise KeyboardInterrupt("the process died before the read-back")
        return answer
    return cast


def test_a_re_entry_reuses_a_take_that_passed_after_its_checkpoint_listed_it_failed(live, monkeypatch, tmp_path):
    """A re-entry resumes from a checkpoint, and its failed list can be older than a take that
    landed after it. Live, scene c came back as her and the next re-entry sent it again, which
    only a locked account refused. The ledger decides: a take that landed and passed its read-back
    is reused, and only the scene that is still broken is paid for."""
    tk, state = live
    monkeypatch.setenv("CLOSER_FROM", str(closer_take(tmp_path)))
    vendor = Vendor(reject={"fal-2"})
    monkeypatch.setattr(L, "http", vendor)
    monkeypatch.setattr(L.LiveToolkit, "script", scripts())
    first = tk.render(cast_state(state))
    assert first["failed"] == ["b"], first
    vendor.reject = set()
    posts = len(vendor.posts())
    stale = dict(cast_state(state), verdict={"render": dict(first, failed=["b", "c"])})
    again = L.LiveToolkit(state["run_dir"], tk.ledger.run_id).render(stale)
    sent = [r["scene"] for r in tk.ledger.rows() if r["kind"] == "request" and r.get("scene")]
    assert again["failed"] == [] and len(vendor.posts()) == posts + 1 and sent[-1] == "zai-b", (again, sent)
    assert sent.count("zai-c") == 1, "a take that landed and passed was paid for again"
    assert [r["scene"] for r in tk.ledger.rows() if r.get("status") == "REUSED"] == ["zai-c"]


def test_a_re_roll_renders_again_a_take_its_read_back_failed(live, monkeypatch, tmp_path):
    """A take that is not her fails the scene, and its re-roll is a new render, never the take the
    read-back refused."""
    tk, state = live
    monkeypatch.setenv("CLOSER_FROM", str(closer_take(tmp_path)))
    vendor = Vendor()
    monkeypatch.setattr(L, "http", vendor)
    answers = {"zai-a": SAME, "zai-b": SAME, "zai-c": OTHER}
    monkeypatch.setattr(L.LiveToolkit, "script", scripts(cast=by_scene(answers)))
    first = tk.render(cast_state(state))
    assert first["failed"] == ["c"], first
    answers["zai-c"] = SAME
    posts = len(vendor.posts())
    again = tk.render(dict(cast_state(state), verdict={"render": first}))
    assert again["failed"] == [] and again["fresh"] == ["c"] and len(vendor.posts()) == posts + 1, again
    assert not [r for r in tk.ledger.rows() if r.get("status") == "REUSED"], "the take its read-back refused was reused"


def test_a_take_with_no_face_found_goes_to_the_eye_again_and_is_not_paid_for_twice(live, monkeypatch, tmp_path):
    """No face where she was expected is a flag for the eye, not a failure, though its reading is
    written with passed false. A stale failed list that names the scene reuses the take and flags
    it again rather than paying for it a second time."""
    tk, state = live
    monkeypatch.setenv("CLOSER_FROM", str(closer_take(tmp_path)))
    vendor = Vendor(reject={"fal-2"})
    monkeypatch.setattr(L, "http", vendor)
    answers = {"zai-a": SAME, "zai-b": SAME, "zai-c": NO_FACE}
    monkeypatch.setattr(L.LiveToolkit, "script", scripts(cast=by_scene(answers)))
    first = tk.render(cast_state(state))
    assert first["failed"] == ["b"] and "c" in first["flags"], first
    vendor.reject = set()
    posts = len(vendor.posts())
    again = tk.render(dict(cast_state(state), verdict={"render": dict(first, failed=["b", "c"])}))
    assert again["failed"] == [] and "c" in again["flags"] and len(vendor.posts()) == posts + 1, again


def test_a_take_that_landed_but_was_never_read_back_is_read_now_not_sent_again(live, monkeypatch, tmp_path):
    """The process can die between a take landing and its read-back. The failed reading of an older
    take is not this take's, so a re-entry reuses the new take and reads it, rather than paying again."""
    tk, state = live
    monkeypatch.setenv("CLOSER_FROM", str(closer_take(tmp_path)))
    vendor = Vendor()
    monkeypatch.setattr(L, "http", vendor)
    answers = {"zai-a": SAME, "zai-b": SAME, "zai-c": OTHER}
    monkeypatch.setattr(L.LiveToolkit, "script", scripts(cast=by_scene(answers)))
    first = tk.render(cast_state(state))
    assert first["failed"] == ["c"], first
    answers["zai-c"] = None
    with pytest.raises(KeyboardInterrupt):
        tk.render(dict(cast_state(state), verdict={"render": first}))
    answers["zai-c"] = SAME
    posts = len(vendor.posts())
    again = L.LiveToolkit(state["run_dir"], tk.ledger.run_id).render(dict(cast_state(state), verdict={"render": first}))
    assert again["failed"] == [] and len(vendor.posts()) == posts, "a take that landed was paid for again"
    assert [r["scene"] for r in tk.ledger.rows() if r.get("status") == "REUSED"] == ["zai-c"]


def test_a_take_its_read_back_failed_is_rendered_again_whatever_the_checkpoint_says(live, monkeypatch, tmp_path):
    """A re-entry can resume from a checkpoint older than the read-back that failed a take, whose
    failed list is empty. The ledger still says the take is not her, so it is rendered again, and
    the scenes that passed are reused."""
    tk, state = live
    monkeypatch.setenv("CLOSER_FROM", str(closer_take(tmp_path)))
    vendor = Vendor()
    monkeypatch.setattr(L, "http", vendor)
    answers = {"zai-a": SAME, "zai-b": SAME, "zai-c": OTHER}
    monkeypatch.setattr(L.LiveToolkit, "script", scripts(cast=by_scene(answers)))
    assert tk.render(cast_state(state))["failed"] == ["c"]
    answers["zai-c"] = SAME
    posts = len(vendor.posts())
    again = L.LiveToolkit(state["run_dir"], tk.ledger.run_id).render(cast_state(state))
    assert again["failed"] == [] and again["fresh"] == ["c"] and len(vendor.posts()) == posts + 1, again
    assert [r["scene"] for r in tk.ledger.rows() if r.get("status") == "REUSED"] == ["zai-a", "zai-b"]


def test_a_scene_a_person_sends_back_is_rendered_again_even_on_its_old_prompt(live, monkeypatch, tmp_path):
    """The eye can send a scene back without rewriting its prompt. The take on file then landed and
    passed, and it is still not reused, because a person asked for a new one."""
    tk, state = live
    monkeypatch.setenv("CLOSER_FROM", str(closer_take(tmp_path)))
    vendor = Vendor()
    monkeypatch.setattr(L, "http", vendor)
    monkeypatch.setattr(L.LiveToolkit, "script", scripts())
    first = tk.render(cast_state(state))
    assert first["failed"] == [], first
    posts = len(vendor.posts())
    again = tk.render(dict(cast_state(state), verdict={"render": first}, changes={"scene": "a", "reason": "a prop cut"}))
    assert again["fresh"] == ["a"] and len(vendor.posts()) == posts + 1, again
    assert not [r for r in tk.ledger.rows() if r.get("status") == "REUSED"], "the scene a person sent back was reused"


def test_a_cast_reading_its_exit_code_contradicts_is_no_reading(live, monkeypatch):
    tk, _ = live
    monkeypatch.setattr(L.LiveToolkit, "script", scripts(cast=(0, OTHER[1])))
    verdict, said, _ = tk.cast("reference.jpg", "clip.mp4")
    assert verdict is None and "verdict=FAIL" in said, (verdict, said)
    # A reading from before the gate read a second face still parses, and one that skipped the
    # narrator it was asked to read is no reading.
    older = (0, "CAST_GATE faces=3 sim=0.46 min=0.44 strangers=0 floor=0.30 verdict=PASS")
    monkeypatch.setattr(L.LiveToolkit, "script", scripts(cast=older))
    assert tk.cast("reference.jpg", "clip.mp4")[0] == "PASS"
    assert tk.cast("reference.jpg", "clip.mp4", other="narrator.jpg")[0] is None
    monkeypatch.setattr(L.LiveToolkit, "script", scripts(cast=SAME))
    assert tk.cast("reference.jpg", "clip.mp4", other="narrator.jpg")[2]["other"] == "0.10"


def test_a_new_prompt_with_a_stranger_in_it_is_not_sent(live, monkeypatch):
    """The board gate never reads a person's replacement prompt. One that names someone else would
    render on the plain path, where no cast gate reads it back, so it is refused before any spend."""
    tk, state = live
    vendor = Vendor()
    monkeypatch.setattr(L, "http", vendor)
    monkeypatch.setattr(L.LiveToolkit, "script", scripts())
    asked = dict(cast_state(state), changes={"scene": "a", "prompt": "A woman wipes the counter. Mouth closed, nobody speaks."})
    v = tk.render(asked)
    assert v["failed"] == ["a"] and "{character}" in v["why"]["a"], v
    narrator = dict(cast_state(state), changes={"scene": "a", "prompt": "{presenter} sits at the desk. Mouth closed."})
    assert tk.render(narrator)["failed"] == ["a"], "the narrator was written into a story scene"
    assert not vendor.posts(), "a prompt with a stranger in it was paid for"


def test_every_scene_is_read_back_and_a_stranger_fails_where_no_word_named_one(live, monkeypatch):
    """The board gate reads words, and a barista or a crowd is not one of them. So every scene is
    read back, and with no character in the spot it is read against the narrator's face. A face
    that is not hers fails the scene, and a scene that holds no face at all is what it should be."""
    tk, state = live
    monkeypatch.setattr(L, "http", Vendor())
    stranger = (1, CG.line([0.05] * 8))
    run = scripts(cast=lambda clip: stranger if "zai-b" in clip else (3, CG.line([])) if "zai-c" in clip else SAME)
    monkeypatch.setattr(L.LiveToolkit, "script", run)
    board = dict(state, board=BOARD)
    v = tk.render(board)
    assert v["failed"] == ["b"] and "the board never named" in v["why"]["b"], v
    assert "c" not in v["flags"], "a scene with nobody in it was sent to the eye for having nobody in it"
    read = [c[0][2] for c in calls_to(run, "gates/cast_gate.py") if c[0][1] != "--reference"]
    assert len(read) == 3, f"scenes read back against the narrator: {read}"


def test_a_stranger_behind_her_fails_the_scene_and_says_so(live, monkeypatch, tmp_path):
    """Her face matched and a second person stood behind her. The scene fails, and the reason
    names the second person rather than a mismatch that did not happen."""
    tk, state = live
    monkeypatch.setenv("CLOSER_FROM", str(closer_take(tmp_path)))
    monkeypatch.setattr(L, "http", Vendor())
    behind = (1, CG.line([0.5] * 8, strangers=3))
    monkeypatch.setattr(L.LiveToolkit, "script", scripts(cast=lambda clip: behind if "zai-a" in clip else SAME))
    v = tk.render(cast_state(state))
    assert v["failed"] == ["a"] and v["why"]["a"].startswith("a second person on screen"), v


def test_the_closer_is_read_back_against_the_narrators_face(live, monkeypatch, tmp_path):
    tk, state = live
    monkeypatch.setenv("CLOSER_FROM", str(closer_take(tmp_path)))
    os.makedirs(os.path.join(tk.takes, "zai-presenter"))
    open(os.path.join(tk.takes, "zai-presenter", "reference.jpg"), "wb").write(b"a presenter's face")
    monkeypatch.setattr(L.LiveToolkit, "script", scripts(cast=OTHER))
    v = tk.closer(cast_state(state))
    assert v["pass"] is False and v["why"] == "the closer is not the narrator whose face the run holds", v
    assert [r["passed"] for r in tk.ledger.rows() if r.get("check") == "cast"] == [False]
    os.remove(os.path.join(tk.takes, "zai-av", "render.mp4"))
    monkeypatch.setattr(L.LiveToolkit, "script", scripts(cast=SAME))
    assert tk.closer(cast_state(state))["pass"] is True
    os.remove(os.path.join(tk.takes, "zai-av", "render.mp4"))
    monkeypatch.setattr(L.LiveToolkit, "script", scripts(cast=(64, "CAST_GATE unreadable: the reference holds no face")))
    v = tk.closer(cast_state(state))
    assert v["pass"] is False and v["unreadable"] is True, v


# a chain: each scene shot from a frame, in order

CHAIN_BOARD = os.path.join(ROOT, "shoots", "graph-zai-chain", "boards.json")
FRAME_ENGINE = "google/gemini-omni-flash/image-to-video"


def chain_state(state, **extra):
    return dict(state, board=CHAIN_BOARD, **extra)


def takes_and_frames(monkeypatch):
    """Every download is a new take, and a take's last frame says which take it came from, so a
    frame handed on can be traced to the take it was taken from. A still is its own frame."""
    count = [0]

    def fetch(url, path):
        count[0] += 1
        open(path, "wb").write(b"take %d" % count[0])

    def grab(src, out, last=False):
        data = open(src, "rb").read()
        open(out, "wb").write(b"last frame of " + data if last else data)
        return True
    monkeypatch.setattr(L.urllib.request, "urlretrieve", fetch)
    monkeypatch.setattr(L, "grab_frame", grab)


def started_from(vendor_bodies):
    return [L.base64.b64decode(b["image_url"].split(",", 1)[1]) for b in vendor_bodies]


def sha(data):
    return hashlib.sha256(data).hexdigest()


def test_a_chain_is_shot_in_order_each_scene_from_the_frame_before_it(live, monkeypatch, tmp_path):
    """The face reference kept her the same and copied its own close-up into every scene. A chained
    spot starts its first scene from a whole still of her and every later scene from the last frame
    of the one before, on the path that starts from a frame. Each scene is sent only after the one
    before it landed and was read back, the request names the frame by hash and never carries it,
    and the prompt names her, since the frame carries her face."""
    tk, state = live
    monkeypatch.setenv("CLOSER_FROM", str(closer_take(tmp_path)))
    takes_and_frames(monkeypatch)
    sent = []
    vendor = Vendor(on_post=lambda url, body: sent.append((json.loads(body), [dict(r) for r in tk.ledger.rows()]))
                    if "queue" in url else None)
    monkeypatch.setattr(L, "http", vendor)
    monkeypatch.setattr(L.LiveToolkit, "script", scripts())
    v = tk.render(chain_state(state))
    assert v["failed"] == [] and v["fresh"] == ["a", "b", "c"] and v["rendered"] == ["a", "b", "c"], v
    assert vendor.posts() == [f"{L.FAL}/{FRAME_ENGINE}"] * 3, vendor.posts()
    bodies = [b for b, _ in sent]
    assert started_from(bodies) == [b"the character's still", b"last frame of take 1", b"last frame of take 2"]
    assert all("image_urls" not in b and "the student" in b["prompt"] and "<IMAGE_REF_0>" not in b["prompt"]
               and "{character}" not in b["prompt"] for b in bodies), bodies
    for i, scene in ((1, "zai-a"), (2, "zai-b")):
        before = sent[i][1]
        assert any(r["kind"] == "landing" and r.get("status") == "OK" and r.get("file") == f"takes/{scene}/raw.mp4"
                   for r in before), f"the scene after {scene} was sent before {scene} landed"
        assert any(r["kind"] == "gate" and r.get("check") == "cast" and r.get("scene") == scene for r in before), \
            f"the scene after {scene} was sent before {scene} was read back"
    rows = tk.ledger.rows()
    requests = [r for r in rows if r["kind"] == "request" and r.get("scene")]
    assert [r["start_from"] for r in requests] == ["the character's still", "the last frame of zai-a",
                                                    "the last frame of zai-b"], requests
    assert [r["start_sha256"] for r in requests] == [sha(b"the character's still"), sha(b"last frame of take 1"),
                                                      sha(b"last frame of take 2")], requests
    assert all(r["engine"] == FRAME_ENGINE and "reference_sha256" not in r for r in requests), requests
    assert "data:image" not in ledger_text(tk), "a frame itself reached the ledger"
    still = [r for r in rows if r.get("note") == "the character's still"]
    assert len(still) == 1 and still[0]["source"] == "still" and still[0]["file"] == "takes/zai-character/still.jpg"


def test_a_chain_stops_at_the_first_scene_that_fails_and_the_rest_wait_without_a_re_roll(live, monkeypatch, tmp_path):
    """A scene that fails is the last one paid for in the pass. The scenes after it would start
    from a frame of a take that is going to be thrown away, so they are not sent, they say what
    they wait on, and they are not counted as failed, so none of their re-rolls is spent. The
    re-roll shoots the failed scene again and the rest of the chain after it."""
    tk, state = live
    monkeypatch.setenv("CLOSER_FROM", str(closer_take(tmp_path)))
    takes_and_frames(monkeypatch)
    vendor = Vendor()
    monkeypatch.setattr(L, "http", vendor)
    answers = {"zai-a": OTHER, "zai-b": SAME, "zai-c": SAME}
    monkeypatch.setattr(L.LiveToolkit, "script", scripts(cast=by_scene(answers)))
    first = tk.render(chain_state(state))
    assert first["failed"] == ["a"] and len(vendor.posts()) == 1, first
    assert first["why"]["b"] == first["why"]["c"] == "waits on zai-a, the scene it starts from", first["why"]
    assert first["rendered"] == ["a"], first
    assert not [r for r in tk.ledger.rows() if r["kind"] == "request" and r.get("scene") in ("zai-b", "zai-c")]
    answers["zai-a"] = SAME
    again = tk.render(chain_state(state, verdict={"render": first}))
    assert again["failed"] == [] and again["fresh"] == ["a", "b", "c"] and len(vendor.posts()) == 4, again


def test_a_new_take_early_in_a_chain_renders_every_scene_after_it_again(live, monkeypatch, tmp_path):
    """A chained take is kept only when it started from the frame its scene would start from now.
    When a person sends scene a back, a comes back as a new take, so b and c start from new frames
    and are shot again, each request saying why, and none of the old takes is reused."""
    tk, state = live
    monkeypatch.setenv("CLOSER_FROM", str(closer_take(tmp_path)))
    takes_and_frames(monkeypatch)
    vendor = Vendor()
    monkeypatch.setattr(L, "http", vendor)
    monkeypatch.setattr(L.LiveToolkit, "script", scripts())
    first = tk.render(chain_state(state))
    assert first["failed"] == [] and len(vendor.posts()) == 3, first
    again = tk.render(chain_state(state, verdict={"render": first},
                                  changes={"scene": "a", "reason": "the room never expands"}))
    assert again["failed"] == [] and again["fresh"] == ["a", "b", "c"] and len(vendor.posts()) == 6, again
    requests = [r for r in tk.ledger.rows() if r["kind"] == "request" and r.get("scene")][3:]
    assert [r["why"] for r in requests] == ["the room never expands", "the frame it starts from changed",
                                            "the frame it starts from changed"], requests
    assert [r["start_sha256"] for r in requests][1:] == [sha(b"last frame of take 4"), sha(b"last frame of take 5")]
    assert not [r for r in tk.ledger.rows() if r.get("status") == "REUSED"], "a take from an old frame was kept"


def test_a_re_entry_keeps_a_chain_whose_frames_still_match(live, monkeypatch, tmp_path):
    """A re-entry walks the chain again. Every take started from the frame its scene would start from
    now, so every one is kept and read again, and nothing is paid for twice."""
    tk, state = live
    monkeypatch.setenv("CLOSER_FROM", str(closer_take(tmp_path)))
    takes_and_frames(monkeypatch)
    vendor = Vendor()
    monkeypatch.setattr(L, "http", vendor)
    monkeypatch.setattr(L.LiveToolkit, "script", scripts())
    assert tk.render(chain_state(state))["failed"] == []
    again = L.LiveToolkit(state["run_dir"], tk.ledger.run_id).render(chain_state(state))
    assert again["failed"] == [] and again["fresh"] == [] and len(vendor.posts()) == 3, again
    assert [r["scene"] for r in tk.ledger.rows() if r.get("status") == "REUSED"] == ["zai-a", "zai-b", "zai-c"]
    assert len([r for r in tk.ledger.rows() if r.get("note") == "the character's still"]) == 1, "the still was taken twice"


def test_a_failed_read_back_early_in_a_chain_throws_away_the_takes_after_it(live, monkeypatch, tmp_path):
    """On a re-entry, a take that is read again and now fails stops the chain there, and when it is
    shot again the takes after it are shot again too, since their frames came from the take that
    failed. The checkpoint never decides this, the frames do."""
    tk, state = live
    monkeypatch.setenv("CLOSER_FROM", str(closer_take(tmp_path)))
    takes_and_frames(monkeypatch)
    vendor = Vendor()
    monkeypatch.setattr(L, "http", vendor)
    answers = {"zai-a": SAME, "zai-b": SAME, "zai-c": SAME}
    monkeypatch.setattr(L.LiveToolkit, "script", scripts(cast=by_scene(answers)))
    assert tk.render(chain_state(state))["failed"] == []
    answers["zai-a"] = OTHER
    stopped = L.LiveToolkit(state["run_dir"], tk.ledger.run_id).render(chain_state(state))
    assert stopped["failed"] == ["a"] and len(vendor.posts()) == 3, stopped
    assert stopped["why"]["b"] == "waits on zai-a, the scene it starts from", stopped
    answers["zai-a"] = SAME
    again = tk.render(chain_state(state, verdict={"render": stopped}))
    assert again["failed"] == [] and again["fresh"] == ["a", "b", "c"] and len(vendor.posts()) == 6, again


def test_a_chain_with_no_character_still_stops_before_anything_is_sent(live, monkeypatch, tmp_path):
    tk, state = live
    monkeypatch.setenv("CLOSER_FROM", str(closer_take(tmp_path)))
    vendor = Vendor()
    monkeypatch.setattr(L, "http", vendor)
    monkeypatch.setattr(L.LiveToolkit, "script", scripts())
    monkeypatch.setattr(L, "grab_frame", lambda src, out, last=False: False)
    with pytest.raises(L.LiveSetupError, match="nothing to start from"):
        tk.render(chain_state(state))
    assert vendor.calls == [], "something was sent for a chain with no frame to start from"


def test_a_chained_request_the_vendor_never_confirmed_holds_the_chain_until_a_person_re_enters(live, monkeypatch, tmp_path):
    """A chained POST that failed on the network may still have been billed. It stops the chain for
    a person, the scenes after it wait, the narration is not drawn, the next pass sends nothing,
    and only a re-entry sends it once more, from the same frame, and the rest of the chain after it."""
    tk, state = live
    monkeypatch.setenv("CLOSER_FROM", str(closer_take(tmp_path)))
    takes_and_frames(monkeypatch)
    vendor = Vendor(post_fail={2})
    monkeypatch.setattr(L, "http", vendor)
    run = scripts()
    monkeypatch.setattr(L.LiveToolkit, "script", run)
    v = tk.render(chain_state(state))
    assert v["unconfirmed"] == ["b"] and v["failed"] == [] and len(vendor.posts()) == 2, v
    assert v["why"]["c"] == "waits on zai-b, the scene it starts from", v["why"]
    assert not calls_to(run, "gates/voice_take.sh"), "the narration was paid for behind an unconfirmed request"
    again = tk.render(chain_state(state, verdict={"render": v}))
    assert again["unconfirmed"] == ["b"] and len(vendor.posts()) == 2, "an unconfirmed chained request was sent again"
    tk.ledger.append("resumed", "render", reason="checked the queue, nothing there", trail=[])
    vendor.post_fail = set()
    after = tk.render(chain_state(state, verdict={"render": v}))
    assert after["unconfirmed"] == [] and after["failed"] == [] and len(vendor.posts()) == 4, after
    requests = [r for r in tk.ledger.rows() if r["kind"] == "request" and r.get("scene") == "zai-b"]
    assert len({r["start_sha256"] for r in requests}) == 1, "b was sent again from another frame"


def test_a_chained_job_sent_before_a_crash_is_collected_on_the_re_entry_not_paid_for_again(live, monkeypatch, tmp_path):
    """The process died while scene a was rendering. On the re-entry a is still owed from the same
    frame, so it is collected, and the chain goes on from its last frame."""
    tk, state = live
    monkeypatch.setenv("CLOSER_FROM", str(closer_take(tmp_path)))
    takes_and_frames(monkeypatch)
    vendor = Vendor(die_on_status=True)
    monkeypatch.setattr(L, "http", vendor)
    monkeypatch.setattr(L.LiveToolkit, "script", scripts())
    with pytest.raises(KeyboardInterrupt):
        tk.render(chain_state(state))
    assert len(vendor.posts()) == 1
    vendor.die_on_status = False
    v = L.LiveToolkit(state["run_dir"], tk.ledger.run_id).render(chain_state(state))
    assert v["failed"] == [] and v["fresh"] == ["a", "b", "c"] and len(vendor.posts()) == 3, v


def test_a_chained_job_the_vendor_dropped_is_sent_again_from_the_same_frame(live, monkeypatch, tmp_path):
    tk, state = live
    monkeypatch.setenv("CLOSER_FROM", str(closer_take(tmp_path)))
    takes_and_frames(monkeypatch)
    vendor = Vendor(die_on_status=True)
    monkeypatch.setattr(L, "http", vendor)
    monkeypatch.setattr(L.LiveToolkit, "script", scripts())
    with pytest.raises(KeyboardInterrupt):
        tk.render(chain_state(state))
    vendor.die_on_status, vendor.dropped = False, {"fal-1"}
    v = L.LiveToolkit(state["run_dir"], tk.ledger.run_id).render(chain_state(state))
    assert v["failed"] == [] and v["fresh"] == ["a", "b", "c"] and len(vendor.posts()) == 4, v
    a = [r for r in tk.ledger.rows() if r["kind"] == "request" and r.get("scene") == "zai-a"]
    assert len(a) == 2 and a[0]["start_sha256"] == a[1]["start_sha256"], a
    assert [r for r in tk.ledger.rows() if r.get("error") == "the vendor no longer has this job"], "the drop was not recorded"
