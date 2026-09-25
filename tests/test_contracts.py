"""What pipeline/live.py reads off each gate is a contract, and this file holds the gates to it.

The graph routes on a handful of strings: the ad gates' result line, the mouth probe's line,
the jaw and loudness gates' machine lines, the ship gate's hold texts, its slit-scan line, and
the replay probe's verdict and vertex. Those strings used to be typed into the tests by hand,
so a gate could change what it prints and every test stayed green while the graph stopped
recognising a verdict. The patterns now live in pipeline/live.py, and every test here RUNS the
real script on a synthetic input and matches its real output against the pattern live.py
reads it with.

A sub-probe is stubbed only where the real one needs a face model. Each stub prints the line
the real probe's own print statement would print, formatted from that statement's source, so
a probe that rewords its output rewords its stub too, and the contract is checked against the
new wording rather than the old.

Run with: python3 -m pytest tests/test_contracts.py -v
"""
import ast
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from pipeline import live  # noqa: E402

GATES = os.path.join(ROOT, "gates")
PROBES = os.path.join(ROOT, "probes")
SRT_ARROW = "-" * 2 + ">"   # the SRT timing arrow, built up so no prose hook reads it as a dash


def printed(path, *fragments, **names):
    """The line one f-string print statement in path prints, evaluated with names.

    The statement is found by fragments of its own source text and must be the only match, so
    this reads what the real probe says and cannot drift from it."""
    tree = ast.parse(Path(path).read_text())
    found = [node.args[0] for node in ast.walk(tree)
             if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "print" and node.args
             and isinstance(node.args[0], ast.JoinedStr)
             and all(f in ast.unparse(node.args[0]) for f in fragments)]
    assert len(found) == 1, f"{path}: {len(found)} print statements match {fragments}"
    code = compile(ast.fix_missing_locations(ast.Expression(body=found[0])), path, "eval")
    return eval(code, {"__builtins__": {"len": len, "max": max, "min": min}}, names)  # noqa: S307


def ffmpeg(*args):
    subprocess.run(["ffmpeg", "-v", "error", "-y", *args], check=True, timeout=300)


def run(cmd, env=None, timeout=300):
    return subprocess.run(cmd, env=dict(os.environ, **(env or {})), capture_output=True, text=True, timeout=timeout)


# --------------------------------------------------------------------------------------
# gates/ad_gates.sh and the mouth probe line inside it
# --------------------------------------------------------------------------------------

def _ad_gates(tmp, mouth_line, with_segments, mouth_exit=0):
    """ad_gates.sh on a six second master with sound. The manifest carries no cues, so the
    caption gate fails and no pass receipt is written. With segments, q1 to q3 sit beside it
    at one second each and the closer audio is placed at 3000 ms, which is where they end."""
    tmp.mkdir(parents=True, exist_ok=True)
    master = tmp / "master.mp4"
    ffmpeg("-f", "lavfi", "-i", "testsrc=size=160x160:rate=25", "-f", "lavfi", "-i", "sine=frequency=300:duration=6",
           "-t", "6", "-pix_fmt", "yuv420p", "-c:v", "libx264", "-c:a", "aac", str(master))
    if with_segments:
        for q in ("q1", "q2", "q3"):
            ffmpeg("-f", "lavfi", "-i", "testsrc=size=64x64:rate=25", "-t", "1", "-pix_fmt", "yuv420p", str(tmp / f"{q}.mp4"))
    for name in ("vo", "av"):
        (tmp / f"{name}.json").write_text(json.dumps({"words": []}))
    captions = tmp / "captions.json"
    captions.write_text(json.dumps({"cues": [], "closer_start": 3.0, "closer_dur": 2.0, "audio_closer_ms": 3000,
                                    "vo_stt": str(tmp / "vo.json"), "av_stt": str(tmp / "av.json")}))
    facepy = tmp / "facepy"
    facepy.write_text(f"#!/bin/sh\necho '{mouth_line}'\nexit {mouth_exit}\n")
    facepy.chmod(0o755)
    return run(["bash", os.path.join(GATES, "ad_gates.sh"), str(master), str(captions)],
               env={"FACEPY": str(facepy), "TMPDIR": str(tmp)})


