"""The August ledgers, read as they are and checked against the graph.

The August shoots ran as an agent loop, and the agent wrote these ledgers by hand, so their
shape drifts from shoot to shoot. This reads each row by the fields it actually has and
reports, per shoot:

  transitions      the moves a row states, each checked for an edge in the graph
  divergences      records the graph could not have written, such as a delivery with no
                   ship-gate pass on the record
  over a bound     a loop the ledger shows running past a ceiling the graph enforces
  outside          what the rows show happening that the graph does not model at all
  never recorded   what the graph writes that these ledgers do not

A move is counted only where a row states it, and these are all the rules that count one.

A scene request is a re-roll when it is not the first request for its scene on its engine,
when it says roll or attempt 2 or more, or when it gives a why or a reason. A trailing roll
digit names the same scene, so grok-a2 is grok-a again, and a scene without its letter is its
spot, so harbor-c belongs to harbor. Each re-roll is one move, decided by its reason:

  names the author   a person sent the scene back after seeing it. That is the review, review
                     to render, when a row of the same shoot states a delivery of that spot on
                     an earlier date, and the eye, eye to render, when none does. The dates
                     carry no time, so a delivery on the same day is not before.
  names no one       a reason saying the scene failed to come back (refused, rejected, 422,
                     timed out, no video, an error) is the render step's own retry, render to
                     render. Any other reason sends the scene back for what it shows, which in
                     the graph only the eye does, so it is eye to render, actor not recorded.
  gives none         render to render, reason not recorded.

Three rows state that a spot was delivered, each on the date it carries:

  a ship-gate master whose supersedes names a withdrawn cut, which replaced a delivered one
  a withdrawal, once for each ad it pulled, since only a delivered cut can be pulled
  a move or relocation of that spot's cut

A superseding master records ledger to board, since the run that made it began from the
record of the run whose cut it replaced, and ship_gate to deliver when it says ship_gate
pass. A ship-gate pass that supersedes nothing states a reading, not a delivery, and records
no move. No ad-gate reading
records a move either, except a REVIEW marked "eye approved", which records ad_gates to eye. A
withdrawal records deliver to review, then review back to the closer when its reason names
closers, to render when it names a scene or a re-roll, and to build otherwise, once for each
ad it pulled.

A loop runs past its bound when one scene on one engine has more render to render re-rolls
than MAX_SCENE_REROLLS, when one spot has more eye to render send-backs than MAX_EYE_REJECTS,
or when one spot's withdrawn ads and review to render send-backs together outnumber
MAX_WITHDRAWALS.

The check this makes is the graph against history: a graph missing an edge that some row
records fails it. Prose notes are printed and not counted, and a row whose shape no rule
knows stops the replay.

A ledger the graph wrote, shoots/<run>/ledger.jsonl, is read by what it says of itself. Every
close, waiting and crashed row carries the trail the run had taken, and each step to the next
in each of those trails is a move, so every stint of a resumed run is checked. A close or a
crash is a stop. A resumed row is a person re-entering the run by hand, which the graph does
not do, so it is listed as a re-entry and its trail is not read. A redacted row is a note. A
delivery with no ship-gate pass before it, a local path, and an identity id where its sha256:
fingerprint belongs are divergences.

    python -m pipeline.replay

Exit 1 when a recorded move has no edge in the compiled graph. The divergences and the other
lists are history and cannot change, so they are reported here and pinned in
tests/test_replay.py, where a new one fails the suite.
"""
import collections
import json
import os
import re
import sys

