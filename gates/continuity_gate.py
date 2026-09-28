#!/usr/bin/env python3
"""continuity_gate.py: does what a shot shows stay what it was, from its first frame to its last?

    continuity_gate.py <clip> [--prop <what must persist>]... [--story <what the shot is meant to show>]
                       [--ignore x0,y0,x1,y1] [--span <from>:<to>] [--presenter] [--out <findings.json>]
    continuity_gate.py --first-frame <image> --prop "<what must be visible>" [--prop "..."]... [--out <findings.json>]
    continuity_gate.py --validate [<labels.json>]

Every other gate reads a face, a frame's edge, a caption or a whole frame against another. None of
them follows an object through time, and on 2026-09-27 the author watched three ads the graph (the
LangGraph state machine that runs the whole pipeline) shot and caught three breaks nothing had
flagged. In the Perplexity master the open laptop on the desk, its screen up at 2 to 4 s, is a flat
keyboard slab from about 7 s. In the same master flying paper hides her face and blurs the opening
seconds. Behind the Grok presenter the street moves on its own, because avatar_iii, HeyGen's avatar
engine used for the closer, invents traffic the still never held: a bicycle rides into a sign and a
car loops.

So the gate asks two questions of a clip. PROPS: is each named prop present and unchanged in every
frame, and where does it first vanish, change form or pop in? BACKGROUND: does anything appear from
nowhere, vanish, pass into or through something solid, or repeat the same motion?

On a story shot a vision judge answers both. The clip is sampled FPS times a second, the frames are
laid out in timestamped grids of COLS by COLS, and VOTES lean calls to MODEL, asked at once, each read
every grid with the shot's own words beside them, since a warehouse the story says rises out of a
studio is not a break. Each vote answers strict JSON that names frames by their stamps, and an answer
that is not that JSON, contradicts itself or names a time no frame shows is no reading, never a guess.
One reading is not a ruler: one of three runs failed a Z.ai cut the author passed, and two passed it.
So an axis fails only when every vote reads it and every vote names a break, and it holds when no vote
names one and most read it clean. A break some votes name and some do not is a split, REVIEW, which
costs the author a look and never a re-shoot, while a real break is caught outright. On a FAIL the
break named is the median of the votes' earliest, so one vote naming a stray early frame cannot move
it, and on a REVIEW it is the earliest a dissenting vote named, where the eye should look.

On a presenter take (--presenter) the background is measured instead, because the camera holds
still and the measure is known. She is matted out of every frame with RobustVideoMatting, the matte
grown by GROW of the frame's width, and what is left is differenced frame to frame and against the
clip's own median. The largest moving patch has to stay under PAIR_BLOB pixels frame to frame and
under MEDIAN_BLOB against the median, both at 1080 by 1080 and scaled by area. Both limits come from
the background check the closer renders were first measured with, outside this repository, set on
that night's renders, where every Grok take that moved read thousands of pixels and every take that
held still read 0. No labelled pair on either axis is in evals/labels.csv, so evals/derive.py counts
both AUTHORED. The matte needs torch, which the repo's own interpreter does not carry, so a presenter
take runs under MATTEPY's.

A verdict here stands only while it reproduces the author's labels. --validate runs the gate for real
on every case in evals/continuity-labels.json, judge calls included, prints each axis's vote tally and
exits 1 on any miss, which means this file is wrong, never the eye. A FAIL label agrees only with a
FAIL whose break on the labelled axis falls inside the labelled window, and a REVIEW on it is a miss.
A REVIEW on a PASS label is deferred to the eye, counted apart, and not a miss. The labelled set is
thin, and --validate prints its size every time it reports. A case held outside the repository names
its directory by an environment variable, ADS8_TAKES for the ads8 closer takes (ads8, one of the ad
batches shot in August 2026, before the graph existed), which --validate needs set.

Exit 0 PASS, 1 FAIL, 2 REVIEW, the code gates/ad_gates.sh reads as a mouth to review, and 64 UNREAD
or a clip that cannot be read. The machine line is always the last line printed:
CONTINUITY_GATE props=<ok|fail|split|-> background=<ok|fail|split|-> first_break=<seconds|-> verdict=<PASS|FAIL|REVIEW|UNREAD>
A dash is a question not asked, props when none were named, or one that could not be read. The frame
level findings, every vote's breaks tagged with its vote, go to a JSON sidecar beside the clip unless
--out names one, never over an earlier one, and the grids the judge read or the strip the ruler cut go
beside it for the eye.

A board names its props before anything is shot, and a chain starts its first scene from a whole frame
of its character, so that frame can be read before any of the chain is paid for. --first-frame <image>
asks a narrower question of that one still: is each named prop visible in it? The same votes and the
same strict JSON discipline apply, and a vote that does not account for every prop exactly once is no
reading for any of them. A prop is absent when most votes read it as not visible and no vote sees it,
since refusing a board before any spend costs a person one look while letting it through costs a paid
scene on every take. It is split when the votes disagree or a lone vote misses it, and otherwise visible. The verdict is FAIL when any prop is
absent, REVIEW when none is absent and any is split, UNREAD when none is absent or split and any has no
reading, and PASS when every prop reads visible, with the gate's own exit codes throughout. The machine
line is CONTINUITY_FIRST_FRAME props=<visible>/<named> absent=<comma joined numbers or a dash>
verdict=<PASS|FAIL|REVIEW|UNREAD>.
"""
import base64
import hashlib
import json
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
LABELS = os.path.join(ROOT, "evals", "continuity-labels.json")

FPS = 4                   # frames a second the judge reads
COLS = 4                  # a grid holds COLS by COLS frames
GAP = 4                   # white pixels between the frames of a grid
# The largest grid the model reads at full size. Past either bound it is scaled down before the model
# sees it, and every frame in it shrinks with it.
GRID_PIXELS = 1_150_000
GRID_EDGE = 1568
MODEL = "claude-opus-5-5"
# Independent readings of every judged question. Authored, not derived: one reading of a cut the author
# passed failed it where two passed it, and three is the fewest that can outvote one stray reading.
VOTES = 3
JUDGE_TIMEOUT = 900
# A frame's label prints its time to two decimals, so a time read off a label sits within half a hundredth
# of that frame's own. Any further from every frame and it names a moment no frame shows.
LABEL_ROUNDING = 0.006
SYSTEM = "You check timestamped video frames for continuity breaks and answer with strict JSON only."
# The judge binary, overridable so a test can answer in its place without a key.
CLAUDE = os.environ.get("CONTINUITY_CLAUDE", "claude")