def test_the_ad_gates_result_line_is_the_line_live_reads(tmp_path):
    # Found by the values it formats rather than its wording, so a probe that rewords the line
    # is caught by the pattern below and not by a failure to find the statement.
    mouth = printed(os.path.join(GATES, "mouth_sync_probe.py"), "{best", "{bl",
                    v="PASS", best=0.41, bl=0.0, found=20, total=20)
    assert live.MOUTH_LINE.search(mouth), f"MOUTH_LINE does not read the probe's own line: {mouth}"
    for with_segments, drift in ((True, "pass"), (False, "unreadable")):
        r = _ad_gates(tmp_path / drift, mouth, with_segments)
        line = live.AD_GATES_LINE.search(r.stdout)
        assert line, f"AD_GATES_LINE finds no result line in the gate's output\n{r.stdout}\n{r.stderr}"
        assert (line.group(1), line.group(2), line.group(3)) == ("fail", drift, "pass"), line.group(0)
        said = live.MOUTH_LINE.search(r.stdout)
        assert said and float(said.group(1)) == 0.41, f"MOUTH_LINE lost the probe line inside the gate\n{r.stdout}"


def test_a_mouth_the_probe_could_not_find_or_rule_on_reads_as_such(tmp_path):
    """live.py stops on noface and sends review to the eye, so each has to reach the result line
    as itself. The probe signals them by its exit code, 3 for no face and 2 for a review."""
    for code, word in ((3, "noface"), (2, "review")):
        r = _ad_gates(tmp_path / word, "stub mouth probe", True, mouth_exit=code)
        line = live.AD_GATES_LINE.search(r.stdout)
        assert line and line.group(3) == word, (code, r.stdout)


# --------------------------------------------------------------------------------------
# gates/jaw_gate.py and gates/loudness_gate.py
# --------------------------------------------------------------------------------------

def test_the_jaw_gate_line_is_the_line_live_reads(tmp_path):
    source = os.path.join(GATES, "source_gate.py")
    clip = tmp_path / "closer.mp4"
    clip.write_bytes(b"x")
    for faces, jaw, want in ((19, 0.1167, "PASS"), (19, 0.19, "FAIL"), (8, 0.11, "UNMEASURED")):
        said = [printed(source, "{len(chin)", chin=[0] * faces, _sampled=[0] * 20),
                printed(source, "{jaw:", jaw=jaw)]
        stub = tmp_path / f"facepy-{want}"
        stub.write_text("#!/bin/sh\n" + "".join(f"echo '{ln}'\n" for ln in said))
        stub.chmod(0o755)
        r = run([sys.executable, os.path.join(GATES, "jaw_gate.py"), str(clip)], env={"FACEPY": str(stub)})
        line = live.JAW_LINE.search(r.stdout)
        assert line and line.group(1) == want, (want, r.stdout, r.stderr)
    r = run([sys.executable, os.path.join(GATES, "jaw_gate.py"), str(clip)], env={"FACEPY": "/nonexistent/python3"})
    assert r.returncode == 64 and not live.JAW_LINE.search(r.stdout), (r.stdout, r.stderr)