from pipeline import graph as G
from pipeline.steps import STEPS

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SHOOTS = os.path.join(ROOT, "shoots")
PLACEHOLDERS = {"<request-id>", "<id>"}
PERSON = re.compile(r"\bthe author\b")
# The words a reason uses when a scene never came back. In the graph that is the only re-roll
# the render step makes by itself, so only a reason like this is the render step's move.
FAILED = re.compile(r"\b(refus|reject|422|time[sd]? ?out|timeout|no video|error)\w*", re.IGNORECASE)
# A graph run writes paths relative to its run directory and identities as fingerprints, per
# pipeline/SCHEMA.md, so a row carrying either of these is one the schema rules out.
LOCAL_PATHS = ("/Users/", "/home/", "/private/", "/var/folders/", "/tmp/")
IDENTITY_KEYS = ("look", "voice", "avatar", "avatar_id", "voice_id")
# The rows a graph run writes when it stops, each carrying the trail it had taken.
END_KINDS = ("close", "waiting", "crashed")
ENGINES = {"google/gemini-omni-flash": "Omni", "omni": "Omni",
           "alibaba/wan-3.0/text-to-video": "Wan 3.0", "wan3": "Wan 3.0",
           "bytedance/seedance-2.0/text-to-video": "Seedance 2.0", "seedance2": "Seedance 2.0",
           "fal-ai/lyria2": "Lyria 2", "bed": "the bed engine"}

Row = collections.namedtuple("Row", "shoot file line data kind")


def _ref(row):
    return f"shoots/{row.shoot}/{row.file}:{row.line}"


def _classify(shoot, file, line, d):
    """Name what a row records. Every shape in the seven ledgers has a rule here."""
    kind = d.get("kind")
    if file == "requests.jsonl":
        if kind == "bed" or str(d.get("scene", "")).endswith("-bed") or d.get("engine") == "fal-ai/lyria2":
            return "bed request"
        if kind is None and "scene" in d:
            return "scene request"
    else:
        if kind is None and "scene" in d and ("status" in d or "url" in d):
            return "scene landing"
        named = {"scene": "scene landing", "closer": "closer landing", "bed": "bed landing",
                 "master": "ship gate", "gated master": "ad gates", "withdrawn": "withdrawn",
                 "relocation": "moved", "moved": "moved"}
        if kind in named:
            return named[kind]
    raise ValueError(f"shoots/{shoot}/{file}:{line} has a shape no replay rule knows. "
                     "Read it and add a rule rather than skipping it.")


def shoots():
    return sorted(d for d in os.listdir(SHOOTS) if os.path.isdir(os.path.join(SHOOTS, d)))


def is_graph_run(shoot):
    return os.path.exists(os.path.join(SHOOTS, shoot, "ledger.jsonl"))


def _raw_identity(value, under=False):
    """Whether an id sits where its fingerprint belongs: a value under a look, voice or avatar
    key, at any depth, that does not start with sha256:. An empty value holds no id."""
    if isinstance(value, dict):
        return any(_raw_identity(v, under or k in IDENTITY_KEYS) for k, v in value.items())
    if isinstance(value, list):
        return any(_raw_identity(v, under) for v in value)
    if not under or value is None or value == "" or isinstance(value, bool):
        return False
    return not str(value).startswith("sha256:")