# The ruler, carried over with its numbers unchanged from the check the closer renders were first measured with.
PAIR_T, MEDIAN_T = 18, 28  # grey levels a pixel has to move, frame to frame and away from the median
PAIR_BLOB = 600            # px at 1080x1080, the largest patch that may move between two frames
MEDIAN_BLOB = 1500         # px at 1080x1080, the largest patch that may sit away from the clip's median
GROW = 0.03                # her matte grown by this share of the frame's width, so hair and a soft edge stay out
ALPHA = 0.05               # a pixel is hers on a frame where the matte reads over this
REF_AREA = 1080 * 1080
# The matte's code and its weights, where torch hub caches them under the directory TORCH_HOME names. Both
# are read from there and never fetched, so each is put there once by hand.
MATTE_REPO = "PeterL1n_RobustVideoMatting_master"
MATTE_WEIGHTS = os.path.join("checkpoints", "rvm_mobilenetv3.pth")

LINE = re.compile(r"^CONTINUITY_GATE props=(ok|fail|split|-) background=(ok|fail|split|-) first_break=([0-9.]+|-) "
                  r"verdict=(PASS|FAIL|REVIEW|UNREAD)[ \t]*$", re.M)
PROP_KINDS = ("disappears", "changes form", "pops in")
BACKGROUND_KINDS = ("appears", "vanishes", "passes through", "repeats")
EXIT = {"PASS": 0, "FAIL": 1, "REVIEW": 2, "UNREAD": 64}
USAGE = __doc__.split("\n\n")[1]


# --- the verdict --------------------------------------------------------------------------------

def verdict(props, background):
    """PASS, FAIL, REVIEW or UNREAD for the two answers, each "ok", "fail", "split", "-" when it was not
    asked, or None when it could not be read. A break on either axis fails the clip whatever the other
    says, since no reading of the other could save it. Short of that a split goes to the eye, and then
    anything unread leaves no verdict."""
    if "fail" in (props, background):
        return "FAIL"
    if "split" in (props, background):
        return "REVIEW"
    if props is None or background in (None, "-"):
        return "UNREAD"
    return "PASS"


def tally(states):
    """One asked axis's answer from its votes, each "ok", "fail" or None. "fail" only when every vote read
    it and every vote names a break, since a real break is plain to each reading. "split" when some vote
    names one and not every vote does. "ok" when no vote names one and most read it clean. Anything else
    is None, no reading."""
    if states.count("fail") == len(states):
        return "fail"
    if "fail" in states:
        return "split"
    return "ok" if states.count("ok") > len(states) // 2 else None


def pick(state, earliest):
    """The break the eye is pointed at on one judged axis, from each vote's earliest break or None: on a
    fail the median of them, so one vote naming a stray early frame cannot move it, on a split the
    earliest a dissenting vote named. None when the axis did not break."""
    named = sorted((f for f in earliest if f), key=lambda f: f["t"])
    if state == "fail":
        return named[(len(named) - 1) // 2]
    if state == "split":
        return named[0]
    return None


def count(axis):
    """How an axis was decided, as "3/3 fail" or "2/3 ok 1/3 unread" from the votes, or "measured ok"."""
    if axis["by"] == "ruler":
        return f"measured {axis['state'] or 'unread'}"
    votes = axis["votes"]
    return " ".join(f"{votes.count(s)}/{len(votes)} {s or 'unread'}" for s in ("fail", "ok", None) if votes.count(s))


def line(props, background, first_break, v):
    """The machine line pipeline/live.py reads."""
    t = "-" if first_break is None else f"{first_break:.2f}"
    return f"CONTINUITY_GATE props={props or '-'} background={background or '-'} first_break={t} verdict={v}"


# --- the clip -----------------------------------------------------------------------------------

def probe(path):
    """(width, height, seconds) of a clip, or None when it cannot be read."""
    try:
        r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                            "stream=width,height:format=duration", "-of", "json", path],
                           capture_output=True, text=True, timeout=60)
        j = json.loads(r.stdout or "{}")
        stream = (j.get("streams") or [{}])[0]
        return int(stream["width"]), int(stream["height"]), float(j["format"]["duration"])
    except (OSError, ValueError, KeyError, TypeError, subprocess.TimeoutExpired):
        return None


def tile_size(w, h):
    """The largest frame, in the clip's own shape, whose grid the model reads without scaling it down."""
    for tw in range(640, 32, -2):
        th = max(2, int(round(tw * h / w / 2)) * 2)
        gw, gh = COLS * tw + (COLS - 1) * GAP, COLS * th + (COLS - 1) * GAP
        if gw * gh <= GRID_PIXELS and max(gw, gh) <= GRID_EDGE:
            return tw, th
    return 32, 32


