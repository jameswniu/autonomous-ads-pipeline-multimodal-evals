"""The August ledgers replayed against the graph, pinned.

pipeline/replay.py reads the seven hand-written ledgers and reports what they record as
graph transitions, what the graph could not have written, where a loop ran past a bound
the graph now enforces, and what the ledgers never recorded. History does not change, so
every one of those lists is pinned here, and every move down to the row that states it. A
new divergence, a transition the graph lacks, a row that changes class, or a gap that
quietly closes all fail the suite, and each needs a deliberate edit here.
"""
import collections
import hashlib
import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

pytest.importorskip("langgraph")

from pipeline import graph as G  # noqa: E402
from pipeline import replay as R  # noqa: E402

MOVES = {
    "ads2-redo": {"render->render": 2},
    "ads3": {"render->render": 2},
    "ads4": {"eye->render": 2, "ledger->board": 4, "render->render": 2, "ship_gate->deliver": 4},
    "ads5": {"ad_gates->eye": 3, "eye->render": 3, "ledger->board": 4, "review->render": 1,
             "ship_gate->deliver": 4},
    "ads6-omni": {"ad_gates->eye": 2, "eye->render": 3},
    "ads7-real": {"deliver->review": 13, "review->closer": 13},
    "ads8-real": {"eye->render": 3},
}


def _rows(shoot, name, *lines):
    return [f"shoots/{shoot}/{name}:{n}" for n in lines]


# Which rows state each move, in the order the replay reads them. MOVES counts them and this
# names them, so a row that changes class fails here even when every count still adds up.
# ledger->board is left out because it is a cross-run edge the replay always allows, so taking
# it away from the compiled graph cannot unmap it.
ADS7_WITHDRAWN = _rows("ads7-real", "landings.jsonl", *[6] * 4, *[7] * 4, *[8] * 5)
ROW_MOVES = {
    ("render", "render"): (_rows("ads2-redo", "requests.jsonl", 46, 47) + _rows("ads3", "requests.jsonl", 13, 14)
                           + _rows("ads4", "requests.jsonl", 13, 14)),
    ("eye", "render"): (_rows("ads4", "requests.jsonl", 15, 16) + _rows("ads5", "requests.jsonl", 9, 10, 11)
                        + _rows("ads6-omni", "requests.jsonl", 13, 14, 15)
                        + _rows("ads8-real", "requests.jsonl", 24, 25, 26)),
    ("review", "render"): _rows("ads5", "requests.jsonl", 12),
    ("ad_gates", "eye"): _rows("ads5", "landings.jsonl", 6, 8, 9) + _rows("ads6-omni", "landings.jsonl", 2, 4),
    ("ship_gate", "deliver"): _rows("ads4", "landings.jsonl", 1, 2, 3, 4) + _rows("ads5", "landings.jsonl", 1, 2, 3, 4),
    ("deliver", "review"): ADS7_WITHDRAWN,
    ("review", "closer"): ADS7_WITHDRAWN,
}

ADS7_DELIVERED = ("chatgpt v1, chatgpt v2, chatgpt v3, chatgpt v4, gemini v1, gemini v2, gemini v3, gemini v4, "
                  "metaai v1, metaai v2, metaai v3, metaai v4, perplexity v1, perplexity v4, "
                  "pics v1, pics v2, pics v3, pics v4")
ADS7_UNGATED = ("chatgpt v2, chatgpt v3, chatgpt v4, gemini v2, gemini v3, gemini v4, "
                "metaai v2, metaai v3, metaai v4, perplexity v4, pics v2, pics v3, pics v4")
DIVERGENCES = {
    "ads3": ["4 ship-gate passes with no ad-gate reading on the record: harbor, lantern, orchard, slowroad"],
    "ads4": ["4 ship-gate passes with no ad-gate reading on the record: harbor, lantern, orchard, slowroad"],
    "ads5": ["4 unversioned ship-gate passes written above all 6 ad-gate readings (lines 1-4 before 5-10), "
             "so no gated master has a pass recorded after its reading"],
    "ads7-real": [f"18 deliveries with no ship-gate pass on the record: {ADS7_DELIVERED}",
                  f"13 of them with no gate reading at all: {ADS7_UNGATED}",
                  "past a REVIEW with no eye verdict on the record: chatgpt, perplexity, pics"],
}