def replay_graph_run(shoot, edges=None):
    """A ledger the graph wrote, read by what it says of itself.

    Every close, waiting and crashed row carries the trail the run had taken to it, and each
    step to the next in each of those trails is a move, so a run that stopped and was resumed
    is checked on every stint and not only its last. A close or a crash is a stop. A resumed
    row is a person re-entering the run by hand, which the graph does not do, so it is listed
    as a re-entry and its trail is not read as moves. A redacted row is a note. What the run
    never recorded is checked against what pipeline/SCHEMA.md says every run writes, over
    every step any of its trails reached.
    """
    edges = G.edges() if edges is None else edges
    path = os.path.join(SHOOTS, shoot, "ledger.jsonl")
    with open(path) as fh:
        rows = [json.loads(line) for line in fh if line.strip()]
    ends = [r for r in rows if r["kind"] in END_KINDS]
    moves = [(a, b, f"shoots/{shoot}/ledger.jsonl:{r['seq']}")
             for r in ends for a, b in zip(r.get("trail") or [], (r.get("trail") or [])[1:], strict=False)]
    allowed = set(edges) | G.CROSS_RUN_EDGES
    steps = {s for r in ends for s in r.get("trail") or []}
    never = {}
    if not ends:
        never["the run's end"] = "no close, waiting or crashed row"
    if "board" in steps and not any(r["kind"] == "gate" and r["step"] == "board" for r in rows):
        never["board verdict"] = "no row"
    requests = [r for r in rows if r["kind"] == "request" and not r.get("dry")]
    landed = {r.get("request_id") for r in rows if r["kind"] == "landing"}
    fake = [r for r in requests if not str(r.get("request_id", "")).startswith("req_")]
    if fake:
        never["request ids"] = f"{len(fake)} of {len(requests)} requests carry no real id"
    unlanded = [r for r in requests if r.get("request_id") not in landed]
    if unlanded:
        never["landings"] = f"{len(unlanded)} of {len(requests)} requests have no landing with their id"
    untimed = [r for r in rows if len(str(r.get("ts", ""))) <= 10]
    if untimed:
        never["time of day"] = f"{len(untimed)} rows carry no time"
    if "render" in steps and not any(r["kind"] == "request" and "eleven" in str(r.get("engine")) for r in rows) \
            and not any(r.get("dry") for r in rows):
        never["voice take"] = "no row"
    if "build" in steps and not any(r["kind"] == "build" for r in rows):
        never["build parameters"] = "no row"
    if "ship_gate" in steps and not any(r["kind"] == "gate" and r["step"] == "ship_gate" and r.get("loudness")
                                        for r in rows):
        never["ship-gate readings"] = "no loudness reading"
    anon = [r for r in rows if r["kind"] in ("eye", "review") and not r.get("who")]
    if anon:
        never["who approved"] = f"{len(anon)} answers carry no name"
    divergences = []
    for i, r in enumerate(rows):
        if r["kind"] == "deliver":
            gates = [g for g in rows[:i] if g["kind"] == "gate" and g["step"] == "ship_gate"]
            if not gates or not gates[-1].get("pass"):
                divergences.append(f"a delivery at seq {r['seq']} with no ship-gate pass before it")
        if any(p in json.dumps(r) for p in LOCAL_PATHS):
            divergences.append(f"row seq {r['seq']} carries a local path")
        if _raw_identity(r):
            divergences.append(f"row seq {r['seq']} carries an identity id where its fingerprint belongs")
    reentries = [f"seq {r['seq']}, before {r['step']}: {r.get('reason') or 'reason not recorded'}"
                 + (f", abandoning a wait for the {r['abandoned']}" if r.get("abandoned") else "")
                 for r in rows if r["kind"] == "resumed"]
    last = ends[-1] if ends else {}
    return {"rows": len(rows), "kinds": collections.Counter(r["kind"] for r in rows), "moves": moves,
            "unmapped": [m for m in moves if (m[0], m[1]) not in allowed], "divergences": divergences,
            "over_bound": [], "notes": [f"seq {r['seq']}: {r.get('what')}" for r in rows if r["kind"] == "redacted"],
            "never": never, "graph": True, "stops": sum(1 for r in rows if r["kind"] in ("close", "crashed")),
            "reentries": reentries, "trail": last.get("trail") or [], "end": last.get("kind"),
            "waiting": last["step"] if last.get("kind") == "waiting" else None,
            "crashed": last["step"] if last.get("kind") == "crashed" else None}


def load(shoot):
    rows = []
    for name in ("requests.jsonl", "landings.jsonl"):
        path = os.path.join(SHOOTS, shoot, name)
        if not os.path.exists(path):
            continue
        with open(path) as fh:
            for i, text in enumerate(fh, 1):
                if text.strip():
                    d = json.loads(text)
                    rows.append(Row(shoot, name, i, d, _classify(shoot, name, i, d)))
    return rows