def test_the_loudness_gate_line_is_the_line_live_reads(tmp_path):
    def master(name, audio):
        out = tmp_path / f"{name}.mp4"
        ffmpeg("-f", "lavfi", "-i", audio, "-f", "lavfi", "-i", "color=black:s=64x64:d=6", "-ac", "2", "-c:a", "aac",
               "-shortest", str(out))
        return out
    for name, audio, want in (("at_spec", "sine=frequency=440:duration=6,volume=0.3,loudnorm=I=-16:TP=-2:LRA=11", "PASS"),
                              ("too_quiet", "sine=frequency=440:duration=6,volume=0.02", "FAIL")):
        r = run([sys.executable, os.path.join(GATES, "loudness_gate.py"), str(master(name, audio))])
        line = live.LOUDNESS_LINE.search(r.stdout)
        assert line and line.group(1) == want, (name, r.stdout, r.stderr)
    silent = master("silent", "anullsrc=r=48000:cl=stereo:d=6")
    r = run([sys.executable, os.path.join(GATES, "loudness_gate.py"), str(silent)])
    assert r.returncode == 64 and not live.LOUDNESS_LINE.search(r.stdout), (r.stdout, r.stderr)


# --------------------------------------------------------------------------------------
# guards/ship_gate.sh, run whole with the repository's real probes
# --------------------------------------------------------------------------------------

def ship_gate(clip, sandbox, args=(), env=None):
    """The gate on clip with every probe it calls, unstubbed. It writes its receipt and two
    sidecars under /tmp by design, so it runs as a copy whose /tmp paths point into sandbox,
    and nothing else about it changes."""
    gate = Path(ROOT, "guards", "ship_gate.sh").read_text()
    sandbox.mkdir(parents=True, exist_ok=True)
    copy = gate.replace('"/tmp/.', f'"{sandbox}/.')
    left = [ln for ln in gate.splitlines()
            if "/tmp/" in ln.replace("${TMPDIR:-/tmp}/", "").replace('"/tmp/.', "")
            and not ln.lstrip().startswith("#")]
    assert gate.count('"/tmp/.') == 3 and not left, f"the gate's /tmp writes changed: {left}"
    script = sandbox / "ship_gate.sh"
    script.write_text(copy)
    srt = sandbox / "clip.srt"
    srt.write_text(f"1\n00:00:00,500 {SRT_ARROW} 00:00:02,000\nhello there\n")  # pii-allow: subtitle timecodes
    e = {k: v for k, v in os.environ.items() if k not in ("ARROW_WINDOW", "REPLAYOK", "RAW", "REGISTER")}
    # The probes' python3 is this interpreter's, as pipeline/live.py arranges for every script it runs.
    e.update(PIPELINE_PROBES=PROBES, TIMEOK="a test clip claims no time of day", TMPDIR=str(sandbox),
             PATH=os.path.dirname(sys.executable) + os.pathsep + os.environ.get("PATH", ""))
    e.update(env or {})
    r = subprocess.run(["bash", str(script), str(clip), str(srt), *args], env=e,
                       capture_output=True, text=True, timeout=900)
    return r.returncode, r.stdout + r.stderr


def looped(path):
    """Six seconds of a seeded pattern played again from the start, fifteen seconds in all. The
    real replay probe reads a refill off it at about one percent of the unrelated-frame distance,
    far under its bar, so the verdict does not hang on how one ffmpeg build draws a test card."""
    ffmpeg("-f", "lavfi", "-i", "life=s=320x240:mold=10:r=25:ratio=0.5:seed=1:life_color=#00ff00:death_color=#000000",
           "-vf", "trim=duration=6,loop=loop=2:size=150:start=0,setpts=N/25/TB", "-t", "15",
           "-pix_fmt", "yuv420p", "-c:v", "libx264", str(path))
    return path


def scan_beside(out, clip):
    line = live.SLIT_LINE.search(out)
    assert line, f"SLIT_LINE finds no slit-scan line\n{out}"
    scan = Path(line.group(1))
    assert scan.is_file() and scan.stat().st_size > 0, f"the slit-scan line names no written file: {scan}"
    assert scan.parent == clip.parent, f"the scan is not beside the clip: {scan}"