OVER_BOUND = {
    "ads4": ["harbor sent back 2 times before shipping for what a scene showed, actor not recorded on 2",
             "orchard-c on Seedance 2.0 re-rolled 2 times, reason not recorded"],
    "ads6-omni": ["harbor sent back 2 times before shipping for what a scene showed, actor not recorded on 1"],
    "ads8-real": ["grok sent back 2 times before shipping for what a scene showed, actor not recorded on 1"],
}

OUTSIDE = {
    "ads3": ["2 music-bed requests; the graph reuses a bed and has no step that makes one",
             "4 delivered cuts moved or re-posted in the delivery channel, which the graph, "
             "delivering locally, does not model"],
    "ads7-real": ["1 delivered cut moved or re-posted in the delivery channel, which the graph, "
                  "delivering locally, does not model"],
    "ads8-real": ["8 music-bed requests; the graph reuses a bed and has no step that makes one"],
}

EVERYWHERE = {"board verdict", "build parameters", "landings", "request ids", "ship-gate readings",
              "time of day", "voice take"}
NEVER = {
    "ads2-redo": EVERYWHERE | {"closer render", "delivery"},
    "ads3": EVERYWHERE | {"earlier rolls"},
    "ads4": EVERYWHERE | {"closer render"},
    "ads5": EVERYWHERE | {"earlier builds", "earlier rolls", "who approved"},
    "ads6-omni": EVERYWHERE | {"closer render", "delivery", "earlier builds", "earlier rolls", "who approved"},
    "ads7-real": EVERYWHERE | {"closer render"},
    "ads8-real": EVERYWHERE | {"closer render", "delivery"},
}

# A complete trail through the graph, for doctored runs that need one.
DELIVERED_TRAIL = ["board", "render", "closer", "build", "ad_gates", "eye", "ship_gate", "deliver", "review", "ledger"]


@pytest.fixture(scope="module")
def everything():
    return R.replay_all()


@pytest.fixture(scope="module")
def results(everything):
    """The August shoots, the ledgers an agent wrote by hand."""
    return {s: r for s, r in everything.items() if not r.get("graph")}


def _graph_run(tmp_path, monkeypatch, rows, name="doctored"):
    """Write rows as the ledger of a graph run, numbered from seq 1, and replay it."""
    shoot = tmp_path / name
    shoot.mkdir()
    envelope = {"schema": 1, "run": "doctored", "ts": "2026-09-24T01:00:00.000+00:00"}  # pii-allow: fixture time
    (shoot / "ledger.jsonl").write_text("".join(json.dumps({**envelope, "seq": i, **r}) + "\n"
                                                for i, r in enumerate(rows, 1)))
    monkeypatch.setattr(R, "SHOOTS", str(tmp_path))
    return R.replay_graph_run(name)


def _august(tmp_path, monkeypatch, name, requests=(), landings=()):
    """Write rows as a hand-written August shoot and replay it."""
    shoot = tmp_path / name
    shoot.mkdir()
    for file, rows in (("requests.jsonl", requests), ("landings.jsonl", landings)):
        if rows:
            (shoot / file).write_text("".join(json.dumps(r) + "\n" for r in rows))
    monkeypatch.setattr(R, "SHOOTS", str(tmp_path))
    return R.replay_shoot(name)


def test_the_replay_covers_every_shoot(everything):
    august = sorted(s for s, r in everything.items() if not r.get("graph"))
    assert august == sorted(MOVES), august
    for shoot, res in everything.items():
        assert res.get("graph") or shoot in MOVES, f"{shoot} is neither a pinned August shoot nor a graph run"