def _scene(d):
    """A trailing roll digit on the scene letter is the same scene: grok-a2 and grok-a3
    are grok-a re-rolled, and their rows say so."""
    return re.sub(r"^(.*-[a-z])\d+$", r"\1", d.get("scene") or f"{d.get('spot')}-bed")


def _spot(scene):
    """The spot a scene belongs to, the scene without its letter: harbor-c is harbor's."""
    return re.sub(r"-[a-z]$", "", scene)


def _scene_key(row):
    """One scene on one engine."""
    d = row.data
    return _scene(d), d.get("engine") or d.get("leg") or "bed"


def _date(d):
    """The day a row carries, or None. The August rows carry a date and no time, so a day is
    all two rows can be compared by."""
    ts = str(d.get("ts") or "")
    return ts[:10] if len(ts) >= 10 else None


def _verdict(text):
    return (text or "").split()[0].rstrip(",;") if text else ""


def _version(master):
    m = re.search(r"-v(\d+)\.mp4$", master or "")
    return int(m.group(1)) if m else None


def replay_shoot(shoot, edges=None):
    edges = G.edges() if edges is None else edges
    rows = load(shoot)
    by = collections.defaultdict(list)
    for r in rows:
        by[r.kind].append(r)
    delivered = _deliveries(by)
    moves = []                       # (src, dst, ref)

    # Re-rolls: each is one move, and what its reason says decides whose.
    renders = collections.Counter()
    retried = collections.defaultdict(list)     # (scene, engine) -> the reason on each render re-roll
    sent_back = collections.defaultdict(list)   # spot -> whether each eye send-back named the author
    rejects = collections.Counter()             # (scene, engine) -> author send-backs after a delivery
    for r in by["scene request"]:
        key = _scene_key(r)
        renders[key] += 1
        why = r.data.get("why") or r.data.get("reason") or ""
        said = (r.data.get("roll") or r.data.get("attempt") or 1) > 1 or bool(why)
        if renders[key] == 1 and not said:
            continue    # a first render. A row that says it is a re-roll counts even when its
                        # earlier rolls are on another shoot's ledger.
        spot, day = _spot(key[0]), _date(r.data)
        if PERSON.search(why):
            if day and any(d and d < day for d in delivered.get(spot, [])):
                rejects[key] += 1
                moves.append(("review", "render", _ref(r)))
            else:
                sent_back[spot].append(True)
                moves.append(("eye", "render", _ref(r)))
        elif why and not FAILED.search(why):
            sent_back[spot].append(False)
            moves.append(("eye", "render", _ref(r)))
        else:
            retried[key].append(why)
            moves.append(("render", "render", _ref(r)))

    # A gate row records a reading. Only a REVIEW a person approved states a move, the gate
    # asking the eye. A PASS on its own says nothing about what came next.
    for r in by["ad gates"]:
        mouth = r.data.get("mouth", "")
        if _verdict(mouth) == "REVIEW" and "eye approved" in mouth:
            moves.append(("ad_gates", "eye", _ref(r)))

    # A master that superseded a withdrawn cut was delivered in its place, by a run that began
    # from the record of the run it replaced. A pass that supersedes nothing is a reading.
    for r in by["ship gate"]:
        if "withdrawn" in r.data.get("supersedes", ""):
            if r.data.get("gate") == "ship_gate pass":
                moves.append(("ship_gate", "deliver", _ref(r)))
            moves.append(("ledger", "board", _ref(r)))
    for r in by["withdrawn"]:
        reason = r.data.get("reason", "")
        back = "closer" if "closer" in reason else "render" if re.search(r"\bscene|re-roll", reason) else "build"
        for _ in r.data.get("withdrawn", []):
            moves += [("deliver", "review", _ref(r)), ("review", back, _ref(r))]

    allowed = set(edges) | G.CROSS_RUN_EDGES
    unmapped = [m for m in moves if (m[0], m[1]) not in allowed]

    return {
        "rows": len(rows),
        "kinds": collections.Counter(r.kind for r in rows),
        "moves": moves,
        "unmapped": unmapped,
        "divergences": _divergences(by),
        "over_bound": _over_bound(by, retried, sent_back, rejects),
        "notes": _notes(by),
        "outside": _outside(by),
        "never": _never_recorded(rows, by, delivered),
    }


