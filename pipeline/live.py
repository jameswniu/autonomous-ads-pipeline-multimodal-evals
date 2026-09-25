"""The toolkit that spends: fal for the scenes, ElevenLabs for the voice, HeyGen for the closer.

pipeline/toolkit.py holds the free steps and the base class. This adds the steps that reach a
vendor, each through the repo's own scripts where one exists. gates/voice_take.sh draws the
narration and gates/script_match.sh checks it says the script. guards/block_unpinned_identity.sh
and guards/prop_gate.sh vet a closer render before anything is paid for, the voice included,
and gates/jaw_gate.py rules on it after. gates/edge_clip_probe.py looks at every scene that
comes back, and gates/cast_gate.py checks that a scene showing the presenter shows her, since a
scene that names her is rendered from her reference face. shoots/build-ad.sh cuts the master, shoots/master.sh masters it, and
gates/ad_gates.sh, guards/ship_gate.sh and gates/loudness_gate.py gate it.

Every vendor request goes on the ledger before it is sent, with a real request id, the
vendor's own id as soon as it answers, and its landing after, with the vendor's own text on a
failure, so a run that dies mid-call still leaves the record of what it asked for and what it
is owed. A run re-entered after a failure collects what it already paid for instead of paying
again. Identity ids, the voice and the avatar look, are never written; the ledger carries a
short hash of each, which shows two runs used the same identity without publishing it. Paths
on the ledger are relative to the run directory, since a kept run is committed.

What a live run needs in its environment, all checked before the graph starts:

  FAL_KEY, ELEVENLABS_API_KEY   vendor keys, never printed
  ELEVENLABS_VOICE_ID           the presenter's pinned voice
  IDENTITY_PINS                 the pin file the identity guard checks against; with none, the
                                guard passes everything, so this toolkit refuses to run without it
  FILM2, BED                    the directory holding hit.mp3 and hit2.mp3, and this spot's bed
  FACEPY                        an interpreter with the face extra, for the jaw and mouth probes
                                and the cast gate
  PRESENTER_STILL               an image or clip of the presenter to cut her reference from when
                                no closer take is reused. The reference comes from the CLOSER_FROM
                                take first. A spot that shows her is refused with neither, and
                                with either one every scene is read back against her face.
  CLOSER_FROM                   a directory holding an existing closer take to reuse, or else
  HEYGEN_API_KEY, CLOSER_LOOK_ID to render one. The REST API bills a wallet of its own, separate
                                from a web plan's credits.
"""
import base64
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid

from pipeline.ledger import fingerprint, new_request_id, sha256
from pipeline.toolkit import (PLACEHOLDER, PRICE_PER_SCENE, REFERENCE_ENGINE, ROOT, Toolkit, cast_ok, cast_text,
                              engine_for, has_cast, load_spot, scene_prompt)

__all__ = ["LiveSetupError", "LiveToolkit", "fingerprint"]

FAL = "https://queue.fal.run"
HEYGEN = "https://api.heygen.com"
ELEVEN = "https://api.elevenlabs.io"

# What each engine is asked for, read from fal's OpenAPI listing for the endpoint on
# 2026-09-23. The August raws are 16:9 and five seconds long, which the build crops to a
# centre square and cuts to the narration. An engine with no entry is refused rather than
# sent a guessed shape.
ENGINE_INPUT = {"google/gemini-omni-flash": {"aspect_ratio": "16:9", "duration": 5},
                "google/gemini-omni-flash/reference-to-video": {"aspect_ratio": "16:9", "duration": 5}}

# The standing reason the ship gate's time-of-day check is waived on an ad, logged on every run.
# The source: "a morning spot delivered at 1 am is not a claim about the clock." The replay check
# is NOT waived here. Whether a replay is visible is a fact about the scene that only a reader of
# its scan can declare, so a replay goes to the eye, and the reader's reason is the override.
AD_FICTION = "ad fiction, a spot's time of day is staged, not a claim"

# What this toolkit reads off each gate's output. They are the contract with the scripts, and
# tests/test_contracts.py runs the real scripts and checks their output still fits these.
AD_GATES_LINE = re.compile(r"AD_GATES_RESULT caption=(\w+) drift=(\w+) mouth=(\w+)")
MOUTH_LINE = re.compile(r"MOUTH SYNC \w+: corr (-?[0-9.]+) at lag ([-+]?[0-9.]+)s")
JAW_LINE = re.compile(r"^JAW_GATE .*verdict=(PASS|FAIL|UNMEASURED)$", re.M)
CAST_LINE = re.compile(r"^CAST_GATE faces=(?P<faces>\d+) sim=(?P<sim>-?[0-9.]+|nan) min=(?P<min>-?[0-9.]+|nan) "
                       r"strangers=(?P<strangers>\d+) floor=(?P<floor>[0-9.]+) verdict=(?P<verdict>PASS|FAIL|NOFACE)\s*$",
                       re.M)
LOUDNESS_LINE = re.compile(r"^LOUDNESS_GATE .*verdict=(PASS|FAIL)$", re.M)
SLIT_LINE = re.compile(r"^slit-scan: (.+?)\s*$", re.M)   # the rest of the line, so a path with a space still reads
REPLAY_VERTEX = re.compile(r"^replay vertex: t=([0-9.]+)s$", re.M)
REPLAY_VERDICT = re.compile(r"^\s*(\w+ (?:FORWARD|REPLAYS):.*)$", re.M)
EDGE_FLAG = re.compile(r"^EDGE CLIP: .*$", re.M)
SHIP_HOLDS = {"directional": "SHIP-GATE HOLD: directional scene",
              "replay": "SHIP-GATE HOLD: the scene replays itself",
              "letterbox": "LETTERBOX"}

POLL_SECONDS = 10

# Landing statuses that leave a request owed: the vendor may still finish it, or has finished it
# and it was never downloaded. Either way it is collected on the next pass, never sent again.
OWED = (None, "TIMEOUT", "UNCOLLECTED")
WAIT_LIMIT = 40 * 60

# A multipart delimiter is two hyphens and the boundary, and the closing one ends with two more.
HYPHENS = "-" * 2


class LiveSetupError(RuntimeError):
    """Something a live run needs is missing or wrong. Raised before the spend it would have
    enabled, never after it."""


def need(name):
    value = os.environ.get(name, "")
    if not value:
        raise LiveSetupError(f"{name} is not set; the top of pipeline/live.py lists what a live run needs")
    return value