def test_every_run_the_graph_wrote_is_complete(everything):
    """What the August ledgers never recorded is what the graph writes on every run, so a
    graph run must replay with every move an edge, no divergence and nothing missing."""
    graph_runs = {s: r for s, r in everything.items() if r.get("graph")}
    for shoot, res in graph_runs.items():
        assert res["moves"], f"{shoot} recorded no trail"
        assert not res["unmapped"], (shoot, res["unmapped"])
        assert not res["divergences"], (shoot, res["divergences"])
        assert res["never"] == {}, (shoot, res["never"])


def test_a_graph_ledger_missing_what_the_schema_promises_is_caught(tmp_path, monkeypatch):
    """Break test for the check above: a doctored graph ledger with a placeholder id, a
    request that never landed, a row with no time, and a delivery with no ship-gate pass."""
    shoot = tmp_path / "doctored"
    shoot.mkdir()
    rows = [
        {"seq": 1, "ts": "2026-09-24T01:00:00.000+00:00", "kind": "gate", "step": "board", "pass": True},  # pii-allow: fixture time
        {"seq": 2, "ts": "2026-09-24", "kind": "request", "step": "render", "request_id": "<request-id>",
         "engine": "google/gemini-omni-flash"},
        {"seq": 3, "ts": "2026-09-24T01:00:02.000+00:00", "kind": "request", "step": "render",  # pii-allow: fixture time
         "request_id": "req_abc", "engine": "elevenlabs/eleven_v3"},
        {"seq": 4, "ts": "2026-09-24T01:00:03.000+00:00", "kind": "deliver", "step": "deliver"},  # pii-allow: fixture time
        {"seq": 5, "ts": "2026-09-24T01:00:04.000+00:00", "kind": "close", "step": "ledger",  # pii-allow: fixture time
         "trail": ["board", "render", "closer", "build", "ad_gates", "ship_gate", "deliver", "review", "ledger"]},
    ]
    (shoot / "ledger.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    monkeypatch.setattr(R, "SHOOTS", str(tmp_path))
    res = R.replay_graph_run("doctored")
    assert set(res["never"]) >= {"request ids", "landings", "time of day", "build parameters", "ship-gate readings"}
    assert res["divergences"] == ["a delivery at seq 4 with no ship-gate pass before it"]
    assert not res["unmapped"]
    res = R.replay_graph_run("doctored", edges=G.edges() - {("deliver", "review")})
    assert [m[:2] for m in res["unmapped"]] == [("deliver", "review")]


def test_a_move_off_the_graph_in_any_stint_is_caught(tmp_path, monkeypatch):
    """A run stopped and resumed has a trail for every stint. A move off the graph in the
    first stint is reported even when the stint that ended the run is clean."""
    res = _graph_run(tmp_path, monkeypatch, [
        {"kind": "gate", "step": "board", "pass": True},
        {"kind": "close", "step": "ledger", "trail": ["board", "render", "deliver", "review", "ledger"]},
        {"kind": "resumed", "step": "render", "reason": "the render step was fixed", "trail": ["board"]},
        {"kind": "close", "step": "ledger", "trail": ["board", "render", "ledger"]},
    ])
    assert res["unmapped"] == [("render", "deliver", "shoots/doctored/ledger.jsonl:2")]
    assert res["trail"] == ["board", "render", "ledger"]


def test_an_answer_with_no_name_is_never_recorded(tmp_path, monkeypatch):
    """The eye and the review are a person's word, so an answer with no name on it is an
    approval nobody signed. A named answer beside it is not counted."""
    res = _graph_run(tmp_path, monkeypatch, [
        {"kind": "eye", "step": "eye", "verdict": "approve", "who": None, "answer": {"verdict": "approve"}},
        {"kind": "review", "step": "review", "verdict": "keep", "who": "reviewer", "answer": {"verdict": "keep"}},
        {"kind": "close", "step": "ledger", "trail": DELIVERED_TRAIL},
    ])
    assert res["never"]["who approved"] == "1 answers carry no name"


def test_a_local_path_or_a_raw_identity_id_in_a_graph_row_diverges(tmp_path, monkeypatch):
    """pipeline/SCHEMA.md: paths are relative to the run directory, and a voice or a look is
    written as its sha256: fingerprint, never as the id. A row that breaks either is found at
    any depth, while a fingerprint or an empty value is not."""
    res = _graph_run(tmp_path, monkeypatch, [
        {"kind": "landing", "step": "render", "file": "/Users/x/takes/zai-a/raw.mp4"},
        {"kind": "gate", "step": "closer", "check": "jaw", "passed": True, "look": "3f2c9a7e51d04b6f"},
        {"kind": "eye", "step": "eye", "who": "reviewer", "answer": {"verdict": "reject", "look": "3f2c9a7e51d04b6f"}},
        {"kind": "gate", "step": "closer", "check": "jaw", "passed": True, "look": "sha256:0123456789ab",
         "voice": None},
        {"kind": "gate", "step": "ship_gate", "pass": False, "said": ["slit-scan: /tmp/slit-zai-v1.mp4.png"]},
        {"kind": "waiting", "step": "eye", "trail": ["board", "render", "closer", "build", "ad_gates", "eye"]},
    ])
    assert res["divergences"] == ["row seq 1 carries a local path",
                                  "row seq 2 carries an identity id where its fingerprint belongs",
                                  "row seq 3 carries an identity id where its fingerprint belongs",
                                  "row seq 5 carries a local path"]


def test_a_resumed_row_is_a_reentry_by_hand(tmp_path, monkeypatch):
    """A person re-entering a stopped run is outside the graph. It is listed with its reason
    and any wait it abandoned, its trail is not read as moves, and only a close or a crash
    counts as a stop."""
    res = _graph_run(tmp_path, monkeypatch, [
        {"kind": "close", "step": "ledger", "trail": ["board", "render", "closer", "build", "ledger"]},
        {"kind": "resumed", "step": "build", "reason": "the crop was fixed", "abandoned": None,
         "trail": ["board", "render", "closer"]},
        {"kind": "crashed", "step": "build", "error": "OSError: disk full",
         "trail": ["board", "render", "closer", "build"]},
        {"kind": "resumed", "step": "build", "reason": "space was freed", "trail": ["board", "render", "closer"]},
        {"kind": "waiting", "step": "eye", "trail": ["board", "render", "closer", "build", "ad_gates", "eye"]},
        {"kind": "resumed", "step": "ship_gate", "reason": "the probe read the closer, not the master",
         "abandoned": "eye", "trail": ["board", "render", "closer", "build", "ad_gates"]},
        {"kind": "close", "step": "ledger", "trail": ["board", "render", "closer", "build", "ad_gates", "ship_gate",
                                                     "ledger"]},
    ])
    assert res["reentries"] == ["seq 2, before build: the crop was fixed",
                                "seq 4, before build: space was freed",
                                "seq 6, before ship_gate: the probe read the closer, not the master, "
                                "abandoning a wait for the eye"]
    assert res["stops"] == 3
    assert {m[2] for m in res["moves"]} == {f"shoots/doctored/ledger.jsonl:{seq}" for seq in (1, 3, 5, 7)}


def test_every_recorded_transition_is_a_graph_edge(results):
    unmapped = [m for res in results.values() for m in res["unmapped"]]
    assert not unmapped, unmapped


def test_the_transitions_read_from_each_ledger_are_pinned(results):
    got = {s: dict(sorted(collections.Counter(f"{a}->{b}" for a, b, _ in r["moves"]).items()))
           for s, r in results.items()}
    assert got == MOVES, got


def test_the_divergences_are_the_known_ones(results):
    got = {s: r["divergences"] for s, r in results.items() if r["divergences"]}
    assert got == DIVERGENCES, got


def test_the_loops_past_a_bound_are_the_known_ones(results):
    got = {s: r["over_bound"] for s, r in results.items() if r["over_bound"]}
    assert got == OVER_BOUND, got


def test_the_reroll_rules_no_august_row_exercises(tmp_path, monkeypatch):
    """No August re-roll says it failed to come back, no author send-back falls on the day of
    a delivery, and the one after a delivery follows its own spot's, so the real rows cannot
    tell these rules from their near misses. These rows can. A failure is the render step's
    own retry, a delivery the same day is not before, another spot's delivery does not count,
    and send-backs past the eye's bound that all name the author print no actor clause."""
    one, two = "2026-09-01", "2026-09-02"
    res = _august(tmp_path, monkeypatch, "adsZ", requests=[
        {"ts": one, "scene": "cove-a", "engine": "omni", "id": "<request-id>"},
        {"ts": one, "scene": "cove-a", "engine": "omni", "roll": 2, "why": "422 from the vendor", "id": "<request-id>"},
        {"ts": one, "scene": "cove-a", "engine": "omni", "roll": 3, "why": "Timed out, no video", "id": "<request-id>"},
        {"ts": one, "scene": "dune-a", "engine": "omni", "id": "<request-id>"},
        {"ts": one, "scene": "dune-a", "engine": "omni", "roll": 2, "why": "the author: reads as a set",
         "id": "<request-id>"},
        {"ts": two, "scene": "dune-a", "engine": "omni", "roll": 3, "why": "the author: the horizon tilts",
         "id": "<request-id>"},
        {"ts": two, "scene": "cove-b", "engine": "omni", "roll": 2, "why": "the author: gulls cross the lens",
         "id": "<request-id>"},
        {"ts": two, "scene": "cove-c", "engine": "omni", "roll": 2, "why": "the author: the tide runs backwards",
         "id": "<request-id>"},
    ], landings=[
        {"ts": one, "kind": "master", "scene": "dune", "gate": "ship_gate pass",
         "supersedes": "adsY-dune-final-v1.mp4 withdrawn"},
        {"ts": one, "kind": "master", "scene": "cove", "gate": "ship_gate pass"},
    ])
    req, land = "shoots/adsZ/requests.jsonl", "shoots/adsZ/landings.jsonl"
    assert res["moves"] == [("render", "render", f"{req}:2"), ("render", "render", f"{req}:3"),
                            ("eye", "render", f"{req}:5"), ("review", "render", f"{req}:6"),
                            ("eye", "render", f"{req}:7"), ("eye", "render", f"{req}:8"),
                            ("ship_gate", "deliver", f"{land}:1"), ("ledger", "board", f"{land}:1")]
    assert res["over_bound"] == ["cove sent back 2 times before shipping for what a scene showed",
                                 "cove-a on Omni re-rolled 2 times for failing to come back"]


def test_what_happened_outside_the_graph_is_pinned(results):
    """Beds and re-posts are real steps the graph does not model, reported rather than mapped
    onto an edge they do not belong to."""
    got = {s: r["outside"] for s, r in results.items() if r["outside"]}
    assert got == OUTSIDE, got


def test_a_gate_reading_alone_records_no_move(results):
    """A PASS row says what a gate read, not what happened next. Only a REVIEW a person
    approved states a move, so ads7, whose REVIEWs have no eye verdict, records none. A
    ship-gate pass is the same: only one that superseded a withdrawn cut states a delivery,
    so ads3, whose four passes supersede nothing, records no ship-gate move."""
    for shoot, res in results.items():
        gate_moves = [m for m in res["moves"] if m[0] == "ad_gates"]
        assert all(m[1] == "eye" for m in gate_moves), (shoot, gate_moves)
    assert not [m for m in results["ads7-real"]["moves"] if m[0] == "ad_gates"]
    assert not [m for m in results["ads3"]["moves"] if m[0] == "ship_gate"]


def test_a_bare_ship_gate_pass_states_no_delivery(tmp_path, monkeypatch):
    """A ship-gate pass that supersedes nothing is a reading. It records no move, and a shoot
    with passes and no row that states a delivery says so, even beside an ad-gate reading."""
    res = _august(tmp_path, monkeypatch, "adsW", landings=[
        {"ts": "2026-09-01", "kind": "master", "scene": "cove", "gate": "ship_gate pass"},
        {"ts": "2026-09-01", "kind": "master", "scene": "dune", "gate": "ship_gate pass"},
        {"ts": "2026-09-01", "kind": "gated master", "ad": "cove", "master": "adsW-cove-final-v1.mp4",
         "mouth": "PASS corr 0.30 lag +0.00", "captions": "PASS 5 cues", "drift_ms": 0},
    ])
    assert res["moves"] == []
    assert res["never"]["delivery"] == "2 ship-gate passes and no row that says a cut was delivered"


def test_what_the_ledgers_never_recorded_is_pinned(results):
    got = {s: set(r["never"]) for s, r in results.items()}
    assert got == NEVER, {s: sorted(v ^ NEVER.get(s, set())) for s, v in got.items() if v != NEVER.get(s)}


def test_every_row_is_read_and_none_is_skipped(results):
    """The replay classifies every line of every ledger or stops. Counted from the files
    themselves, so a rule that silently dropped a shape would show up as a short count."""
    for shoot, res in results.items():
        lines = 0
        for name in ("requests.jsonl", "landings.jsonl"):
            path = os.path.join(ROOT, "shoots", shoot, name)
            if os.path.exists(path):
                with open(path) as fh:
                    lines += sum(1 for line in fh if line.strip())
        assert res["rows"] == lines == sum(res["kinds"].values()), (shoot, res["rows"], lines)


@pytest.mark.parametrize("edge", sorted(ROW_MOVES), ids=lambda e: f"{e[0]}->{e[1]}")
def test_a_graph_missing_an_edge_fails_the_replay(edge):
    """Break test: take away an edge and the replay must name exactly the rows that travel
    it, which is what makes the green result above mean something."""
    got = [m[2] for shoot in MOVES for m in R.replay_shoot(shoot, edges=G.edges() - {edge})["unmapped"]]
    assert got == ROW_MOVES[edge], (edge, got)


def test_a_row_of_unknown_shape_stops_the_replay(tmp_path, monkeypatch):
    shoot = tmp_path / "adsX"
    shoot.mkdir()
    (shoot / "landings.jsonl").write_text(json.dumps({"kind": "something new", "ts": "2026-09-01"}) + "\n")
    monkeypatch.setattr(R, "SHOOTS", str(tmp_path))
    with pytest.raises(ValueError, match="no replay rule knows"):
        R.replay_shoot("adsX")


def test_the_replay_writes_nothing():
    def digest():
        h = hashlib.sha256()
        for shoot in sorted(os.listdir(os.path.join(ROOT, "shoots"))):
            for name in ("requests.jsonl", "landings.jsonl"):
                path = os.path.join(ROOT, "shoots", shoot, name)
                if os.path.exists(path):
                    h.update(open(path, "rb").read())
        return h.hexdigest()
    before = digest()
    R.main()
    assert digest() == before


def test_no_committed_ledger_carries_a_local_path():
    """A kept run's ledger is published. Script output carries absolute paths, and the first
    live run wrote the author's home directory into five rows before the toolkit learned to
    strip them. Every ledger under shoots/ is checked, August and graph runs alike."""
    home = os.path.expanduser("~")
    leaks = []
    for shoot in sorted(os.listdir(os.path.join(ROOT, "shoots"))):
        for name in ("ledger.jsonl", "requests.jsonl", "landings.jsonl"):
            path = os.path.join(ROOT, "shoots", shoot, name)
            if not os.path.exists(path):
                continue
            with open(path) as fh:
                for n, line in enumerate(fh, 1):
                    if home in line or any(p in line for p in ("/Users/", "/home/", "/tmp/", "/private/", "/var/folders/")):
                        leaks.append(f"shoots/{shoot}/{name}:{n}")
    assert not leaks, leaks