def _over_bound(by, retried, sent_back, rejects):
    """Every loop past the bound the graph puts on it, with what its rows could not say: the
    reason for a re-roll, or who sent a scene back."""
    out = []
    for (scene, eng), whys in retried.items():
        if len(whys) > G.MAX_SCENE_REROLLS:
            head = f"{scene} on {ENGINES.get(eng, eng)} re-rolled {len(whys)} times"
            out.append(f"{head} for failing to come back" if any(whys) else f"{head}, reason not recorded")
    for spot, named in sent_back.items():
        if len(named) > G.MAX_EYE_REJECTS:
            unnamed = named.count(False)
            out.append(f"{spot} sent back {len(named)} times before shipping for what a scene showed"
                       + (f", actor not recorded on {unnamed}" if unnamed else ""))
    out += [f"{ad} withdrawn {n} times" for ad, n in _withdrawals(by, rejects).items() if n > G.MAX_WITHDRAWALS]
    return sorted(out)


def _withdrawals(by, rejects):
    """Per spot, every time a person sent delivered work back: each ad a withdrawal pulled,
    and each scene the author re-rolled after that spot was delivered. The eye's send-backs
    before a delivery have a bound of their own and are not counted here."""
    out = collections.Counter()
    for r in by["withdrawn"]:
        for item in r.data.get("withdrawn", []):
            out[item["ad"]] += 1
    for (scene, _), n in rejects.items():
        out[_spot(scene)] += n
    return out


def _deliveries(by):
    """The dates each spot is stated delivered on, as spot -> dates, from the three rows that
    state one: a master that superseded a withdrawn cut, a withdrawal for each ad it pulled,
    and a move or relocation. A move that names no spot, like the one in ads7, says something
    was delivered but not what, and is kept under None."""
    out = collections.defaultdict(list)
    for r in by["ship gate"]:
        if "withdrawn" in r.data.get("supersedes", ""):
            out[r.data.get("scene")].append(_date(r.data))
    for r in by["withdrawn"]:
        for item in r.data.get("withdrawn", []):
            out[item["ad"]].append(_date(r.data))
    for r in by["moved"]:
        out[r.data.get("scene") or r.data.get("spot") or r.data.get("ad")].append(_date(r.data))
    return out


def _delivered(by):
    """Every cut the record proves was delivered, by version, as ad -> versions.

    Only a withdrawal names versions. It proves the cut it withdrew had been delivered, and its
    reason names the version that replaced it in the same thread. A superseding master or a
    move states that a spot was delivered without naming a version, so neither adds one here,
    and a ship-gate pass that supersedes nothing states no delivery at all.
    """
    out = collections.defaultdict(set)
    gated = {r.data["ad"]: _version(r.data.get("master")) for r in by["ad gates"]}
    for r in by["withdrawn"]:
        named = [int(v) for v in re.findall(r"(?<![a-z_])v(\d+)\b", r.data.get("reason", ""))]
        for item in r.data.get("withdrawn", []):
            ad = item["ad"]
            out[ad].add(max(out[ad]) if out[ad] else gated.get(ad, 1))   # the cut withdrawn
            out[ad].update(named)                                       # its replacement
    return out