def sample(path, start, end, size):
    """The clip between start and end, FPS frames a second, each scaled to size, as (second, RGB array). No
    frames at all when ffmpeg exits non-zero or its frames stop short of end, since a decode that died partway
    would be judged as if the clip ended where the decode did, and run() reads no frames as no reading."""
    import numpy as np
    tw, th = size
    r = subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-ss", f"{start:.3f}", "-i", path, "-t", f"{end - start:.3f}",
                        "-vf", f"fps={FPS},scale={tw}:{th}", "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"],
                       capture_output=True, timeout=600)
    each = tw * th * 3
    frames = [np.frombuffer(r.stdout[i * each:(i + 1) * each], dtype=np.uint8).reshape(th, tw, 3)
              for i in range(len(r.stdout) // each)]
    # A whole decode can come up a frame short, where the rate rounds at the span's end or the sound runs a
    # little past the picture, and never more.
    last = start + (len(frames) - 1) / FPS
    if r.returncode or not frames or len(frames) < int((end - start) * FPS) - 1 or last < end - 2 / FPS:
        return []
    return [(round(start + i / FPS, 2), f) for i, f in enumerate(frames)]


def font(size):
    from PIL import ImageFont
    try:
        return ImageFont.load_default(size=size)
    except TypeError:          # Pillow before 10.1 has only the small bitmap face
        return ImageFont.load_default()


def grids(frames, ignore=None):
    """The frames laid out COLS by COLS in time order, each stamped with its second in its lower left
    corner, as JPEG bytes. A region to ignore is painted flat grey in every frame, so the judge is not
    asked about what it cannot see."""
    import io

    from PIL import Image, ImageDraw
    th, tw = frames[0][1].shape[:2]
    face = font(max(14, th // 12))
    out = []
    per = COLS * COLS
    for g in range(0, len(frames), per):
        chunk = frames[g:g + per]
        rows = (len(chunk) + COLS - 1) // COLS
        sheet = Image.new("RGB", (COLS * tw + (COLS - 1) * GAP, rows * th + (rows - 1) * GAP), (255, 255, 255))
        for i, (t, f) in enumerate(chunk):
            im = Image.fromarray(f)
            d = ImageDraw.Draw(im)
            if ignore:
                x0, y0, x1, y1 = ignore
                d.rectangle((int(x0 * tw), int(y0 * th), int(x1 * tw), int(y1 * th)), fill=(128, 128, 128))
            label = f"{t:.2f}s"
            box = d.textbbox((0, 0), label, font=face)
            lw, lh = box[2] - box[0], box[3] - box[1]
            d.rectangle((0, th - lh - 8, lw + 8, th), fill=(0, 0, 0))
            d.text((4, th - lh - 4 - box[1]), label, fill=(255, 230, 0), font=face)
            sheet.paste(im, ((i % COLS) * (tw + GAP), (i // COLS) * (th + GAP)))
        buf = io.BytesIO()
        sheet.save(buf, "JPEG", quality=90)
        out.append(buf.getvalue())
    return out


# --- the judge ----------------------------------------------------------------------------------

def prompt(props, story, ignore, background, first, last, n):
    """What the judge is asked, in one message: how to read the grids, what the shot is meant to show,
    the props to follow, and the one JSON shape it may answer in."""
    parts = [f"These {n} images are grids of frames from one video clip, sampled {FPS} times a second from {first:.2f} s "
             f"to {last:.2f} s. Read each grid left to right, top to bottom; the grids follow one another in time. The "
             "yellow label in each frame's lower left corner is that frame's time in seconds. White caption text on a "
             "dark bar, if there is any, was laid over the picture after it was filmed, so ignore it."]
    if story:
        parts.append(f"What the shot is meant to show, in the words it was written with: \"{story}\" Change that "
                     "those words ask for is not a break. Change they do not ask for is.")
    if ignore:
        parts.append("A flat grey box covers the same part of every frame. It hides the speaker, so ignore the box "
                     "and anything partly behind it.")
    if props:
        listed = "\n".join(f"{i}. {p}" for i, p in enumerate(props, 1))
        parts.append("PROPS. Check that each prop below is present and unchanged in every frame. A prop breaks "
                     "where it disappears while its place is in view, where it changes form (an open laptop that "
                     "becomes a flat keyboard has changed form), or where it pops into view in a place that was "
                     "already in view. A prop hidden for a moment behind something passing in front of it, or out "
                     "of frame because the camera moved, has not broken if it comes back the same, unless its own "
                     f"words say it must stay in view.\n{listed}")
    if background:
        parts.append("BACKGROUND. Does anything in the background appear from nowhere, vanish, pass into or "
                     "through a solid object, or visibly repeat the same motion, the way a loop does? Name every "
                     "frame where it happens.")
    shape = []
    if props:
        shape.append('"props": [{"n": <the prop\'s number above>, "ok": true or false, "first_break": <the time of '
                     'the first frame where it breaks, or null>, "kind": "disappears" or "changes form" or "pops in" '
                     'or null, "what": "<one short sentence>"}]')
    if background:
        shape.append('"background": {"ok": true or false, "breaks": [{"t": <the frame\'s time>, "kind": "appears" '
                     'or "vanishes" or "passes through" or "repeats", "what": "<one short sentence>"}]}')
    parts.append("Answer with this JSON object and nothing else, every time read off a frame's label, one entry for "
                 "each prop, and an empty breaks list when the background holds:\n{" + ", ".join(shape) + "}")
    return "\n\n".join(parts)


def ask(text, images):
    """One lean call to the judge, the prompt and the grids as one user message over stdin. Returns the
    answer's text and what it cost, or None when the call gave no answer. Nothing but the message is
    loaded, no settings, tools or servers, since a judge that reads its host's instructions while it
    grades is not detached. This is the one function a test replaces."""
    content = [{"type": "text", "text": text}] + [
        {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": base64.b64encode(b).decode()}}
        for b in images]
    message = json.dumps({"type": "user", "message": {"role": "user", "content": content}}) + "\n"
    # Images reach the CLI only as stream-json, and it answers stream-json only in kind, with --verbose.
    argv = [CLAUDE, "-p", "--input-format", "stream-json", "--output-format", "stream-json", "--verbose",
            "--model", MODEL, "--setting-sources", "", "--tools", "", "--strict-mcp-config",
            "--mcp-config", '{"mcpServers":{}}', "--system-prompt", SYSTEM,
            "--no-session-persistence", "--disable-slash-commands"]
    try:
        r = subprocess.run(argv, input=message, capture_output=True, text=True, timeout=JUDGE_TIMEOUT)
    except (OSError, subprocess.TimeoutExpired):
        return None
    result = None
    for ln in r.stdout.splitlines():
        try:
            event = json.loads(ln)
        except ValueError:
            continue
        if isinstance(event, dict) and event.get("type") == "result":
            result = event
    if not result or result.get("is_error") or not isinstance(result.get("result"), str):
        return None
    return {"text": result["result"], "cost_usd": result.get("total_cost_usd"), "model": MODEL}


def poll(text, images):
    """VOTES independent readings of the same question and the same frames, asked at once, since each
    call waits on the network and not on the others. A call that gave no answer is None in its place."""
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=VOTES) as pool:
        return list(pool.map(lambda _vote: ask(text, images), range(VOTES)))


def answer_of(text):
    """The judge's JSON object, or None. A code fence around it is tolerated and nothing else is."""
    t = (text or "").strip()
    fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", t, re.S)
    try:
        a = json.loads(fenced.group(1) if fenced else t)
    except ValueError:
        return None
    return a if isinstance(a, dict) else None


def _time(x, times):
    """The time of the sampled frame the judge named, read off its label, or None when the number is no
    frame's: a time between two frames or outside the span is a moment the judge was never shown."""
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        return None
    t = min(times, key=lambda s: abs(s - x))
    return round(t, 2) if abs(t - x) <= LABEL_ROUNDING else None


def read_answer(answer, props, background, times):
    """The judge's JSON as (props, background, findings): each answer "ok", "fail", "-" when it was not
    asked, or None when it is missing, malformed or contradicts itself, and every break it named. A break
    has to name a frame, so a prop that fails with no time is no reading, and neither is a background that
    fails with no break named or holds with one. The props answer has to account for every prop named,
    each once, and one entry it cannot stand behind leaves the whole axis unread, whatever the others say:
    an answer that is not the shape asked for is not trusted in part, since a break it names would pay
    for a re-roll."""
    if not isinstance(answer, dict):
        return (None if props else "-"), (None if background else "-"), []
    findings = []
    p_state = "-"
    if props:
        entries = answer.get("props") if isinstance(answer.get("props"), list) else []
        got = {}
        for e in entries:
            n = e.get("n") if isinstance(e, dict) else None
            if type(n) is not int or not 1 <= n <= len(props) or n in got:
                got = None   # an entry for no prop named, or a prop answered twice
                break
            got[n] = e
        if got is None or len(got) != len(props):
            p_state = None   # an entry missing, duplicated, or naming no prop leaves the whole axis unread
        else:
            states, found = [], []
            for i, name in enumerate(props, 1):
                e = got[i]
                if not isinstance(e.get("ok"), bool):
                    states.append(None)
                elif e["ok"]:
                    states.append("ok" if e.get("first_break") is None else None)
                else:
                    t = _time(e.get("first_break"), times)
                    if t is None or e.get("kind") not in PROP_KINDS:
                        states.append(None)
                    else:
                        states.append("fail")
                        found.append({"axis": "props", "prop": name, "t": t, "kind": e["kind"], "what": str(e.get("what", ""))})
            p_state = None if None in states else "fail" if "fail" in states else "ok"
            if p_state is not None:
                findings += found
    b_state = "-"
    if background:
        b = answer.get("background")
        breaks = b.get("breaks") if isinstance(b, dict) else None
        if not isinstance(b, dict) or not isinstance(b.get("ok"), bool) or not isinstance(breaks, list):
            b_state = None
        elif b["ok"]:
            b_state = "ok" if not breaks else None
        else:
            named = [(_time(x.get("t"), times), x) for x in breaks if isinstance(x, dict)]
            if not named or len(named) != len(breaks) or any(t is None or x.get("kind") not in BACKGROUND_KINDS for t, x in named):
                b_state = None
            else:
                b_state = "fail"
                findings += [{"axis": "background", "t": t, "kind": x["kind"], "what": str(x.get("what", ""))} for t, x in named]
    return p_state, b_state, sorted(findings, key=lambda f: f["t"])


# --- the ruler ----------------------------------------------------------------------------------

def matte_repo(hub=None):
    """The directory holding the matte's code in the local torch hub cache, `hub` or the one TORCH_HOME
    names, once its weights are found in the same cache. ModuleNotFoundError naming what is missing when
    either is not there, since nothing here is ever fetched, and the hubconf would fetch weights it cannot
    find and unpickle them."""
    if hub is None:
        import torch
        hub = torch.hub.get_dir()
    repo = os.path.join(hub, MATTE_REPO)
    missing = [name for name, there in ((MATTE_REPO, os.path.isdir(repo)),
                                        (MATTE_WEIGHTS, os.path.isfile(os.path.join(hub, MATTE_WEIGHTS)))) if not there]
    if missing:
        raise ModuleNotFoundError(f"the matte model is not in the local torch hub cache that TORCH_HOME names, {hub}, "
                                  f"which lacks {' and '.join(missing)}, and has to be put there once by hand, since "
                                  "the gate never fetches it", name=MATTE_REPO)
    return repo


def rvm():
    """RobustVideoMatting's mobilenetv3 as one frame at a time, the recurrent state carried between
    frames so her edges hold. It is the matte the avatar pipeline's body guard uses outside this repository,
    loaded from the torch hub cache TORCH_HOME names, and it needs torch, so the import lives here. It loads
    only from that local cache, never from the network, since a gate that runs code it just downloaded is
    not the gate that was reviewed."""
    import cv2
    import torch
    dev = "mps" if torch.backends.mps.is_available() else "cpu"
    model = torch.hub.load(matte_repo(), "mobilenetv3", source="local").to(dev).eval()
    rec = [None] * 4

    def step(frame):
        nonlocal rec
        h, w = frame.shape[:2]
        src = torch.from_numpy(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB).copy()).permute(2, 0, 1).float().div(255)
        with torch.no_grad():
            _fgr, pha, *rec = model(src.unsqueeze(0).to(dev), *rec, downsample_ratio=min(512.0 / max(w, h), 1.0))
        return pha[0, 0].clamp(0, 1).cpu().numpy()
    return step


def largest(mask):
    """The area in pixels of the largest connected patch in a mask."""
    import cv2
    n, _labels, stats, _centres = cv2.connectedComponentsWithStats(mask, connectivity=8)
    return int(stats[1:, cv2.CC_STAT_AREA].max()) if n > 1 else 0


def measure(path, matte=None):
    """The ruler on a presenter take: her matte on every frame, her region the union of it grown by GROW,
    and in the rest the largest patch that moves frame to frame or sits away from the clip's median. The
    frames at FPS a second come back too, her greyed out, for the eye. `matte` stands in for the model, a
    function from a BGR frame to its alpha, so the arithmetic is testable without torch. None when no
    frame could be read.

    Her region is one union across the take, not a matte per frame, so anything that moves only where she
    stood at some moment is not read. That is the mask PAIR_BLOB and MEDIAN_BLOB were measured with, and a
    per-frame mask would count her own edges as background and move every number those limits were set on.
    A seated presenter sways little, and what crosses behind her shows on either side of her anyway."""
    import cv2
    import numpy as np
    cap = cv2.VideoCapture(path)
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    every = max(1, int(round(fps / FPS)))
    her, greys, kept = None, [], []
    matte = matte or rvm()
    while True:
        ok, f = cap.read()
        if not ok:
            break
        hers = (matte(f) > ALPHA).astype(np.uint8)
        her = hers if her is None else her | hers
        greys.append(cv2.GaussianBlur(cv2.cvtColor(f, cv2.COLOR_BGR2GRAY), (5, 5), 0))
        if (len(greys) - 1) % every == 0:
            kept.append((round((len(greys) - 1) / fps, 2), f))
    cap.release()
    if not greys:
        return None
    h, w = greys[0].shape
    g = max(3, int(round(GROW * w)))
    bg = cv2.dilate(her, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * g + 1, 2 * g + 1))) == 0
    kern = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    pair, vs_median = [], []
    for i in range(1, len(greys)):
        diff = np.abs(greys[i].astype(np.int16) - greys[i - 1].astype(np.int16))
        moved = cv2.morphologyEx(((diff > PAIR_T) & bg).astype(np.uint8), cv2.MORPH_OPEN, kern)
        pair.append({"t": round(i / fps, 2), "blob": largest(moved), "mean": round(float(diff[bg].mean()), 3) if bg.any() else 0.0})
    median = np.median(np.stack(greys), axis=0)
    for i, grey in enumerate(greys):
        away = cv2.morphologyEx(((np.abs(grey.astype(np.int16) - median) > MEDIAN_T) & bg).astype(np.uint8), cv2.MORPH_OPEN, kern)
        vs_median.append({"t": round(i / fps, 2), "blob": largest(away)})
    strip, size = [], tile_size(w, h)
    for t, f in kept:
        f = f.copy()
        f[~bg] = (f[~bg] * 0.15 + 110 * 0.85).astype(np.uint8)
        strip.append((t, cv2.cvtColor(cv2.resize(f, size, interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2RGB)))
    return {"frames": len(greys), "fps": round(fps, 2), "size": [w, h], "background_share": round(float(bg.mean()), 3),
            "pair": pair, "vs_median": vs_median, "strip": strip}


def rule(m):
    """The ruler's answer for a measured take, "ok" or "fail", or None when nothing of the background was
    left to measure, with the first second a patch reached its limit and a finding for each limit
    crossed. A take she fills from edge to edge reads 0 px everywhere, which is no reading, not a still
    background."""
    if not m or not m["background_share"]:
        return None, None, []
    scale = m["size"][0] * m["size"][1] / REF_AREA
    findings = []
    for name, rows, limit, what in (("pair", m["pair"], PAIR_BLOB, "between two frames"),
                                    ("vs_median", m["vs_median"], MEDIAN_BLOB, "away from the clip's median")):
        over = [r for r in rows if r["blob"] >= limit * scale]
        if over:
            worst = max(over, key=lambda r: r["blob"])
            findings.append({"axis": "background", "t": over[0]["t"], "kind": "moves", "measure": name,
                             "what": f"a patch behind the speaker moves {what}, first at {over[0]['t']:.2f} s, largest "
                                     f"{worst['blob']} px at {worst['t']:.2f} s against a limit of {round(limit * scale)} px, "
                                     f"over it in {len(over)} frames"})
    findings.sort(key=lambda f: f["t"])
    return ("fail" if findings else "ok"), (findings[0]["t"] if findings else None), findings


# --- one clip -----------------------------------------------------------------------------------

def fresh(path):
    """path, or the first of path-v2, path-v3 and on that is free, so no reading is written over another."""
    stem, ext = os.path.splitext(path)
    n = 1
    while os.path.exists(path):
        n += 1
        path = f"{stem}-v{n}{ext}"
    return path


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def options(argv):
    """The command line as a dict, or ValueError naming what is wrong with it."""
    o = {"clip": None, "props": [], "story": None, "ignore": None, "span": None, "presenter": False, "out": None}
    args = list(argv)
    while args:
        a = args.pop(0)
        if a == "--presenter":
            o["presenter"] = True
        elif a in ("--prop", "--story", "--ignore", "--span", "--out"):
            if not args:
                raise ValueError(f"{a} needs a value")
            v = args.pop(0)
            if a == "--prop":
                if not v.strip():
                    raise ValueError("a prop is a line of text")
                o["props"].append(v.strip())
            elif a == "--ignore":
                box = [float(x) for x in v.split(",")]
                if len(box) != 4 or not (0 <= box[0] < box[2] <= 1 and 0 <= box[1] < box[3] <= 1):
                    raise ValueError("--ignore is x0,y0,x1,y1, fractions of the frame with x0 < x1 and y0 < y1")
                o["ignore"] = box
            elif a == "--span":
                span = [float(x) for x in v.split(":")]
                if len(span) != 2 or not 0 <= span[0] < span[1]:
                    raise ValueError("--span is <from>:<to> in seconds, from before to")
                o["span"] = span
            else:
                o[a[2:]] = v
        elif a.startswith("-") or o["clip"]:
            raise ValueError(f"unexpected {a}")
        else:
            o["clip"] = a
    if not o["clip"]:
        raise ValueError("no clip named")
    if o["presenter"] and o["span"]:
        # The ruler measures a take whole, against the take's own median, so part of one is not a reading.
        raise ValueError("--span reads part of a story shot, and a presenter take is measured whole")
    return o


def unread(reason):
    print(f"continuity: no reading, {reason}")
    print(line(None, None, None, "UNREAD"))
    return 64


def run(o):
    """Read one clip, write its findings and print its machine line. Returns the exit code."""
    clip = o["clip"]
    shape = probe(clip) if os.path.isfile(clip) else None
    if not shape:
        return unread("the clip cannot be read")
    w, h, seconds = shape
    start, end = o["span"] or (0.0, seconds)
    end = min(end, seconds)
    if start >= end:
        return unread(f"the span starts at or after the clip's end, {seconds:.2f} s")
    out = fresh(o["out"] or os.path.splitext(clip)[0] + ".continuity.json")
    if not os.path.isdir(os.path.dirname(os.path.abspath(out))):
        # Checked before anything is measured or paid for, since a reading with nowhere to go is lost.
        return unread(f"there is no directory to write the findings in, {os.path.dirname(out)}")
    stem = os.path.splitext(out)[0]
    record = {"clip": clip, "clip_sha256": sha256(clip), "span": [round(start, 2), round(end, 2)], "props": o["props"],
              "story": o["story"], "ignore": o["ignore"], "presenter": o["presenter"]}
    props, background, findings, axes = ("-" if not o["props"] else None), None, [], {}

    if o["presenter"]:
        m = measure(clip)
        background, _first, ruled = rule(m)
        findings += ruled
        axes["background"] = {"by": "ruler", "state": background, "first": ruled[0] if ruled else None}
        record["ruler"] = {k: v for k, v in (m or {}).items() if k != "strip"}
        record["ruler"].update(pair_limit=PAIR_BLOB, median_limit=MEDIAN_BLOB)
        if m and m["strip"]:
            record["ruler"]["strip"] = [os.path.basename(p) for p in save(grids(m["strip"]), f"{stem}.strip")]

    if o["props"] or not o["presenter"]:
        frames = sample(clip, start, end, tile_size(w, h))
        if frames:
            times = [t for t, _ in frames]
            images = grids(frames, o["ignore"])
            asked = prompt(o["props"], o["story"], o["ignore"], not o["presenter"], times[0], times[-1], len(images))
            replies = poll(asked, images)
            answers = [answer_of(r["text"]) if r else None for r in replies]
            votes = [read_answer(a, o["props"], not o["presenter"], times) for a in answers]
            for n, (_p, _b, found) in enumerate(votes, 1):
                findings += [dict(f, vote=n) for f in found]
            for i, axis in enumerate(("props", "background")):
                if (axis == "props" and not o["props"]) or (axis == "background" and o["presenter"]):
                    continue
                states = [vote[i] for vote in votes]
                earliest = [min((dict(f, vote=n) for f in vote[2] if f["axis"] == axis), key=lambda f: f["t"], default=None)
                            for n, vote in enumerate(votes, 1)]
                state = tally(states)
                axes[axis] = {"by": "judge", "state": state, "votes": states, "first": pick(state, earliest)}
            if o["props"]:
                props = axes["props"]["state"]
            if not o["presenter"]:
                background = axes["background"]["state"]
            record["judge"] = {"model": MODEL, "votes": VOTES, "prompt": asked,
                               "cost_usd": round(sum((r or {}).get("cost_usd") or 0 for r in replies), 6),
                               "grids": [os.path.basename(p) for p in save(images, f"{stem}.grid")],
                               "answers": [a if a is not None else (r or {}).get("text") for a, r in zip(answers, replies, strict=True)]}
        elif not o["presenter"]:
            background = None

    findings.sort(key=lambda f: (f["t"], f.get("vote") or 0))
    v = verdict(props, background)
    # The break a person is sent to: a failed axis's median on a FAIL, the dissent on a REVIEW.
    wanted = {"FAIL": "fail", "REVIEW": "split"}.get(v)
    pointed = [a["first"] for a in axes.values() if a["state"] == wanted and a.get("first")]
    first = min(pointed, key=lambda f: f["t"]) if pointed else None
    said = line(props, background, first["t"] if first else None, v)
    record.update(findings=findings, axes=axes, first=first, props_state=props, background_state=background,
                  first_break=first["t"] if first else None, verdict=v, line=said)
    with open(out, "w") as fh:
        json.dump(record, fh, indent=1)
    for name, axis in axes.items():
        print(f"continuity: {name} {count(axis)}")
    for f in findings:
        what = f" \"{f['prop']}\"" if f["axis"] == "props" else ""
        vote = f", vote {f['vote']}" if f.get("vote") else ""
        print(f"continuity: {f['axis']}{what} {f['kind']} at {f['t']:.2f} s{vote}: {f['what']}")
    print(f"continuity: findings in {out}")
    print(said)
    return EXIT[v]


def save(images, stem):
    """Write each image beside the findings, numbered, and return their paths."""
    paths = []
    for i, data in enumerate(images, 1):
        p = fresh(f"{stem}-{i}.jpg")
        with open(p, "wb") as fh:
            fh.write(data)
        paths.append(p)
    return paths


# --- the first frame ------------------------------------------------------------------------------

def first_frame_prompt(props):
    """What the judge is asked for a first-frame check: the props to find in the one still and the one
    JSON shape it may answer in."""
    listed = "\n".join(f"{i}. {p}" for i, p in enumerate(props, 1))
    return ("This image is the still a chain's first shot starts from, before anything is filmed. For "
            f"each prop below, say whether it is visible in this image.\n{listed}\n\nAnswer with this "
            "JSON object and nothing else, one entry for each prop, every number above used exactly "
            'once:\n{"props": [{"n": <the prop\'s number above>, "visible": true or false, "what": '
            '"<one short sentence>"}]}')


def first_frame_image(path):
    """The still as one JPEG block, scaled down only when it is past the grid's own limits, so the judge
    reads it no larger than any frame it is otherwise shown. Raises the way Image.open does when the
    file is not a readable image, which the caller reads as no reading, never a crash."""
    import io

    from PIL import Image
    im = Image.open(path).convert("RGB")
    w, h = im.size
    tw, th = w, h
    for cand in range(w, 32, -2):
        cth = max(2, round(cand * h / w))
        if cand * cth <= GRID_PIXELS and max(cand, cth) <= GRID_EDGE:
            tw, th = cand, cth
            break
    else:
        tw, th = 32, max(2, round(32 * h / w))
    if (tw, th) != (w, h):
        im = im.resize((tw, th), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=90)
    return buf.getvalue()


def read_first_frame(answer, props):
    """One vote's reading of a first-frame answer: "ok" (visible), "fail" (absent) or None (no reading it
    can be trusted for), one for each prop in order, and what it said about each it read as absent. The
    answer has to name every prop exactly once, or none of it is trusted, since a numbering that already
    lost track of which prop is which cannot be trusted for any one of them."""
    if not isinstance(answer, dict):
        return [None] * len(props), []
    entries = answer.get("props") if isinstance(answer.get("props"), list) else []
    got = {}
    for e in entries:
        n = e.get("n") if isinstance(e, dict) else None
        if type(n) is not int or not 1 <= n <= len(props) or n in got:
            got = None
            break
        got[n] = e
    if got is None or len(got) != len(props):
        return [None] * len(props), []
    states, found = [], []
    for i, name in enumerate(props, 1):
        visible = got[i].get("visible")
        if not isinstance(visible, bool):
            states.append(None)
        else:
            states.append("ok" if visible else "fail")
            if not visible:
                found.append({"n": i, "prop": name, "what": str(got[i].get("what", ""))})
    return states, found


def first_frame_line(visible, named, absent, v):
    """The machine line pipeline/live.py reads for a first-frame check."""
    a = "-" if not absent else ",".join(str(n) for n in absent)
    return f"CONTINUITY_FIRST_FRAME props={visible}/{named} absent={a} verdict={v}"


def first_frame_options(argv):
    """The --first-frame command line as a dict, or ValueError naming what is wrong with it."""
    o = {"image": None, "props": [], "out": None}
    args = list(argv)
    while args:
        a = args.pop(0)
        if a in ("--prop", "--out"):
            if not args:
                raise ValueError(f"{a} needs a value")
            v = args.pop(0)
            if a == "--prop":
                if not v.strip():
                    raise ValueError("a prop is a line of text")
                o["props"].append(v.strip())
            else:
                o["out"] = v
        elif a.startswith("-") or o["image"]:
            raise ValueError(f"unexpected {a}")
        else:
            o["image"] = a
    if not o["image"]:
        raise ValueError("no image named")
    if not o["props"]:
        raise ValueError("no props named")
    return o


def unread_first_frame(reason, n):
    print(f"continuity: no reading, {reason}")
    print(first_frame_line(0, n, [], "UNREAD"))
    return 64


def first_frame_tally(states):
    """One prop's answer across the first-frame votes, looser than a scene's: "fail" (absent) when most votes
    read it as missing and none sees it, "split" when any vote misses it otherwise, "ok" when most see it,
    else None. One unreadable vote must not wave a missing prop through, since that costs a paid scene."""
    fails, oks = states.count("fail"), states.count("ok")
    if fails > len(states) // 2 and not oks:
        return "fail"
    if fails:
        return "split"
    return "ok" if oks > len(states) // 2 else None


def run_first_frame(o):
    """Read one still image and ask whether every named prop is visible in it, before any render request
    is sent for it. Returns the exit code."""
    image, props = o["image"], o["props"]
    if not os.path.isfile(image):
        return unread_first_frame("the image cannot be read", len(props))
    out = fresh(o["out"] or os.path.splitext(image)[0] + ".first_frame.json")
    if not os.path.isdir(os.path.dirname(os.path.abspath(out))):
        # Checked before anything is measured or paid for, since a reading with nowhere to go is lost.
        return unread_first_frame(f"there is no directory to write the findings in, {os.path.dirname(out)}", len(props))
    try:
        frame = first_frame_image(image)
    except Exception as e:  # noqa: BLE001, an image that cannot be opened is no reading, never a crash
        return unread_first_frame(f"the image cannot be opened, {type(e).__name__}: {str(e)[:200]}", len(props))
    asked = first_frame_prompt(props)
    replies = poll(asked, [frame])
    answers = [answer_of(r["text"]) if r else None for r in replies]
    per_vote = [read_first_frame(a, props) for a in answers]
    findings, tallied = [], []
    for i in range(len(props)):
        column = [states[i] for states, _ in per_vote]
        tallied.append(first_frame_tally(column))
        for n_vote, (_states, found) in enumerate(per_vote, 1):
            findings += [dict(f, vote=n_vote) for f in found if f["n"] - 1 == i]
    absent = [i + 1 for i, s in enumerate(tallied) if s == "fail"]
    split = [i + 1 for i, s in enumerate(tallied) if s == "split"]
    unread_ns = [i + 1 for i, s in enumerate(tallied) if s is None]
    visible_n = sum(1 for s in tallied if s == "ok")
    v = "FAIL" if absent else "REVIEW" if split else "UNREAD" if unread_ns else "PASS"
    said = first_frame_line(visible_n, len(props), absent, v)
    record = {"image": image, "image_sha256": sha256(image), "props": props, "findings": findings,
              "tally": tallied, "absent": absent, "split": split, "unread": unread_ns, "verdict": v, "line": said,
              "judge": {"model": MODEL, "votes": VOTES, "prompt": asked,
                       "cost_usd": round(sum((r or {}).get("cost_usd") or 0 for r in replies), 6),
                       "frame": [os.path.basename(p) for p in save([frame], os.path.splitext(out)[0] + ".frame")],
                       "answers": [a if a is not None else (r or {}).get("text") for a, r in zip(answers, replies, strict=True)]}}
    with open(out, "w") as fh:
        json.dump(record, fh, indent=1)
    for i, name in enumerate(props, 1):
        axis = {"by": "judge", "state": tallied[i - 1], "votes": [states[i - 1] for states, _ in per_vote]}
        print(f'continuity: prop {i} "{name}" {count(axis)}')
    for f in findings:
        print(f"continuity: prop {f['n']} \"{f['prop']}\" not visible, vote {f['vote']}: {f['what']}")
    print(f"continuity: findings in {out}")
    print(said)
    return EXIT[v]


# --- the labels ---------------------------------------------------------------------------------

def story_of(case):
    """The words a labelled master was shot from, each shot's line from its board with the character
    named the way the render names her, or the case's own words, or None."""
    if case.get("story"):
        return case["story"]
    if not case.get("board"):
        return None
    with open(os.path.join(ROOT, case["board"])) as fh:
        spot = json.load(fh)["spots"][case["spot"]]
    who = f"the {spot.get('character_noun', 'person')}"
    order = spot.get("chain") or sorted(spot["scenes"])
    return " ".join(f"Shot {k}: {spot['scenes'][k].replace('{character}', who)}" for k in order)


def agrees(case, v, axes):
    """How the gate's reading of a labelled case stands against its label: "agree", "deferred" or "miss". A
    PASS label agrees with PASS, and a REVIEW on it is deferred to the eye, a look and never a re-shoot. A
    FAIL label agrees only with a FAIL whose break on the labelled axis falls inside the labelled window,
    since a FAIL for the wrong reason is not the eye's FAIL, and a REVIEW on it is a miss, because a real
    break has to be caught outright. No reading is a miss."""
    if case["label"] == "PASS":
        return {"PASS": "agree", "REVIEW": "deferred"}.get(v, "miss")
    axis = (axes or {}).get(case["axis"]) or {}
    t = (axis.get("first") or {}).get("t")
    lo, hi = case.get("window") or (0, float("inf"))
    return "agree" if v == "FAIL" and axis.get("state") == "fail" and t is not None and lo <= t <= hi else "miss"


def validate(path, out_root=None):
    """Run the gate on every labelled case, as the pipeline runs it, and compare. Exits 0 only when no case
    is a miss, a case that could not be read included."""
    with open(path) as fh:
        cases = json.load(fh)["cases"]
    out_dir = os.path.join(out_root or os.path.join(ROOT, ".reports", "continuity-validate"), time.strftime("%Y%m%d-%H%M%S"))
    os.makedirs(out_dir, exist_ok=True)
    seen, spent, calls = {"agree": 0, "deferred": 0, "miss": 0}, 0.0, 0
    print(f"{'case':24s} {'label':6s} {'gate':7s} {'first':>6s}  {'outcome':9s} tally", flush=True)
    for case in cases:
        clip = os.path.expanduser(os.path.expandvars(case["clip"]))
        clip = clip if os.path.isabs(clip) else os.path.join(ROOT, clip)
        if not os.path.isfile(clip) or (case.get("sha256") and sha256(clip) != case["sha256"]):
            why = "is not here" if not os.path.isfile(clip) else "is not the file that was labelled"
            if not os.path.isfile(clip) and "$" in clip:
                why += ", and it names an environment variable that is not set"
            seen["miss"] += 1
            print(f"{case['id']:24s} {case['label']:6s} {'-':7s} {'-':>6s}  {'miss':9s} {case['clip']} {why}", flush=True)
            continue
        args = [clip, "--out", os.path.join(out_dir, f"{case['id']}.json")]
        for p in case.get("props") or []:
            args += ["--prop", p]
        story = story_of(case)
        if story:
            args += ["--story", story]
        if case.get("span"):
            args += ["--span", f"{case['span'][0]}:{case['span'][1]}"]
        if case.get("presenter"):
            args.append("--presenter")
        py = os.environ.get("MATTEPY", sys.executable) if case.get("presenter") else sys.executable
        r = subprocess.run([py, os.path.abspath(__file__), *args], capture_output=True, text=True, timeout=3600)
        said = LINE.findall(r.stdout)
        v = said[-1][3] if said and EXIT[said[-1][3]] == r.returncode else "UNREAD"
        record = {}
        found = re.findall(r"^continuity: findings in (.+)$", r.stdout, re.M)
        if found and os.path.isfile(found[-1]):
            with open(found[-1]) as fh:
                record = json.load(fh)
        judge = record.get("judge") or {}
        spent += judge.get("cost_usd") or 0.0
        calls += judge.get("votes") or 0
        axes = record.get("axes") or {}
        outcome = agrees(case, v, axes)
        seen[outcome] += 1
        first = record.get("first_break")
        votes = ", ".join(f"{name} {count(axis)}" for name, axis in axes.items())
        print(f"{case['id']:24s} {case['label']:6s} {v:7s} {'-' if first is None else f'{first:.2f}':>6s}  {outcome:9s} {votes}",
              flush=True)
        pointed = record.get("first")
        if pointed:
            what = f" \"{pointed['prop']}\"" if pointed["axis"] == "props" else ""
            vote = f", vote {pointed['vote']}" if pointed.get("vote") else ""
            print(f"    {pointed['axis']}{what} {pointed['kind']} at {pointed['t']:.2f} s{vote}: {pointed['what']}", flush=True)
        if v == "UNREAD":
            print(f"    {(r.stdout + r.stderr).strip()[-300:]}", flush=True)
        elif case["label"] == "FAIL" and outcome == "miss" and v == "FAIL":
            print(f"    no break on {case['axis']} inside {case.get('window')}", flush=True)
    print(f"\nagainst the author's labels: {seen['agree']} agree, {seen['deferred']} deferred to the eye, {seen['miss']} "
          f"missed, of {len(cases)} labelled. Judge spend ${spent:.2f} over {calls} calls.", flush=True)
    print(f"{len(cases)} cases is a thin set. Findings are in {os.path.relpath(out_dir, ROOT)}.", flush=True)
    if seen["miss"]:
        print("NOT every case agrees. The labels are the ground truth, so a miss means THIS FILE is wrong.", flush=True)
    return 0 if not seen["miss"] else 1


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["--validate"]:
        return validate(argv[1] if len(argv) > 1 else LABELS)
    if argv[:1] == ["--first-frame"]:
        try:
            o = first_frame_options(argv[1:])
        except ValueError as e:
            print(f"continuity: {e}\n{USAGE}")
            return 64
        try:
            return run_first_frame(o)
        except Exception as e:  # noqa: BLE001, an uncaught crash exits 1, which every caller reads as a break
            return unread_first_frame(f"the gate crashed, {type(e).__name__}: {str(e)[:200]}", len(o["props"]))
    try:
        o = options(argv)
    except ValueError as e:
        print(f"continuity: {e}\n{USAGE}")
        return 64
    try:
        return run(o)
    except ImportError as e:
        # A presenter take read by the repo's own interpreter, which carries no torch, or under one whose hub
        # cache does not hold the matte, which is never fetched. No reading either way, and each says why.
        if e.name == MATTE_REPO:
            return unread(str(e))
        return unread(f"{e.name} is not installed here, so run a presenter take with MATTEPY's interpreter")
    except Exception as e:  # noqa: BLE001, an uncaught crash exits 1, which every caller reads as a break
        return unread(f"the gate crashed, {type(e).__name__}: {str(e)[:200]}")


if __name__ == "__main__":
    sys.exit(main())