def http(method, url, headers, body=None, timeout=120):
    """One vendor call. A network failure comes back as status 0 with its text, the way an HTTP
    error comes back with its code, so no caller loses a paid request to an exception."""
    req = urllib.request.Request(url, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        return 0, f"{type(e).__name__}: {e}".encode()


def as_json(data):
    try:
        return json.loads(data.decode() or "{}")
    except (ValueError, UnicodeDecodeError):
        return {}


def multipart(fields, files):
    sep = HYPHENS + uuid.uuid4().hex
    out = []
    for k, v in fields.items():
        out.append(f'{sep}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode())
    for k, (name, data, ctype) in files.items():
        out.append(f'{sep}\r\nContent-Disposition: form-data; name="{k}"; filename="{name}"\r\n'
                   f"Content-Type: {ctype}\r\n\r\n".encode() + data + b"\r\n")
    out.append(f"{sep}{HYPHENS}\r\n".encode())
    return b"".join(out), f"multipart/form-data; boundary={sep[len(HYPHENS):]}"


def duration(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
                       capture_output=True, text=True, timeout=60)
    try:
        return round(float(r.stdout.strip()), 3)
    except ValueError:
        return None


GONE = (404, 410)        # the vendor no longer has the job or its result, so waiting is over


def held_back(code):
    """Whether a refused result fetch is one that waiting can change: a locked or unpaid account, a
    rate limit, or the vendor's own error. A 404 or a 410 means the result is gone."""
    return code in (401, 402, 403, 408, 425, 429) or 500 <= code < 600


def frame_size(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
                        "-of", "csv=p=0", path], capture_output=True, text=True, timeout=60)
    try:
        w, h = (int(x) for x in r.stdout.strip().split(",")[:2])
    except ValueError:
        return None
    return w, h


def _looks_like_id(s):
    return isinstance(s, str) and len(s) >= 12 and "/" not in s and not any(c.isspace() for c in s)


def identity_values(pins_path):
    """Every id and name the pin file holds, so they can be scrubbed from anything a script
    prints. The identity guard quotes the pinned id, its name and its group when it refuses."""
    try:
        with open(pins_path) as fh:
            pins = json.load(fh)
    except (OSError, ValueError):
        return set()
    found = set()

    def walk(x, key=""):
        if isinstance(x, dict):
            for k, v in x.items():
                if "ids" in key and _looks_like_id(k):
                    found.add(k)
                walk(v, k)
        elif isinstance(x, list):
            for v in x:
                walk(v, key)
        elif ("id" in key or "name" in key) and _looks_like_id(x):
            found.add(x)
    walk(pins)
    return found


def scene_key(spot, scenes, name):
    """A scene named in an answer, as the board keys it. The ledger spells scenes "<spot>-a",
    so that spelling is accepted; anything that is not one of this spot's scenes is refused
    before a request is sent for it."""
    key = str(name).strip()
    if key.startswith(f"{spot}-"):
        key = key[len(spot) + 1:]
    if key not in scenes:
        raise LiveSetupError(f"the answer asks for scene {name!r}; this spot's scenes are {', '.join(sorted(scenes))}")
    return key


class LiveToolkit(Toolkit):
    def __init__(self, run_dir, run_id=None):
        # Everything the run can need is checked here, before the graph starts, so a missing
        # variable can never surface after the scenes are already paid for.
        voice_id = need("ELEVENLABS_VOICE_ID")
        need("FAL_KEY")
        need("ELEVENLABS_API_KEY")
        pins = self.identity_file()
        if not os.path.isfile(need("BED")):
            raise LiveSetupError("BED is not a file; the build needs this spot's bed")
        if not os.path.isdir(need("FILM2")):
            raise LiveSetupError("FILM2 is not a directory; the build needs hit.mp3 and hit2.mp3 from it")
        if not os.environ.get("CLOSER_FROM"):
            need("HEYGEN_API_KEY")
            need("CLOSER_LOOK_ID")
        self.secrets = identity_values(pins) | {v for v in (voice_id, os.environ.get("CLOSER_LOOK_ID")) if v}
        super().__init__(run_dir, run_id)
        # Absolute, because the build writes an ffmpeg concat list, and ffmpeg resolves a
        # relative path in one against the list's own directory, not the working directory.
        self.takes = os.path.join(self.run_dir, "takes")
        os.makedirs(self.takes, exist_ok=True)

    # Plumbing.

    def rel(self, path):
        return os.path.relpath(path, self.run_dir)

    def clean(self, text):
        """Paths come out as in the base class, and every identity the pin file or the run
        knows is replaced by its fingerprint, longest first so no id is half replaced."""
        text = super().clean(text)
        for secret in sorted(self.secrets, key=len, reverse=True):
            text = text.replace(secret, fingerprint(secret))
        return text

    def lines(self, text, last=8):
        return [self.clean(x) for x in str(text).splitlines() if x.strip()][-last:]

    def dir(self, name):
        d = os.path.join(self.takes, name)
        os.makedirs(d, exist_ok=True)
        return d

    def script(self, *args, env=None, drop=(), timeout=1800, python=None):
        """Run a repo script. Its own python3 calls resolve to this interpreter's environment,
        which has the probe dependencies, rather than whatever python3 is first on the PATH.
        `drop` keeps a variable in the caller's shell from reaching a script that would read it.
        `python` runs a Python script under another interpreter, the face extra's for the cast gate."""
        cmd = [python or sys.executable, *args] if args[0].endswith(".py") else ["bash", *args]
        path = os.path.dirname(sys.executable) + os.pathsep + os.environ.get("PATH", "")
        base = {k: v for k, v in os.environ.items() if k not in drop}
        return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=timeout,
                              env=dict(base, PATH=path, **(env or {})))

    def guard(self, name, payload):
        """Run one of the Claude Code guards the August shoots ran under, fed the hook JSON it
        reads. Exit 0 lets the spend through; anything else is the guard refusing it. A refusal
        quotes ids and private paths below its first line, so only that line is kept."""
        args = ["bash", os.path.join(ROOT, "guards", name)] + (["hook"] if name == "prop_gate.sh" else [])
        r = subprocess.run(args, input=json.dumps(payload), capture_output=True, text=True, timeout=120, cwd=ROOT)
        said = [x for x in (r.stdout + r.stderr).splitlines() if x.strip()]
        return r.returncode, self.clean(said[0].strip()) if said else ""

    def identity_file(self):
        pins = os.environ.get("IDENTITY_PINS", "")
        if not pins or not os.path.isfile(pins):
            raise LiveSetupError("IDENTITY_PINS is unset or not a file, and the identity guard passes every "
                                 "voice and look when it has none, so nothing here will spend on one")
        return pins

    def rows(self, kind, **match):
        return [r for r in self.ledger.rows() if r["kind"] == kind and all(r.get(k) == v for k, v in match.items())]

    # The voice: drawn, checked for accent drift, read back, and matched to the script.

    def voiced(self, step, spot, audio, text):
        """A take this run already drew and matched to this script, kept rather than paid for
        again when a step is re-entered."""
        script_path = os.path.join(os.path.dirname(audio), "script.txt")
        if not (os.path.isfile(audio) and os.path.isfile(script_path)):
            return False
        with open(script_path) as fh:
            if fh.read().strip() != text.strip():
                return False
        matches = self.rows("gate", step=step, spot=spot, check="script match")
        return bool(matches) and matches[-1].get("passed") is True

    def voice(self, step, spot, text, out_dir, stem):
        """Draw three takes through gates/voice_take.sh, keep a survivor, transcribe it, and
        check it says the script. Returns (ok, why)."""
        voice_id, key = need("ELEVENLABS_VOICE_ID"), need("ELEVENLABS_API_KEY")
        audio = os.path.join(out_dir, f"{stem}.mp3")
        if self.voiced(step, spot, audio, text):
            self.ledger.append("landing", step, spot=spot, status="REUSED", file=self.rel(audio), sha256=sha256(audio),
                               note="drawn and matched to this script earlier in this run")
            return True, ""
        rc, said = self.guard("block_unpinned_identity.sh", {
            "tool_name": "Bash", "tool_input": {"command": f"curl -X POST {ELEVEN}/v1/text-to-speech/{voice_id}"}})
        self.ledger.append("gate", step, spot=spot, check="identity pin, voice", passed=rc == 0,
                           voice=fingerprint(voice_id), said=said if rc else "")
        if rc != 0:
            return False, "the voice is not the pinned clone"
        script_path = os.path.join(out_dir, "script.txt")
        with open(script_path, "w") as fh:
            fh.write(text.strip() + "\n")
        rid = new_request_id()
        self.ledger.append("request", step, request_id=rid, spot=spot, engine="elevenlabs/eleven_v3",
                           voice=fingerprint(voice_id), draws=3, text=text.strip())
        r = self.script("gates/voice_take.sh", script_path, audio, "3", timeout=900)
        if r.returncode != 0 or not os.path.isfile(audio):
            self.ledger.append("landing", step, request_id=rid, status="FAILED", error=self.clean((r.stdout + r.stderr)[-600:]))
            return False, "no voice take survived the draw"
        probe = [x.strip() for x in r.stdout.splitlines() if "consensus vowel space" in x or x.startswith("SURVIVOR")]
        self.ledger.append("landing", step, request_id=rid, status="OK", file=self.rel(audio),
                           sha256=sha256(audio), seconds=duration(audio), probe=[self.clean(x) for x in probe])

        stt_path = os.path.join(out_dir, "stt.json")
        rid = new_request_id()
        self.ledger.append("request", step, request_id=rid, spot=spot, engine="elevenlabs/scribe_v1",
                           file=self.rel(audio))
        with open(audio, "rb") as fh:
            body, ctype = multipart({"model_id": "scribe_v1", "timestamps_granularity": "word", "language_code": "en"},
                                    {"file": (os.path.basename(audio), fh.read(), "audio/mpeg")})
        code, data = http("POST", f"{ELEVEN}/v1/speech-to-text", {"xi-api-key": key, "Content-Type": ctype}, body, 300)  # pii-allow: the key is read from the environment
        if not 200 <= code < 300:
            self.ledger.append("landing", step, request_id=rid, status="FAILED", http=code,
                               error=self.clean(data.decode(errors="replace")[:600]))
            return False, "the read-back failed"
        with open(stt_path, "wb") as fh:
            fh.write(data)
        self.ledger.append("landing", step, request_id=rid, status="OK", file=self.rel(stt_path),
                           text=as_json(data).get("text"))

        r = self.script("gates/script_match.sh", stt_path, script_path, timeout=120)
        self.ledger.append("gate", step, spot=spot, check="script match", passed=r.returncode == 0,
                           said=self.clean(r.stdout.strip()[-400:]))
        return (r.returncode == 0), ("" if r.returncode == 0 else "the take does not say the script")

    # Render: the scenes on the board's engine, and the narration.

    def edge(self, raw):
        """The edge probe's flag on one scene, or None when it is clean. A probe that could not
        read the scene raises a flag too, because unexamined is not clean."""
        r = self.script("gates/edge_clip_probe.py", raw, timeout=300)
        if r.returncode == 0:
            return None
        found = EDGE_FLAG.search(r.stdout)
        if r.returncode == 3 and found:
            return self.clean(found.group(0))
        return f"EDGE CLIP: the edge probe could not read this scene (exit {r.returncode}), so it needs a look"

    def cast(self, reference, clip):
        """The cast gate on one clip against the presenter's reference: PASS, FAIL or NOFACE, or
        None when it gave no reading its exit code agrees with, and the line it printed."""
        r = self.script("gates/cast_gate.py", reference, clip, python=os.environ.get("FACEPY", sys.executable),
                        timeout=900)
        m = CAST_LINE.search(r.stdout)
        if not m or {"PASS": 0, "FAIL": 1, "NOFACE": 3}[m["verdict"]] != r.returncode:
            return None, self.clean((r.stdout + r.stderr).strip()[-300:]), None
        return m["verdict"], self.clean(m.group(0)), m

    def presenter_reference(self, spot):
        """The presenter's face for this spot's scenes, cut once per run and kept with the takes.
        It comes from the closer take the run reuses, so the scenes are held to the face the
        closer shows, and from PRESENTER_STILL when the closer is still to be rendered. It is
        resolved before any scene is paid for."""
        out = os.path.join(self.dir(f"{spot}-cast"), "reference.jpg")
        if os.path.isfile(out):
            return out
        still, closer_dir = os.environ.get("PRESENTER_STILL", ""), os.environ.get("CLOSER_FROM", "")
        if closer_dir:
            src, source = os.path.join(closer_dir, "render.mp4"), "closer take"
        elif still:
            src, source = still, "still"
        else:
            raise LiveSetupError("a spot that shows the presenter needs her face: set PRESENTER_STILL, or CLOSER_FROM "
                                 "to a closer take")
        if not os.path.isfile(src):
            raise LiveSetupError(f"the presenter's {source} named in the environment is not a file")
        r = self.script("gates/cast_gate.py", "--reference", src, out, python=os.environ.get("FACEPY", sys.executable),
                        timeout=900)
        if r.returncode != 0 or not os.path.isfile(out):
            raise LiveSetupError(f"no face could be cut from the presenter's {source}, so her scenes cannot be held to her")
        self.ledger.append("landing", "render", spot=spot, status="OK", file=self.rel(out), sha256=sha256(out),
                           source=source, note="the presenter's reference")
        return out

    def cast_check(self, spot, s, reference, raw, failed, why, flags, shows_presenter=True):
        """Read one scene back against the presenter. Every scene is read, because a person the
        board never named, a barista or a crowd, is still a person on screen. A face that is not
        hers fails the scene, which re-rolls it once. No face is expected in a scene written
        without her, and anywhere else goes to the eye as a flag, like a scene with no reading."""
        verdict, reading, m = self.cast(reference, raw)
        extra = {"unreadable": True} if verdict is None else {}
        self.ledger.append("gate", "render", spot=spot, scene=f"{spot}-{s}", check="cast", passed=verdict == "PASS",
                           reading=reading, **extra)
        if verdict == "FAIL":
            failed.append(s)
            who = "a different person from the presenter" if shows_presenter else "a person on screen who is not the presenter"
            if int(m["strangers"]) and float(m["sim"]) >= float(m["floor"]):
                why[s] = f"a second person on screen who is not the presenter, in {m['strangers']} of the frames read"
            else:
                why[s] = f"{who}, face similarity {m['sim']} under the gate's {m['floor']}"
        elif verdict == "NOFACE" and shows_presenter:
            flags[s] = "CAST: no face found to match against the presenter. Look before shipping."
        elif verdict is None:
            flags[s] = "CAST: the cast gate could not read this scene, so it needs a look"

    def dropped(self, handle, auth):
        """Whether the vendor has confirmed it no longer has a job: its status and its result both
        come back not found, twice, a poll apart. One 404 can be a lookup that lagged, and taking
        it as gone would pay for the scene a second time."""
        _, _, status_url, response_url = handle
        for attempt in range(2):
            if attempt:
                time.sleep(POLL_SECONDS)
            if http("GET", status_url, auth, timeout=60)[0] not in GONE:
                return False
            if http("GET", response_url, auth, timeout=120)[0] not in GONE:
                return False
        return True

    def earlier(self, spot, scene, prompt):
        """This run's last request for this scene with this prompt: its id, what the vendor
        answered, and whether it is still owed, sent and never landed or timed out."""
        asked = [r for r in self.rows("request", step="render", scene=f"{spot}-{scene}") if r.get("prompt") == prompt]
        # A request the vendor refused never became a job. It is not owed, and it hides nothing
        # about the one sent before it, which may be a finished render still to collect.
        refused = {r["request_id"] for r in self.rows("landing", status="REFUSED")}
        asked = [r for r in asked if r["request_id"] not in refused] or asked[-1:]
        if not asked:
            return None
        rid = asked[-1]["request_id"]
        queued = self.rows("queued", request_id=rid)
        landed = self.rows("landing", request_id=rid)
        status = landed[-1]["status"] if landed else None
        # Rows written before UNCOLLECTED covered a held-back result logged one as FAILED, with the
        # vendor's non-2xx code beside it. That render finished too, so it is owed the same way.
        if status == "FAILED" and queued and held_back(landed[-1].get("http") or 200):
            status = "UNCOLLECTED"
        handle = (rid, queued[-1]["vendor_id"], queued[-1]["status_url"], queued[-1]["response_url"]) if queued else None
        # Sent, and the vendor never said whether it took it: the POST failed on the network, came
        # back with no id, or the process died before the answer was written down.
        unknown = status == "UNCONFIRMED" or (not queued and not landed)
        return {"request_id": rid, "seq": asked[-1]["seq"], "owed": bool(handle) and status in OWED,
                "landed": status in ("OK", "REUSED"), "landed_seq": landed[-1]["seq"] if landed else None,
                "unconfirmed": unknown, "handle": handle}

    def read_back_failed(self, spot, scene, since):
        """Whether the take that landed at row `since` was failed by its read-back: the newest cast
        reading of the scene after that row says FAIL. No face where one was expected, or a reading
        the gate could not make, is a flag for the eye and not a failure, so neither counts, though
        both are written with passed false."""
        readings = [r for r in self.rows("gate", step="render", scene=f"{spot}-{scene}", check="cast") if r["seq"] > since]
        m = CAST_LINE.search(readings[-1].get("reading") or "") if readings else None
        return bool(m) and m["verdict"] == "FAIL"

    def render(self, state):
        board, spot_def = load_spot(state["board"], state["spot"])
        spot, scenes = state["spot"], spot_def.get("scenes", {})
        engine = engine_for(board, spot_def)
        if engine not in ENGINE_INPUT:
            raise LiveSetupError(f"no request shape recorded for {engine}; add it to ENGINE_INPUT from its schema")
        changes = state.get("changes") or {}
        last = (state.get("verdict") or {}).get("render") or {}
        asked = scene_key(spot, scenes, changes["scene"]) if changes.get("scene") else None
        if asked:
            todo = [asked]
        elif last.get("failed"):
            todo = [s for s in last["failed"] if s in scenes]
        else:
            todo = sorted(scenes)
        auth = {"Authorization": f"Key {need('FAL_KEY')}"}
        failed, why, flags, pending, unconfirmed, fresh = [], {}, {}, {}, [], []
        # A person who re-enters the run after an unconfirmed request has checked the vendor and
        # chosen to send again, so only a request sent after the last re-entry holds a scene back.
        reentered = max([r["seq"] for r in self.rows("resumed")] or [0])
        texts = {s: changes["prompt"] if asked == s and changes.get("prompt") else scenes[s] for s in todo}
        # The board gate holds the board's lines to this rule. A person's new prompt from the eye meets
        # it here, before anything is paid for, since a stranger in it would render where no cast
        # gate reads it.
        stranger = [asked] if asked and changes.get("prompt") and not cast_ok(changes["prompt"]) else []
        if stranger:
            return {"failed": stranger, "why": {s: f"the prompt shows a person with no {PLACEHOLDER}" for s in stranger},
                    "flags": {}, "rendered": [], "fresh": [], "unconfirmed": []}
        cast = {s: PLACEHOLDER in texts[s] for s in todo}
        engines = {s: REFERENCE_ENGINE.get(engine) if cast[s] else engine for s in todo}
        if any(cast.values()) and REFERENCE_ENGINE.get(engine) not in ENGINE_INPUT:
            raise LiveSetupError(f"{engine} has no reference path here, so a scene that shows the presenter "
                                 "cannot be held to her face")
        # The presenter's face is resolved before anything is paid for. It is sent with every scene
        # that shows her, because a text prompt cannot hold a face. Whenever a face source is set,
        # every scene is read back against it, since a person the board never named is still a
        # person on screen. A spot with nobody written in it and no face source runs without it.
        wanted = any(cast.values()) or os.environ.get("CLOSER_FROM") or os.environ.get("PRESENTER_STILL")
        reference = self.presenter_reference(spot) if wanted else None
        ref_uri = ref_sha = None
        if any(cast.values()):
            with open(reference, "rb") as fh:
                ref_uri = "data:image/jpeg;base64," + base64.b64encode(fh.read()).decode()
            ref_sha = sha256(reference)
        prompts = {s: scene_prompt(board, cast_text(spot_def, texts[s]) if cast[s] else texts[s]) for s in todo}
        befores = {s: self.earlier(spot, s, prompts[s]) for s in todo}
        # A request that may already have been billed holds every new request in the pass, and the
        # narration, until a person has looked at the vendor's queue.
        held = any(b and b["unconfirmed"] and b["seq"] > reentered for b in befores.values())
        for s in todo:
            prompt, before = prompts[s], befores[s]
            raw = os.path.join(self.dir(f"{spot}-{s}"), "raw.mp4")
            if before and before["owed"]:
                # Sent already and never collected, or timed out: the vendor may still deliver
                # it and bill it, so it is collected rather than sent a second time. It is asked
                # about once first, because a job the vendor has dropped is never coming, and
                # waiting on it only runs the clock out.
                if not self.dropped(before["handle"], auth):
                    pending[s] = before["handle"]
                    continue
                self.ledger.append("landing", "render", request_id=before["request_id"], vendor_id=before["handle"][1],
                                   status="FAILED", http=404, during="status", error="the vendor no longer has this job")
                before = None
            if before and before["unconfirmed"] and before["seq"] > reentered:
                unconfirmed.append(s)
                why[s] = (f"{before['request_id']} was sent and never confirmed, so it may have been billed. Look for it "
                          "in the vendor's queue before re-entering, which sends it again")
                continue
            # A scene whose newest take landed is never sent again unless its read-back failed it or
            # a person asked for a new one. The ledger decides that, not the checkpoint: a re-entry
            # resumes from a state whose failed list can be older than a take that landed after it,
            # or emptier than a read-back written before a crash. The checkpoint only picks the scenes.
            held_take = before and before["landed"] and os.path.isfile(raw) and not asked
            if held_take and not self.read_back_failed(spot, s, before["landed_seq"]):
                # A re-entry after the spend: this run already holds this scene with this prompt.
                self.ledger.append("landing", "render", request_id=before["request_id"], spot=spot, scene=f"{spot}-{s}",
                                   status="REUSED", file=self.rel(raw), sha256=sha256(raw))
                flag = self.edge(raw)
                if flag:
                    flags[s] = flag
                if reference:
                    self.cast_check(spot, s, reference, raw, failed, why, flags, shows_presenter=cast[s])
                continue
            if held or unconfirmed:
                why[s] = "not sent, a request that may have been billed is waiting for a person"
                continue
            rid, eng = new_request_id(), engines[s]
            self.ledger.append("request", "render", request_id=rid, spot=spot, scene=f"{spot}-{s}", engine=eng,
                               prompt=prompt, params=ENGINE_INPUT[eng], est_usd=PRICE_PER_SCENE.get(eng),
                               **({"reference_sha256": ref_sha} if cast[s] else {}),
                               why=changes.get("reason") if asked == s else (last.get("why") or {}).get(s),
                               prompt_reused=bool(before), asked_by_person=asked == s)
            body = {"prompt": prompt, **ENGINE_INPUT[eng], **({"image_urls": [ref_uri]} if cast[s] else {})}
            code, data = http("POST", f"{FAL}/{eng}", {**auth, "Content-Type": "application/json"},
                              json.dumps(body).encode())
            j = as_json(data)
            if code == 0 or (200 <= code < 300 and "request_id" not in j):
                # The vendor may have taken it. Sending again could pay twice, so a person checks.
                self.ledger.append("landing", "render", request_id=rid, status="UNCONFIRMED", http=code,
                                   error=self.clean(data.decode(errors="replace")[:600]))
                unconfirmed.append(s)
                why[s] = f"{rid} was sent and never confirmed, so it may have been billed"
                continue
            if not 200 <= code < 300:
                self.ledger.append("landing", "render", request_id=rid, status="REFUSED", http=code,
                                   error=self.clean(data.decode(errors="replace")[:600]))
                failed.append(s)
                why[s] = "the queue refused the request"
                continue
            pending[s] = (rid, j["request_id"], j.get("status_url"), j.get("response_url"))
            self.ledger.append("queued", "render", request_id=rid, vendor_id=j["request_id"],
                               status_url=j.get("status_url"), response_url=j.get("response_url"))

        for s, (rid, vendor_id, status_url, response_url) in pending.items():
            status, deadline = None, time.time() + WAIT_LIMIT
            while time.time() < deadline:
                code, data = http("GET", status_url, auth, timeout=60)
                if 200 <= code < 300:
                    status = as_json(data).get("status")
                    if status == "COMPLETED":
                        break
                if code in GONE:
                    if 200 <= http("GET", response_url, auth, timeout=120)[0] < 300:
                        status = "COMPLETED"    # the status record lapsed, and the result is there
                        break
                    if self.dropped((rid, vendor_id, status_url, response_url), auth):
                        status = "GONE"
                        break
                time.sleep(POLL_SECONDS)
            if status == "GONE":
                self.ledger.append("landing", "render", request_id=rid, vendor_id=vendor_id, status="FAILED", http=code,
                                   during="status", error="the vendor no longer has this job")
                failed.append(s)
                why[s] = "the vendor no longer has this job"
                continue
            if status != "COMPLETED":
                self.ledger.append("landing", "render", request_id=rid, vendor_id=vendor_id, status="TIMEOUT", last=status)
                failed.append(s)
                why[s] = f"still {status} after {WAIT_LIMIT // 60} minutes"
                continue
            code, data = http("GET", response_url, auth, timeout=120)
            if code == 422:
                # fal hands a content rejection back as COMPLETED, then a 422 on the result
                self.ledger.append("landing", "render", request_id=rid, vendor_id=vendor_id, status="REJECTED",
                                   error=self.clean(data.decode(errors="replace")[:800]))
                failed.append(s)
                why[s] = "the engine rejected the output"
                continue
            if held_back(code):
                # The status said COMPLETED, so the render may exist and may be billed. A result the
                # vendor holds back for now, behind a locked account, a rate limit or its own error,
                # is collected on the next pass. Recorded as FAILED it was sent again, paying twice.
                # A locked account also closes a job it never ran this way, a second after the POST,
                # and drops it later, which the next pass confirms before it sends the scene again.
                self.ledger.append("landing", "render", request_id=rid, vendor_id=vendor_id, status="UNCOLLECTED",
                                   http=code, during="result", error=self.clean(data.decode(errors="replace")[:600]))
                failed.append(s)
                why[s] = "the video was held back by the vendor"
                continue
            if not 200 <= code < 300:
                # Gone, a 404 or any other refusal that waiting will not change. Nothing is left to
                # collect, so the scene is sent again rather than waited on forever.
                self.ledger.append("landing", "render", request_id=rid, vendor_id=vendor_id, status="FAILED", http=code,
                                   during="result", error=self.clean(data.decode(errors="replace")[:600]))
                failed.append(s)
                why[s] = "the finished video is gone from the vendor"
                continue
            url = (as_json(data).get("video") or {}).get("url")
            if not url:
                self.ledger.append("landing", "render", request_id=rid, vendor_id=vendor_id, status="FAILED", http=code,
                                   error=self.clean(data.decode(errors="replace")[:600]))
                failed.append(s)
                why[s] = "no video came back"
                continue
            raw = os.path.join(self.dir(f"{spot}-{s}"), "raw.mp4")
            try:
                urllib.request.urlretrieve(url, raw)
            except (urllib.error.URLError, OSError) as e:
                self.ledger.append("landing", "render", request_id=rid, vendor_id=vendor_id, status="UNCOLLECTED",
                                   during="download", error=self.clean(f"{type(e).__name__}: {e}"))
                failed.append(s)
                why[s] = "the finished video could not be downloaded"
                continue
            flag = self.edge(raw)
            if flag:
                flags[s] = flag
            fresh.append(s)
            self.ledger.append("landing", "render", request_id=rid, vendor_id=vendor_id, status="OK",
                               file=self.rel(raw), sha256=sha256(raw), bytes=os.path.getsize(raw), seconds=duration(raw),
                               edge_clip=flag or "clean")
            if reference:
                self.cast_check(spot, s, reference, raw, failed, why, flags, shows_presenter=cast[s])

        verdict = {"failed": failed, "why": why, "flags": flags, "rendered": todo, "fresh": fresh,
                   "unconfirmed": unconfirmed}
        if unconfirmed:
            return verdict      # the narration waits with the scenes
        vo = self.dir(f"{spot}-vo")
        if not os.path.isfile(os.path.join(vo, "narration.mp3")) or "narration" in (last.get("failed") or []):
            ok, reason = self.voice("render", spot, spot_def["narration"], vo, "narration")
            if not ok:
                failed.append("narration")
                why["narration"] = reason
        return verdict

    # Closer: reuse a take that exists, or render one on the pinned engine.

    def closer(self, state):
        _, spot_def = load_spot(state["board"], state["spot"])
        spot = state["spot"]
        d = self.dir(f"{spot}-av")
        render = os.path.join(d, "render.mp4")
        changes = state.get("changes") or {}
        asked = [fingerprint(changes["look"]) if changes.get("look") else None, changes.get("engine")]
        on_file = list((state.get("artifacts") or {}).get("closer_inputs") or [None, None])
        wants_new = any(asked) and asked != on_file
        src = os.environ.get("CLOSER_FROM", "")
        if os.path.isfile(render) and not wants_new:
            source, inputs = "this run", on_file
        elif src and not wants_new:
            for name in ("render.mp4", "upload.mp3", "stt.json", "script.txt"):
                shutil.copy2(os.path.join(src, name), os.path.join(d, name))
            said = " ".join(open(os.path.join(d, "script.txt")).read().split())
            source, inputs = "/".join(os.path.normpath(src).split(os.sep)[-2:]), [None, None]
            if said != " ".join(spot_def["closer"].split()):
                os.remove(render)   # a take that says another line never counts as this run's closer
                self.ledger.append("gate", "closer", spot=spot, check="reused take says this closer", passed=False,
                                   source=source)
                return {"pass": False, "why": "the take to reuse says a different closer line"}
            # script.txt is what the take was asked to say. stt.json is what it said when read back.
            r = self.script("gates/script_match.sh", os.path.join(d, "stt.json"), os.path.join(d, "script.txt"),
                            timeout=120)
            self.ledger.append("gate", "closer", spot=spot, check="reused take's read-back says this closer",
                               passed=r.returncode == 0, said=self.clean(r.stdout.strip()[-400:]), source=source)
            if r.returncode != 0:
                os.remove(render)
                return {"pass": False, "why": "the take to reuse does not say this closer when it is read back"}
            # A take made outside this run carries no record of the look and voice behind it. The
            # ledger says so, and whoever set CLOSER_FROM is the one vouching for it.
            self.ledger.append("landing", "closer", spot=spot, status="REUSED", source=source, identity="unrecorded",
                               file=self.rel(render), sha256=sha256(render), seconds=duration(render))
        else:
            ok, reason = self.render_closer(spot, spot_def, d, changes)
            if not ok:
                return {"pass": False, "why": reason}
            source, inputs = "rendered", asked
        r = self.script("gates/jaw_gate.py", render, drop=("SG_START", "SG_DUR"), timeout=900)
        m = JAW_LINE.search(r.stdout)
        reading = self.clean(m.group(0)) if m else ""
        unreadable = not m or m.group(1) == "UNMEASURED"
        passed = bool(m) and m.group(1) == "PASS" and r.returncode == 0
        extra = {"unreadable": True, "error": self.clean((r.stderr or r.stdout).strip()[-300:])} if unreadable else {}
        self.ledger.append("gate", "closer", spot=spot, check="jaw", passed=passed, reading=reading, source=source, **extra)
        v = {"pass": passed, "jaw": reading, "artifacts": {"closer": render, "closer_inputs": inputs}}
        if unreadable:
            v["unreadable"] = True
        reference = os.path.join(self.takes, f"{spot}-cast", "reference.jpg")
        if has_cast(spot_def) and os.path.isfile(reference):
            # The scenes were held to this face, so the closer must be the same person.
            verdict, said, _ = self.cast(reference, render)
            self.ledger.append("gate", "closer", spot=spot, check="cast", passed=verdict == "PASS", reading=said,
                               source=source, **({"unreadable": True} if verdict is None else {}))
            if verdict is None:
                v.update(unreadable=True, **{"pass": False})
            elif verdict != "PASS":
                v.update(why="the closer is not the presenter the scenes were rendered from", **{"pass": False})
        return v

    def owed_closer(self, spot, look, engine):
        """A closer render this run asked for and never collected, polled before paying for another."""
        asked = [r for r in self.rows("request", step="closer", spot=spot, engine=f"heygen/{engine}")
                 if r.get("look") == fingerprint(look)]
        if not asked:
            return None
        rid = asked[-1]["request_id"]
        queued = self.rows("queued", request_id=rid)
        landed = self.rows("landing", request_id=rid)
        if queued and (not landed or landed[-1]["status"] in OWED):
            return rid, queued[-1]["vendor_id"]
        return None

    def render_closer(self, spot, spot_def, d, changes):
        key, look = need("HEYGEN_API_KEY"), changes.get("look") or need("CLOSER_LOOK_ID")
        engine = changes.get("engine") or "avatar_iii"
        self.secrets.add(look)
        # The guards come first, so a refused look costs nothing, not even the voice.
        payload = {"tool_name": "mcp__heygen__create_video_from_avatar",
                   "tool_input": {"avatarId": look, "engine": {"type": engine}, "aspectRatio": "1:1",
                                  "fit": "cover", "resolution": "1080p"}}
        for name in ("block_unpinned_identity.sh", "prop_gate.sh"):
            rc, said = self.guard(name, payload)
            self.ledger.append("gate", "closer", spot=spot, check=name, passed=rc == 0, look=fingerprint(look),
                               said=said if rc else "")
            if rc != 0:
                return False, f"{name} refused the render before any spend"
        ok, reason = self.voice("closer", spot, spot_def["closer"], d, "upload")
        if not ok:
            return False, reason
        auth = {"x-api-key": key}
        owed = self.owed_closer(spot, look, engine)
        if owed:
            rid, video = owed
        else:
            up = new_request_id()
            self.ledger.append("request", "closer", request_id=up, spot=spot, engine="heygen/assets",
                               file=self.rel(os.path.join(d, "upload.mp3")))
            with open(os.path.join(d, "upload.mp3"), "rb") as fh:
                body, ctype = multipart({}, {"file": ("upload.mp3", fh.read(), "audio/mpeg")})
            code, data = http("POST", f"{HEYGEN}/v3/assets", {**auth, "Content-Type": ctype}, body, 300)
            asset = (as_json(data).get("data") or {}).get("asset_id")
            if not 200 <= code < 300 or not asset:
                self.ledger.append("landing", "closer", request_id=up, status="FAILED", http=code,
                                   error=self.clean(data.decode(errors="replace")[:600]))
                return False, "the audio upload failed"
            self.ledger.append("landing", "closer", request_id=up, status="OK", vendor_id=asset)
            rid = new_request_id()
            req = {"type": "avatar", "avatar_id": look, "audio_asset_id": asset, "engine": {"type": engine},
                   "aspect_ratio": "1:1", "fit": "cover", "resolution": "1080p", "title": f"{spot} closer"}
            self.ledger.append("request", "closer", request_id=rid, spot=spot, engine=f"heygen/{engine}",
                               look=fingerprint(look),
                               params={k: v for k, v in req.items() if k not in ("avatar_id", "audio_asset_id")})
            code, data = http("POST", f"{HEYGEN}/v3/videos", {**auth, "Content-Type": "application/json"},
                              json.dumps(req).encode())
            video = (as_json(data).get("data") or {}).get("video_id")
            if code == 0 or (200 <= code < 300 and not video):
                self.ledger.append("landing", "closer", request_id=rid, status="UNCONFIRMED", http=code,
                                   error=self.clean(data.decode(errors="replace")[:600]))
                return False, (f"{rid} was sent and never confirmed, so it may have been billed. Look for a render titled "
                               f"'{spot} closer' before re-entering")
            if not 200 <= code < 300:
                self.ledger.append("landing", "closer", request_id=rid, status="REFUSED", http=code,
                                   error=self.clean(data.decode(errors="replace")[:600]))
                return False, "the render was refused"
            self.ledger.append("queued", "closer", request_id=rid, vendor_id=video)
        deadline, info = time.time() + WAIT_LIMIT, {}
        while time.time() < deadline:
            code, data = http("GET", f"{HEYGEN}/v3/videos/{video}", auth, timeout=60)
            if 200 <= code < 300:
                info = as_json(data).get("data") or {}
                if info.get("status") in ("completed", "failed"):
                    break
            time.sleep(POLL_SECONDS)
        if info.get("status") != "completed" or not info.get("video_url"):
            status = "FAILED" if info.get("status") == "failed" else "TIMEOUT"
            self.ledger.append("landing", "closer", request_id=rid, vendor_id=video, status=status,
                               last=info.get("status"), error=self.clean(f"{info.get('failure_code')} {info.get('failure_message')}"))
            return False, "the render did not complete"
        render = os.path.join(d, "render.mp4")
        try:
            urllib.request.urlretrieve(info["video_url"], render)
        except (urllib.error.URLError, OSError) as e:
            self.ledger.append("landing", "closer", request_id=rid, vendor_id=video, status="UNCOLLECTED", during="download",
                               error=self.clean(f"{type(e).__name__}: {e}"))
            return False, "the finished render could not be downloaded"
        self.ledger.append("landing", "closer", request_id=rid, vendor_id=video, status="OK", file=self.rel(render),
                           sha256=sha256(render), seconds=duration(render))
        return True, ""

    # Build: shoots/build-ad.sh, with every parameter on the record.

    def build(self, state):
        _, spot_def = load_spot(state["board"], state["spot"])
        spot = state["spot"]
        # Numbered from the ledger, not the checkpoint, so a run re-entered from an earlier step
        # never writes over a master it already built.
        version = 1 + len(self.rows("build", spot=spot))
        nudge = float((state.get("changes") or {}).get("nudge", 0) or 0)
        # The build crops each scene to its centre square and scales it to 1080, so a 720p scene is
        # enlarged one and a half times. Nothing else records that, so the build row does.
        sizes = {s: frame_size(os.path.join(self.takes, f"{spot}-{s}", "raw.mp4")) for s in sorted(spot_def.get("scenes", {}))}
        shortest = [min(wh) for wh in sizes.values() if wh]
        params = {"scene_px": {s: f"{wh[0]}x{wh[1]}" if wh else None for s, wh in sizes.items()},
                  "upscale": round(1080 / min(shortest), 2) if shortest else None,
                  "brand": spot_def.get("brand", spot), "tag": spot_def.get("card", ""),
                  "bed": os.path.basename(need("BED")), "closer_nudge": nudge, "closer_autoalign": 0,
                  "script": "shoots/build-ad.sh", "master": "shoots/master.sh, loudnorm I=-16 TP=-2 LRA=11",
                  "version": version}
        self.ledger.append("build", "build", spot=spot, **params)
        env = {"TAKES": self.takes, "FILM2": need("FILM2"), "BED": need("BED"), "BRAND": params["brand"],
               "TAG": params["tag"], "CLOSER_AUTOALIGN": "0", "CLOSER_NUDGE": str(nudge),
               "GATES": os.path.join(ROOT, "gates"), "FACEPY": os.environ.get("FACEPY", sys.executable)}
        r = self.script("shoots/build-ad.sh", spot, f"{spot}-av", env=env)
        out = os.path.join(self.takes, f"out-{spot}-{spot}-av")
        if r.returncode != 0 or not os.path.isfile(os.path.join(out, "ad.mp4")):
            self.ledger.append("landing", "build", spot=spot, status="FAILED", error=self.clean((r.stdout + r.stderr)[-800:]))
            return {"pass": False}
        masters = os.path.join(self.run_dir, "masters")
        os.makedirs(masters, exist_ok=True)
        master = os.path.join(masters, f"{spot}-v{version}.mp4")
        # The gates read the captions where the build wrote them: ad_gates.sh finds the scene
        # segments it measures the closer's placement against beside captions.json.
        captions = os.path.join(out, "captions.json")
        srt = os.path.join(out, "clean.srt")
        m = self.script("shoots/master.sh", os.path.join(out, "ad.mp4"), master, timeout=600)
        if m.returncode != 0 or not os.path.isfile(master):
            self.ledger.append("landing", "build", spot=spot, status="FAILED", during="mastering",
                               error=self.clean((m.stdout + m.stderr)[-600:]))
            return {"pass": False}
        self.ledger.append("landing", "build", spot=spot, status="OK", file=self.rel(master), sha256=sha256(master),
                           seconds=duration(master), log=self.lines(r.stdout, 6))
        return {"pass": True, "artifacts": {"master": master, "captions": captions, "srt": srt}}

    # Ad gates and ship gate: the repo's gates, read off their machine lines.

    def ad_gates(self, state):
        a = state["artifacts"]
        r = self.script("gates/ad_gates.sh", a["master"], a["captions"],
                        env={"FACEPY": os.environ.get("FACEPY", sys.executable)}, timeout=900)
        line = AD_GATES_LINE.search(r.stdout)
        mouth = MOUTH_LINE.search(r.stdout)
        # A mouth FAIL with no verdict line from the probe is a crash, not a measurement, and a
        # crash read as FAIL would stop the run for a new look nobody needed.
        crashed = bool(line) and line.group(3) == "fail" and not mouth
        if not line:
            v = {"unreadable": True, "caption": "unreadable", "drift": "unreadable", "mouth": "unreadable"}
        else:
            v = {"caption": line.group(1), "drift": line.group(2), "mouth": "unreadable" if crashed else line.group(3),
                 "corr": float(mouth.group(1)) if mouth else None,
                 "lag_s": float(mouth.group(2)) if mouth else None}
            if r.returncode == 64 or "unreadable" in (v["caption"], v["drift"], v["mouth"]):
                v["unreadable"] = True
        self.ledger.append("gate", "ad_gates", spot=state["spot"], master=self.rel(a["master"]), **v,
                           said=self.lines(r.stdout))
        return v

    def ship_gate(self, state):
        a = state["artifacts"]
        with open(a["captions"]) as fh:
            cj = json.load(fh)
        changes = state.get("changes") or {}
        arrow_ok, replay_ok = changes.get("arrow_ok"), changes.get("replay_ok")
        # The probes run on the master, as they did in August. The side-band motion measure
        # reads the scenes, from the first frame to the closer, since the closer is a talking
        # head whose replay the replay probe judges. A replay goes to the eye unless a reader
        # has already approved it, and then their reason is the override the gate logs.
        env = {"TIMEOK": AD_FICTION, "ARROW_WINDOW": f"0:{float(cj['closer_start']):.2f}"}
        if replay_ok:
            env["REPLAYOK"] = replay_ok
        r = self.script("guards/ship_gate.sh", a["master"], a["srt"], *(["--arrow-ok"] if arrow_ok else []),
                        env=env, drop=("REPLAYOK", "RAW", "SG_START", "SG_DUR", "ARROW_WINDOW"), timeout=1800)
        text = r.stdout + r.stderr
        cause = None
        if r.returncode == 64:
            cause = "unreadable"
        elif r.returncode == 1 and SHIP_HOLDS["letterbox"] in text:
            cause = "letterbox"
        elif r.returncode == 3 and SHIP_HOLDS["directional"] in text:
            cause = "directional"
        elif r.returncode == 3 and SHIP_HOLDS["replay"] in text:
            cause = "replay"
        elif r.returncode != 0:
            cause = "held"
        loud = self.script("gates/loudness_gate.py", a["master"], timeout=600)
        reading = LOUDNESS_LINE.search(loud.stdout)
        if cause is None and not (reading and reading.group(1) == "PASS" and loud.returncode == 0):
            cause = "loudness" if reading and reading.group(1) == "FAIL" else "unreadable"
        slit = SLIT_LINE.search(text)
        kept = None
        if slit and os.path.isfile(slit.group(1)):
            # Kept with the run, where the person asked to read it will find it, days later if need be.
            os.makedirs(os.path.join(self.run_dir, "evidence"), exist_ok=True)
            kept = os.path.join(self.run_dir, "evidence", os.path.basename(slit.group(1)))
            shutil.copy2(slit.group(1), kept)
        turn = REPLAY_VERTEX.search(text)
        probe = REPLAY_VERDICT.search(text)
        v = {"pass": cause is None, "cause": cause, "loudness": self.clean(reading.group(0)) if reading else "",
             "slit": self.rel(kept) if kept else None, "replay": self.clean(probe.group(1).strip()) if probe else None,
             "replay_turn_s": float(turn.group(1)) if turn else None}
        self.ledger.append("gate", "ship_gate", spot=state["spot"], master=self.rel(a["master"]), **v,
                           overrides={"time": AD_FICTION, "replay": replay_ok, "arrow": arrow_ok},
                           said=self.lines(text))
        return v

    # Deliver: a local copy, since the private delivery channel stays out of this repo.

    def deliver(self, state):
        master = state["artifacts"]["master"]
        out_dir = os.path.join(self.run_dir, "delivered")
        os.makedirs(out_dir, exist_ok=True)
        out = os.path.join(out_dir, os.path.basename(master))
        shutil.copy2(master, out)
        earlier = [r["file"] for r in self.rows("deliver") if r.get("file") != self.rel(out)]
        self.ledger.append("deliver", "deliver", spot=state["spot"], file=self.rel(out), sha256=sha256(out),
                           seconds=duration(out), supersedes=earlier[-1] if earlier else None)
        return {"delivered": True, "artifacts": {"delivered": out}}