def _divergences(by):
    found = []
    shipped = {r.data.get("scene") for r in by["ship gate"] if r.data.get("gate") == "ship_gate pass"}
    delivered = _delivered(by)
    gated = collections.defaultdict(set)
    for r in by["ad gates"]:
        gated[r.data["ad"]].add(_version(r.data.get("master")))
    no_pass = sorted(f"{ad} v{v}" for ad, vs in delivered.items() if ad not in shipped for v in sorted(vs))
    if no_pass:
        found.append(f"{len(no_pass)} deliveries with no ship-gate pass on the record: {', '.join(no_pass)}")
    no_gates = sorted(f"{ad} v{v}" for ad, vs in delivered.items() for v in sorted(vs) if v not in gated[ad])
    if no_gates:
        found.append(f"{len(no_gates)} of them with no gate reading at all: {', '.join(no_gates)}")
    ungated = sorted(r.data.get("scene") for r in by["ship gate"]
                     if r.data.get("gate") == "ship_gate pass" and r.data.get("scene") not in gated)
    if ungated:
        found.append(f"{len(ungated)} ship-gate passes with no ad-gate reading on the record: {', '.join(ungated)}")
    ship_lines = [r.line for r in by["ship gate"]]
    gate_lines = [r.line for r in by["ad gates"]]
    if ship_lines and gate_lines and max(ship_lines) < min(gate_lines):
        found.append(f"{len(ship_lines)} unversioned ship-gate passes written above all {len(gate_lines)} ad-gate "
                     f"readings (lines {min(ship_lines)}-{max(ship_lines)} before {min(gate_lines)}-{max(gate_lines)}), "
                     "so no gated master has a pass recorded after its reading")
    unlooked = sorted(r.data["ad"] for r in by["ad gates"]
                      if _verdict(r.data.get("mouth")) == "REVIEW" and "eye approved" not in r.data.get("mouth", ""))
    if unlooked:
        found.append(f"past a REVIEW with no eye verdict on the record: {', '.join(unlooked)}")
    return found


def _outside(by):
    """What the rows show happening that the graph has no step for."""
    out = []
    if by["bed request"]:
        out.append(f"{len(by['bed request'])} music-bed requests; the graph reuses a bed and has no step that makes one")
    if by["moved"]:
        n = len(by["moved"])
        out.append(f"{n} delivered {'cut' if n == 1 else 'cuts'} moved or re-posted in the delivery channel, "
                   "which the graph, delivering locally, does not model")
    return out


def _notes(by):
    """Prose on a gate row that describes a move, shown so a reader can weigh it, not counted."""
    out = []
    for r in by["ad gates"]:
        d = r.data
        extra = d.get("mouth", "").split(";", 1)[1].strip() if ";" in d.get("mouth", "") else ""
        for text in (extra, d.get("fix", "")):
            if text:
                out.append(f"{d['ad']} v{_version(d.get('master'))}, {text}  ({_ref(r)})")
    return out