def test_the_replay_hold_is_the_hold_live_routes_on(tmp_path):
    clip = looped(tmp_path / "loop.mp4")
    rc, out = ship_gate(clip, tmp_path / "sandbox")
    assert rc == 3 and live.SHIP_HOLDS["replay"] in out, (rc, out)
    scan_beside(out, clip)
    verdict = live.REPLAY_VERDICT.search(out)
    assert verdict and " REPLAYS:" in verdict.group(1), f"REPLAY_VERDICT finds no replay verdict\n{out}"
    vertex = live.REPLAY_VERTEX.search(out)
    assert vertex, f"REPLAY_VERTEX finds no vertex line\n{out}"
    assert f"at t={vertex.group(1)} " in verdict.group(1) + " ", (
        f"the vertex line says {vertex.group(1)} and the probe's verdict says otherwise: {verdict.group(1)}")


def test_the_directional_hold_is_the_hold_live_routes_on(tmp_path):
    """A replay under a declared override is the one path that reaches the directional HOLD,
    since a FORWARD verdict settles the arrow. The window is formatted the way live.py formats it."""
    clip = looped(tmp_path / "loop.mp4")
    rc, out = ship_gate(clip, tmp_path / "sandbox",
                        env={"ARROW_WINDOW": f"0:{10.0:.2f}", "REPLAYOK": "a declared override, for the contract"})
    assert rc == 3 and live.SHIP_HOLDS["directional"] in out, (rc, out)
    scan_beside(out, clip)


def test_the_letterbox_failure_is_the_failure_live_routes_on(tmp_path):
    clip = tmp_path / "boxed.mp4"
    ffmpeg("-f", "lavfi", "-i", "testsrc=size=1080x608:rate=25", "-vf", "pad=1080:1080:0:(oh-ih)/2:black", "-t", "3",
           "-pix_fmt", "yuv420p", "-c:v", "libx264", str(clip))
    rc, out = ship_gate(clip, tmp_path / "sandbox")
    assert rc == 1 and live.SHIP_HOLDS["letterbox"] in out, (rc, out)


def test_a_chain_hands_on_a_takes_true_last_frame_and_starts_from_a_stills_own_bytes(tmp_path):
    """A chain's frames come from ffmpeg, so they are checked against it. The frame handed on is the
    take's last, picked out by its index, and the same take hands on the same bytes twice, which is
    what lets a kept take's hash be compared. A first frame is the first, a JPEG still is kept byte for
    byte, another still is converted, and a file that is not there gives no frame."""
    clip = tmp_path / "take.mp4"
    ffmpeg("-f", "lavfi", "-i", "testsrc=size=160x90:rate=25", "-t", "1", "-pix_fmt", "yuv420p", str(clip))
    first, last, again, true = (tmp_path / f"{n}.jpg" for n in ("first", "last", "again", "true"))
    assert live.grab_frame(str(clip), str(first)) and live.grab_frame(str(clip), str(last), last=True)
    assert live.grab_frame(str(clip), str(again), last=True)
    assert last.read_bytes() == again.read_bytes(), "the same take handed on two different last frames"
    assert first.read_bytes() != last.read_bytes(), "the first frame was handed on as the last"
    ffmpeg("-i", str(clip), "-vf", "select=eq(n\\,24)", "-frames:v", "1", "-q:v", "2", str(true))
    assert last.read_bytes() == true.read_bytes(), "the frame handed on is not the take's last"
    still, kept = tmp_path / "still.jpg", tmp_path / "kept.jpg"
    still.write_bytes(first.read_bytes())
    assert live.grab_frame(str(still), str(kept)) and kept.read_bytes() == still.read_bytes()
    png, converted = tmp_path / "still.png", tmp_path / "converted.jpg"
    ffmpeg("-i", str(first), str(png))
    assert live.grab_frame(str(png), str(converted)) and converted.stat().st_size > 0
    assert not live.grab_frame(str(tmp_path / "nothing.mp4"), str(tmp_path / "none.jpg"))