def _never_recorded(rows, by, delivered):
    requests = by["scene request"] + by["bed request"]
    out = {}
    if not any("board" in str(r.data.get("kind", "")) or "board" in r.data for r in rows):
        out["board verdict"] = "no row"
    if not any("eleven" in str(r.data.get("engine", "")) or r.data.get("kind") in ("voice", "vo", "narration")
               for r in rows):
        out["voice take"] = "no row"
    if not by["closer landing"] and not any("closer" in r.data for r in by["ad gates"]):
        out["closer render"] = "no row"
    trims = [r for r in by["ad gates"] if "trimmed" in r.data.get("fix", "")]
    out["build parameters"] = (f"only in prose, a closer trim noted on {len(trims)} rows" if trims else "no row")
    if by["ship gate"]:
        out["ship-gate readings"] = f"{len(by['ship gate'])} rows say ship_gate pass with no loudness or peak reading"
    else:
        out["ship-gate readings"] = "no row"
    placeholder = sum(1 for r in requests
                      if (r.data.get("id") or r.data.get("request_id")) in PLACEHOLDERS)
    if placeholder:
        out["request ids"] = f"{placeholder} of {len(requests)} requests carry a placeholder id"
    # Joined by scene and engine, the only keys the rows share, since every id is a
    # placeholder. A landing row with no engine field answers its scene on any engine.
    landed = collections.Counter()
    for r in by["scene landing"] + by["bed landing"]:
        eng = r.data.get("engine") or r.data.get("leg")
        landed[(_scene(r.data), eng)] += 1
    asked = collections.Counter(_scene_key(r) for r in requests)
    unlanded = 0
    for (scene, eng), n in asked.items():
        have = landed[(scene, eng)] + landed[(scene, None)]
        unlanded += max(0, n - have)
    if unlanded:
        out["landings"] = f"{unlanded} of {len(requests)} requests have no landing row"
    no_ts = sum(1 for r in rows if "ts" not in r.data)
    date_only = sum(1 for r in rows if len(str(r.data.get("ts", ""))) == 10)
    if no_ts or date_only:
        out["time of day"] = (f"{date_only} rows carry a date and no time"
                              + (f", {no_ts} carry no timestamp" if no_ts else ""))
    gaps = []
    seen = collections.Counter()
    for r in requests:
        seen[_scene_key(r)] += 1
        roll = r.data.get("roll") or r.data.get("attempt")
        if roll and roll > seen[_scene_key(r)]:
            gaps.append(f"{_scene_key(r)[0]} is roll {roll} with {seen[_scene_key(r)] - 1} earlier here")
    if gaps:
        out["earlier rolls"] = ", ".join(gaps)
    versions = collections.defaultdict(set)
    for r in by["ad gates"]:
        versions[r.data["ad"]].add(_version(r.data.get("master")))
    missing = [f"{ad} {', '.join(f'v{v}' for v in range(1, max(vs)) if v not in vs)}"
               for ad, vs in sorted(versions.items()) if max(vs) > 1 and len(vs) < max(vs)]
    if missing:
        out["earlier builds"] = "; ".join(missing) + ", with no gate reading on the record"
    anon = sum(1 for r in by["ad gates"] if "eye approved" in r.data.get("mouth", ""))
    if anon:
        out["who approved"] = f"{anon} eye approvals carry no name"
    # A delivery is what one of the three delivery rows states. Ship-gate passes are named when
    # a shoot has them, since a pass is the reading a delivery would follow and is not one.
    if not delivered:
        if by["ship gate"]:
            passes = sum(1 for r in by["ship gate"] if r.data.get("gate") == "ship_gate pass")
            out["delivery"] = f"{passes} ship-gate passes and no row that says a cut was delivered"
        else:
            out["delivery"] = "no row" if by["ad gates"] else "no master, gate or delivery row"
    return out


def nodes_order(pairs, nodes):
    rank = {n: i for i, n in enumerate(nodes + ["review", "ledger"])}
    return sorted(pairs, key=lambda p: rank.get(p[0], 99))


def backed_edges(results):
    return sorted({(s, t) for res in results.values() for s, t, _ in res["moves"]})


def report(everything, edges=None):
    edges = G.edges() if edges is None else edges
    results = {s: r for s, r in everything.items() if not r.get("graph")}
    graph_runs = {s: r for s, r in everything.items() if r.get("graph")}
    lines = [f"The August ledgers against the graph, {len(results)} shoots, "
             f"{sum(r['rows'] for r in results.values())} rows", ""]
    width = max(len(s) for s in everything)
    lines.append(f"{'Shoot':<{width}}  Transitions on the record")
    for shoot, res in results.items():
        c = collections.Counter(f"{s}->{t}" for s, t, _ in res["moves"])
        text = ", ".join(f"{k} {n}" for k, n in sorted(c.items())) or "none, the ledger records renders only"
        lines.append(f"{shoot:<{width}}  {text}")
    unmapped = [m for res in results.values() for m in res["unmapped"]]
    lines += ["", "Every move a row records has an edge in the graph." if not unmapped else
              f"{len(unmapped)} recorded moves have no edge in the graph:"]
    lines += [f"  {s}->{t}  {ref}" for s, t, ref in unmapped]

    backed = set(backed_edges(results))
    nodes = [s.node for s in STEPS]
    spine = set(zip(nodes, nodes[1:], strict=False)) | {("deliver", "review"), ("review", "ledger")}
    unbacked = set(edges) - G.STOP_EDGES - backed
    lines += ["", "Graph edges no row records, since the rows kept gate readings but rarely what came next.",
              "  The spine, whose handoffs no row records: "
              + ", ".join(f"{s}->{t}" for s, t in nodes_order(unbacked & spine, nodes)),
              "  Back edges, which come from the doctrine: "
              + ", ".join(f"{s}->{t}" for s, t in sorted(unbacked - spine))]

    # Graph runs are listed here too, so a row the schema rules out is never left unprinted.
    lines += ["", "Divergences, records the graph could not have written:"]
    for shoot, res in everything.items():
        lines += [f"  {shoot:<{width}}  {d}" for d in res["divergences"]]
    lines += ["", f"Loops past a bound the graph enforces, {G.MAX_SCENE_REROLLS} re-roll per scene, "
              f"{G.MAX_EYE_REJECTS} send-back from the eye per spot and {G.MAX_WITHDRAWALS} withdrawals per spot:"]
    for shoot, res in results.items():
        lines += [f"  {shoot:<{width}}  {b}" for b in res["over_bound"]]
    lines += ["", "Outside the graph, what the rows show happening that no step models:"]
    for shoot, res in results.items():
        lines += [f"  {shoot:<{width}}  {o}" for o in res.get("outside", [])]
    lines += ["", "Notes in prose that describe moves, printed for a reader and not counted:"]
    for shoot, res in results.items():
        lines += [f"  {shoot:<{width}}  {n}" for n in res["notes"]]

    lines += ["", "Never recorded in August, which the graph now writes:"]
    everywhere = set.intersection(*(set(r["never"]) for r in results.values()))
    for item in sorted(everywhere):
        detail = {res["never"][item] for res in results.values()}
        lines.append(f"  {item:<26}  all {len(results)} shoots" + ("" if detail == {"no row"} else ", see below"))
    for shoot, res in results.items():
        for item, detail in res["never"].items():
            if item not in everywhere or detail != "no row":
                lines.append(f"  {shoot:<{width}}  {item}: {detail}")
    if graph_runs:
        lines += ["", "Runs the graph wrote, checked against pipeline/SCHEMA.md:"]
        for shoot, res in graph_runs.items():
            state = (f"waiting for the {res['waiting']}" if res.get("waiting")
                     else f"crashed in the {res['crashed']}" if res.get("crashed")
                     else "closed" if res.get("end") == "close" else "not closed")
            trail = " -> ".join(res["trail"]) or "no trail"
            gaps = "; ".join(f"{k}: {v}" for k, v in res["never"].items()) or "nothing missing"
            edge_note = "every move a graph edge" if not res["unmapped"] else f"{len(res['unmapped'])} moves off the graph"
            lines.append(f"  {shoot:<{width}}  {res['rows']} rows, {res['stops']} stops and "
                         f"{len(res['reentries'])} re-entries by hand, {state}, {edge_note}, {gaps}")
            lines.append(f"  {'':<{width}}  {trail}")
            # A redaction is a person's hand on the record too, so it prints with the re-entries.
            lines += [f"  {'':<{width}}    {e}" for e in res["reentries"] + res["notes"]]
    return "\n".join(lines)


def replay_all(edges=None):
    return {s: (replay_graph_run(s, edges) if is_graph_run(s) else replay_shoot(s, edges)) for s in shoots()}


def main():
    everything = replay_all()
    print(report(everything))
    return 1 if any(res["unmapped"] for res in everything.values()) else 0


if __name__ == "__main__":
    sys.exit(main())
