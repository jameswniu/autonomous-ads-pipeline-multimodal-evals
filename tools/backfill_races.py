#!/usr/bin/env python3
"""Backfill the two recorded race cohorts, locally and without vendor calls.

Existing JSONL rows are immutable. Identical identities are no-ops; changed
content under an existing identity is an error, checked before any append.
"""

import argparse
import fcntl
import importlib.util
import hashlib
import json
import os
import re
import typing
from datetime import datetime, timezone
from pathlib import Path

try:
    from .score_race import resolve_panel, score_race
except ImportError:  # direct script invocation
    from score_race import resolve_panel, score_race

ROOT = Path(__file__).resolve().parents[1]
EXTERNAL_PROVENANCE_LABEL = "external batch provenance, not tracked here"
ENGINES = {
    "heygen": ("HeyGen", None),
    "omni": ("Omni Flash", "Flash"),
    "wan3": ("Wan 3.0", "3.0"),
    "seedance2": ("Seedance 2.0", "2.0"),
}
PATTERNS = {
    "hand_probe": r"^HAND gesture ratio ([0-9.]+)\s",
    "bg_detail": r"^BG (?:SIMPLE|TOO BUSY): detail ([0-9.]+)\s",
    "eye_eval": r"^EYE (?:PASS|REJECT): bg ([0-9.]+)\s",
    "scene_simplicity": r"^(?:SIMPLE|TOO BUSY)\s+([0-9.]+)\s",
    "level_probe": r"\| face ([0-9.]+)\s",
}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def read_json(path):
    return json.loads(path.read_text())


def engine_id(label):
    for engine, (name, _) in ENGINES.items():
        if name in label:
            return engine
    raise ValueError(f"unrecognized recorded engine: {label}")


class Sources:
    def __init__(self, root):
        self.root = root
        self.cache = {}

    def text(self, path):
        if path not in self.cache:
            self.cache[path] = (self.root / path).read_text()
        return self.cache[path]

    def ref(self, path, needle=None, line=None):
        body = self.text(path)
        if line is None:
            matches = [n for n, text in enumerate(body.splitlines(), 1) if needle in text]
            if len(matches) != 1:
                raise ValueError(f"{path}: expected one source line for {needle!r}")
            line = matches[0]
        return {"path": path, "line": line,
                "sha256": digest((self.root / path).read_bytes())}

    def ledger_refs(self, shoot, name, brief, engine=None):
        path = f"shoots/{shoot}/{name}"
        refs, records = [], []
        for line, text in enumerate(self.text(path).splitlines(), 1):
            if not text.strip():
                continue
            row = json.loads(text)
            scene = row.get("ad", row.get("scene", ""))
            if scene.split("-")[0] != brief:
                continue
            if engine is not None and row.get("leg") != engine:
                continue
            refs.append(self.ref(path, line=line))
            records.append(row)
        return refs, records


def baseline_cost(sources, skipped):
    """Read optional external evidence without exporting its path or prose."""
    configured = os.environ.get("RACE_BASELINE_PROVENANCE", "")
    provenance_path = Path(configured) if configured else None
    try:
        body = provenance_path.read_text() if provenance_path is not None else None
    except (FileNotFoundError, IsADirectoryError):
        body = None
    except OSError:
        raise ValueError("external batch provenance could not be read") from None
    if body is None:
        skipped.append({"item": EXTERNAL_PROVENANCE_LABEL, "reason":
                        "External source not configured or unavailable; README batch cost retained."})
        return {"amount": 116, "unit": "HeyGen credits", "scope": "batch",
                "batch_id": "heygen-ad2-remake", "scene_count": 16, "closer_count": 7,
                "basis": "recorded batch total; not allocated to briefs",
                "source": sources.ref("README.md", "| A0 | HeyGen video agent")}

    matches = [line for line in body.splitlines() if line.startswith("ad2 remake batch ")]
    if len(matches) != 1:
        raise ValueError("baseline provenance: expected one ad2 remake batch")
    # Extract only production quantities; never copy external prose or account state.
    clause = matches[0].split("; narrations", 1)[0]
    quantities = re.search(r"(\d+) video-agent scenes .* at (\d+) credits each and (\d+) "
                           r"avatar_v closers\b", clause)
    total = re.search(r", (\d+) credits\.?$", clause)
    if not quantities or not total:
        raise ValueError("baseline provenance cost clause could not be parsed")
    scenes, per_scene, closers = map(int, quantities.groups())
    return {"amount": int(total.group(1)), "unit": "HeyGen credits", "scope": "batch",
            "batch_id": "heygen-ad2-remake", "scene_count": scenes, "closer_count": closers,
            "scene_rate": per_scene,
            "basis": "recorded batch total; includes rerolls and closers; not allocated to briefs",
            "source": {"label": EXTERNAL_PROVENANCE_LABEL}}


def _load_scorer(root):
    """Return the scoring functions belonging to `root`, never merely importable ones.

    build_rows records the sha256 of root/tools/score_race.py beside every result, so
    the functions that produce those results have to come from that same file. For this
    checkout that is the module imported above. For a pinned snapshot of the commit a
    ledger was built from it is the snapshot's own scorer, loaded here, so a row can
    never carry the hash of code that did not compute it.
    """
    path = (Path(root) / "tools/score_race.py").resolve()
    if path == (Path(__file__).resolve().parent / "score_race.py").resolve():
        return resolve_panel, score_race
    specification = importlib.util.spec_from_file_location(f"score_race_pinned_{abs(hash(path))}", path)
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module.resolve_panel, module.score_race


def build_rows(root=ROOT):
    """Return deterministic rows plus omissions. No writes and no probe execution."""
    root = Path(root)
    sources = Sources(root)
    catalog = read_json(root / "races/panels.json")
    panels_hash = digest((root / "races/panels.json").read_bytes())
    scorer_hash = digest((root / "tools/score_race.py").read_bytes())
    pinned_resolve_panel, pinned_score_race = _load_scorer(root)
    skipped = []
    baseline = baseline_cost(sources, skipped)
    rows = []
    original_boards = read_json(root / "shoots/ads2-redo/boards.json")
    redo_boards = {shoot: read_json(root / f"shoots/{shoot}/boards.json")
                   for shoot in ("ads5", "ads6-omni")}
    # ads5 explicitly reuses ads4 scenes/closers; ads6 boards explicitly match ads5.
    audience_boards = read_json(root / "shoots/ads4/boards.json")
    panel_scores = read_json(root / "shoots/ads6-omni/panel-score.json")
    readme_lines = sources.text("README.md").splitlines()
    hand_original = {}
    for line, text in enumerate(readme_lines, 1):
        match = re.search(r"\| \[([^]]+)\]\(#winner-([a-z]+)\) \| (.+) \|$", text)
        if match:
            label, brief, why = match.groups()
            hand_original[brief] = (engine_id(label), sources.ref("README.md", line=line), why)
    if set(hand_original) != set(original_boards["ads"]):
        raise ValueError("README winners and original board briefs do not match")

    original_scores = {}
    for probe, label in [(row["probe"], row["label"])
                         for row in pinned_resolve_panel(catalog, "orchard")["rows"]]:
        source = sources.ref("README.md", f"| {label},")
        cells = readme_lines[source["line"] - 1].strip("|").split("|")[1:]
        values = [float(cell.strip().replace("**", "")) for cell in cells]
        if len(values) != 4:
            raise ValueError("Orchard table must contain the four recorded engines")
        original_scores[probe] = (dict(zip(ENGINES, values)), source)

    def measurement(probe, value=None, refs=None, output_path=None):
        probe_path = f"probes/{probe}.py"
        result = {"value": value, "file": probe_path,
                  "sha256": digest((root / probe_path).read_bytes()),
                  "hash_basis": "repository_snapshot_at_backfill",
                  "historical_execution_sha256": None, "sources": refs or []}
        if output_path:
            body = sources.text(output_path)
            match = re.search(PATTERNS[probe], body, re.M)
            if not match:
                raise ValueError(f"{output_path}: no recognizable {probe} value")
            output_value = float(match.group(1))
            result.update(value=output_value, panel_score_value=value,
                          panel_score_agrees=output_value == value)
            result["sources"].append(sources.ref(output_path, line=1))
        return result

    def render_base(shoot, brief, engine, render_shoot, scene_ids, refs):
        name, version = ENGINES[engine]
        return {
            "schema_version": 1, "row_type": "render",
            "id": f"render:{shoot}:{brief}:{engine}", "shoot": shoot,
            "render_shoot": render_shoot, "brief_id": brief,
            "audience": None, "audience_source": None,
            "panel_type": catalog["briefs"][brief]["panel_type"],
            "panels_sha256": panels_hash, "engine": engine, "engine_name": name,
            "engine_version": version, "engine_model": None,
            "scene_count": len(scene_ids), "scene_ids": scene_ids,
            "cost": {"amount": None, "unit": None, "records": []},
            "render_time_seconds": None, "sources": refs,
            "notes": ["Scene count is the three story scenes; excludes the reused avatar closer.",
                      "No render latency recorded; landing dur is media duration and ts is a date.",
                      "Probe code hashes pin the backfill snapshot, not an attested historical execution."],
        }

    def add_race(shoot, brief, renders, hand, hand_sources, hand_reason):
        panel = pinned_resolve_panel(catalog, brief)
        values = {row["engine"]: {p: v["value"] for p, v in row["probes"].items()}
                  for row in renders}
        missing = {engine: [p for p, v in scores.items() if v is None]
                   for engine, scores in values.items() if any(v is None for v in scores.values())}
        result = None if missing else pinned_score_race(values, panel)
        winner = result["winner"] if result else None
        agrees = winner == hand if winner is not None and hand is not None else None
        disagreement = None
        if agrees is False:
            disagreement = (f"Numeric {result['decided_by']} result selects {winner}; "
                            f"row wins {json.dumps(result['row_wins'], sort_keys=True)}. "
                            f"Hand record selects {hand}: {hand_reason}")
        row = {
            "schema_version": 1, "row_type": "race", "id": f"race:{shoot}:{brief}",
            "shoot": shoot, "brief_id": brief, "panel_type": panel["panel_type"],
            "panels_sha256": panels_hash, "panel_snapshot": panel,
            "scorer_sha256": scorer_hash, "render_ids": [r["id"] for r in renders],
            "computed_winner": winner, "recorded_winner": hand,
            "agrees": agrees, "disagreement_reason": disagreement,
            "recorded_reason": hand_reason, "score": result, "missing_scores": missing,
            "status": "missing_scores" if missing else result["decided_by"],
            "sources": hand_sources, "notes": [],
        }
        if missing:
            reason = "Winner computation skipped: no numeric scores for this original race."
            row["notes"].append(reason)
            skipped.append({"item": row["id"], "reason": reason})
        rows.extend(renders)
        rows.append(row)

    for brief, scene_ids in original_boards["ads"].items():
        renders = []
        for engine in ENGINES:
            refs = [sources.ref("shoots/ads2-redo/boards.json", f'"{brief}": ['),
                    hand_original[brief][1]]
            row = render_base("ads2-redo", brief, engine,
                              "ads2" if engine == "heygen" else "ads2-redo", scene_ids, refs)
            if engine == "heygen":
                row["cost"]["records"].append(baseline)
                row["sources"].append(baseline["source"])
                row["sources"].append({"label": EXTERNAL_PROVENANCE_LABEL})
                row["notes"].append("HeyGen baseline is reused from ad2; its engine version is unrecorded.")
            else:
                req_refs, requests = sources.ledger_refs("ads2-redo", "requests.jsonl", brief, engine)
                landing_refs, landings = sources.ledger_refs("ads2-redo", "landings.jsonl", brief, engine)
                row["sources"].extend(req_refs + landing_refs)
                row["request_count"] = len(requests)
                row["landed_scene_count"] = len({r["scene"] for r in landings if r["status"] == "OK"})
                row["media_duration_seconds"] = {
                    r["scene"]: r["dur"] for r in landings if r["status"] == "OK"}
                if engine in ("wan3", "seedance2"):
                    path = f"shoots/ads2-redo/canary-{engine}.json"
                    canary = read_json(root / path)
                    row["engine_model"] = canary["response_url"].split("queue.fal.run/")[1].split("/requests/")[0]
                    row["sources"].append(sources.ref(path, '"response_url"'))
                    row["cost"]["records"].append({
                        "amount": 32, "unit": "USD", "scope": "batch", "approximate": True,
                        "batch_id": "ads2-redo-wan3-seedance2", "scene_count": 30,
                        "basis": "combined engines; no per-engine or per-brief allocation recorded",
                        "source": sources.ref("README.md", "| B2 and B3 |")})
                else:
                    row["cost"]["records"].append({
                        "amount": 9, "unit": "USD", "scope": "batch", "approximate": True,
                        "batch_id": "ads2-redo-omni", "scene_count": 15, "scene_rate": 0.6,
                        "basis": "recorded approximate batch and scene rate; not a render invoice",
                        "source": sources.ref("README.md", "| B1 | Omni Flash |")})
                for n, landing in zip(landing_refs, landings):
                    if landing["status"] != "OK":
                        skipped.append({"item": f"{n['path']}:{n['line']}",
                                        "reason": f"{landing['status']} scene attempt is not a scored render."})
                if row["landed_scene_count"] != row["scene_count"]:
                    row["notes"].append("Landing ledger is incomplete; README attests the final version.")
            row["probes"] = {
                probe: measurement(probe, original_scores[probe][0][engine],
                                   [original_scores[probe][1]]) if brief == "orchard"
                else measurement(probe) for probe in PATTERNS}
            if brief != "orchard":
                row["notes"].append("No numeric scores recorded for this original-race render.")
            row["notes"].append("Original board contains no audience field; later audience text is not backdated.")
            renders.append(row)
        hand, ref, reason = hand_original[brief]
        add_race("ads2-redo", brief, renders, hand, [ref], reason)

    panel_path = "shoots/ads6-omni/panel-score.json"
    panel_text = sources.text(panel_path).splitlines()
    used_outputs = set()
    for brief, recorded in panel_scores.items():
        start = next(n for n, line in enumerate(panel_text, 1) if f'"{brief}": {{' in line)
        renders = []
        for side, engine, render_shoot in [
                ("A", engine_id(recorded["engine_a"]), "ads5"),
                ("B", "omni", "ads6-omni")]:
            board = redo_boards[render_shoot]
            if side == "A":
                spot = board["spots"][brief]
                scene_ids = sorted(f"{brief}-{slot}" for slot in
                                   set(spot["new_scenes"]) | set(spot["reuse"]))
                model = spot["engine"]
                board_ref = sources.ref("shoots/ads5/boards.json", f'"{brief}": {{')
            else:
                scene_ids = sorted(scene for scene in board["prompts"] if scene.startswith(brief + "-"))
                model = board["engine"]
                board_ref = sources.ref("shoots/ads6-omni/boards.json", '"engine"')
            req_refs, requests = sources.ledger_refs(render_shoot, "requests.jsonl", brief)
            landing_refs, landings = sources.ledger_refs(render_shoot, "landings.jsonl", brief)
            masters = [(ref, item) for ref, item in zip(landing_refs, landings)
                       if item.get("kind") == "gated master"]
            if not masters:
                raise ValueError(f"{render_shoot}/{brief}: no gated master")
            master_ref, master = masters[-1]
            row = render_base("ads6-omni", brief, engine, render_shoot, scene_ids,
                              [board_ref, master_ref] + req_refs)
            row["engine_model"] = model
            row["master"] = master["master"]
            row["request_count"] = len(requests)
            row["audience"] = audience_boards["spots"][brief].get("audience")
            if row["audience"] is not None:
                row["audience_source"] = sources.ref("shoots/ads4/boards.json", json.dumps(row["audience"]))
                row["sources"].append(row["audience_source"])
                row["notes"].append("Audience inherited from ads4 board via ads5 reuse and ads6 matching prompts.")
            row["notes"].append("No cost recorded for this redo render; earlier-shoot prices are not invoices.")
            panel = pinned_resolve_panel(catalog, brief)
            values = {}
            search_from = start
            for label, value_a, value_b, _ in recorded["rows"]:
                probe = next(r["probe"] for r in panel["rows"] if label.startswith(r["label"] + ","))
                label_line = next(n for n in range(search_from, len(panel_text))
                                  if json.dumps(label) in panel_text[n])
                search_from = label_line + 1
                output = f"shoots/ads6-omni/probe-outputs/{Path(master['master']).stem}.{probe}.txt"
                used_outputs.add(output)
                panel_ref = sources.ref(panel_path, line=label_line + (2 if side == "A" else 3))
                values[probe] = measurement(probe, value_a if side == "A" else value_b,
                                            [panel_ref], output)
                if not values[probe]["panel_score_agrees"]:
                    row["notes"].append(f"{probe}: raw output and hand transcription disagree; raw output used.")
            if set(values) != set(PATTERNS):
                raise ValueError(f"{brief}: expected all five probes")
            row["probes"] = values
            renders.append(row)
        hand = engine_id(recorded["engine_a"]) if recorded["winner"] == "A" else "omni"
        winner_line = next(n for n in range(start, len(panel_text)) if '"winner":' in panel_text[n]) + 1
        add_race("ads6-omni", brief, renders, hand,
                 [sources.ref(panel_path, line=winner_line), sources.ref("README.md", "- Scored again after the redo,")],
                 recorded["how"])

    for path in sorted((root / "shoots/ads6-omni/probe-outputs").glob("*.txt")):
        rel = str(path.relative_to(root))
        if rel not in used_outputs:
            skipped.append({"item": rel, "reason": "Output does not belong to a scored final master."})
    skipped.extend([
        {"item": "README.md:253", "reason": "Partial September probe rerun is not a separate complete race; original table readings retained."},
        {"item": "shoots/ads2-redo/requests.jsonl:46-47; shoots/ads6-omni/requests.jsonl:13-15",
         "reason": "Reroll requests retained as provenance and request counts, not additional final-render rows."},
        {"item": "shoots/ads2-redo/canary-*.json", "reason": "Queue receipts have empty metrics; no render time to recover."},
        {"item": "render costs and latency", "reason": "No per-render totals or render times recorded; batch costs remain batch-scoped and unknown fields null."},
        {"item": "historical probe versions", "reason": "No historical execution hashes recorded; current source and saved output hashes pinned separately."},
        {"item": "quiet in ads6-omni", "reason": "No redo board, render or scores for Quiet; no synthetic redo race created."},
    ])
    # Every nested evidence path is also discoverable from the top-level sources list.
    for row in rows:
        refs = list(row["sources"])
        for value in row.get("probes", {}).values():
            refs.extend(value["sources"])
        refs.extend(cost["source"] for cost in row.get("cost", {}).get("records", []))
        row["sources"] = list({json.dumps(ref, sort_keys=True): ref for ref in refs}.values())
    return rows, skipped


class _Ledger(typing.NamedTuple):
    body: str            # every committed row, newline terminated, ready to validate
    committed: int       # bytes on disk that belong to committed rows
    damaged: bytes       # unparseable suffix of an interrupted append, still on disk
    unterminated: bool   # the last committed row is intact but missing its newline


def _read_ledger(stream):
    """Read the ledger without changing a byte, describing any damaged tail.

    Returns the text to validate, the number of committed bytes, and the suffix
    after the last newline when that suffix does not parse. Every row this writer
    commits ends in a newline, and a strict prefix of a JSON object can never
    parse, so an unparseable suffix is the remains of an interrupted append. It
    is still not this function's business to delete it: reading is not repairing,
    and an earlier version that truncated here destroyed a hand-edited line and
    modified files that later failed validation anyway. A suffix that DOES parse
    is a complete row that merely lost its terminator, so it stays in the body
    and is validated like any other row, which is what stops a row from a newer
    schema being thrown away for being unfamiliar.
    """
    stream.seek(0)
    raw = stream.read()
    if not raw or raw.endswith(b"\n"):
        return _Ledger(raw.decode("utf-8"), len(raw), b"", False)
    head, separator, tail = raw.rpartition(b"\n")
    try:
        json.loads(tail.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return _Ledger((head + separator).decode("utf-8"), len(head) + len(separator), tail, False)
    return _Ledger(raw.decode("utf-8") + "\n", len(raw), b"", True)


def _set_aside(output, damaged):
    """Keep damaged bytes in a sibling file, durably, before anything overwrites them.

    The ledger exists to preserve evidence, so nothing here may quietly shrink it.
    The caller names the file it wrote in its result, so a recovery is visible to
    whoever reads the output rather than being inferred from a byte count.
    """
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    kept = output.with_name(f"{output.name}.damaged-{stamp}-{digest(damaged)[:12]}")
    try:
        with kept.open("wb") as sidecar:
            sidecar.write(damaged)
            sidecar.flush()
            os.fsync(sidecar.fileno())
    except BaseException:
        # A half-written copy would read as a backup while holding only part of the bytes.
        kept.unlink(missing_ok=True)
        raise
    # The file's own fsync does not publish its name. Without this the truncation that
    # follows could survive a host crash while the directory entry for this copy did not,
    # which is the one ordering that could still lose the bytes.
    directory = os.open(kept.parent, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)
    return kept


def _validate_row(row, where):
    """One definition of a ledger row, applied to what is read and to what is written."""
    if not isinstance(row, dict):
        raise ValueError(f"ledger row {where} is not an object")
    if row.get("schema_version") != 1 or row.get("row_type") not in ("race", "render"):
        raise ValueError(f"unsupported ledger row {where}")
    if not isinstance(row.get("id"), str) or not row["id"]:
        raise ValueError(f"ledger row {where} has no identity")


def _restore(stream, ledger):
    """Put the file back to the bytes `ledger` was read from, damaged tail included."""
    stream.truncate(ledger.committed)
    if ledger.damaged:
        stream.seek(0, os.SEEK_END)
        pending = memoryview(ledger.damaged)
        while pending:
            written = stream.write(pending)
            if not written:
                break
            pending = pending[written:]
    stream.flush()
    os.fsync(stream.fileno())


def append_rows(output, rows):
    """Serialize writers, reject conflicts, and durably append or roll back."""
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    proposed = {}
    for position, row in enumerate(rows, 1):
        # Checked before the file is opened. A row the reader would later refuse used to
        # reach the disk, and a row missing a field raised only while counting what had
        # already been written, which is outside the rollback and so kept the bad row.
        _validate_row(row, f"proposed at position {position}")
        if row["id"] in proposed:
            raise ValueError(f"duplicate proposed identity: {row['id']}")
        proposed[row["id"]] = row
    # Unbuffered I/O prevents close() from re-appending bytes after rollback.
    with output.open("a+b", buffering=0) as stream:
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
        ledger = _read_ledger(stream)
        body = ledger.body
        existing = {}
        for line, text in enumerate(body.splitlines(), 1):
            row = json.loads(text)
            _validate_row(row, f"at line {line}")
            if row["id"] in existing:
                raise ValueError(f"duplicate existing identity: {row['id']}")
            existing[row["id"]] = row
        conflicts = [key for key in proposed if key in existing and proposed[key] != existing[key]]
        if conflicts:
            raise ValueError("immutable ledger conflict (nothing appended): " + ", ".join(conflicts))
        additions = [row for row in rows if row["id"] not in existing]
        payload = "".join(json.dumps(row, sort_keys=True, separators=(",", ":"), allow_nan=False)
                          + "\n" for row in additions).encode("utf-8")
        recovered = None
        if ledger.damaged and not payload:
            # With rows to write, the damaged bytes are set aside and cleared below. With
            # nothing to write there is no occasion to touch the file, and staying silent
            # would hand back exit 0 over a ledger no reader can parse. So say so instead.
            raise ValueError(
                f"damaged final line of {len(ledger.damaged)} bytes after the last complete "
                f"row, and nothing to append, so {output.name} is unchanged")
        # Nothing on disk changes unless there is something to append, so a run that
        # validates, conflicts or simply has no work leaves the file exactly as found.
        if payload and ledger.unterminated:
            # Terminate the intact final row inside the same write the rollback undoes.
            payload = b"\n" + payload
        if payload:
            if ledger.damaged:
                # Outside the rollback below on purpose. Until this returns, the ledger has
                # not been touched, so a backup that fails leaves the original whole instead
                # of triggering a restore that would truncate it first and might not finish.
                recovered = _set_aside(output, ledger.damaged)
            try:
                if ledger.damaged:
                    # Clearing the saved bytes belongs to this write, so a failure below puts
                    # the tail back rather than keeping a shortened ledger nobody asked for.
                    stream.truncate(ledger.committed)
                    stream.flush()
                    os.fsync(stream.fileno())
                stream.seek(0, os.SEEK_END)
                pending = memoryview(payload)
                while pending:
                    written = stream.write(pending)
                    if not written:
                        raise OSError("ledger append made no progress")
                    pending = pending[written:]
                stream.flush()
                os.fsync(stream.fileno())
            except BaseException as failure:
                # Keep the writer lock until the file is exactly as it was found.
                _restore(stream, ledger)
                if recovered is not None:
                    raise ValueError(f"{failure} (the damaged tail was put back, and a copy "
                                     f"is at {recovered})") from failure
                raise
        result = {"render_rows": sum(r["row_type"] == "render" for r in additions),
                  "race_rows": sum(r["row_type"] == "race" for r in additions),
                  "unchanged_rows": sum(key in existing for key in proposed)}
        if recovered is not None:
            # Lifted out of the counts by main() so a recovery is announced, never buried.
            result["recovered_damaged_tail"] = str(recovered)
        return result


def main(argv=None):
    parser = argparse.ArgumentParser(
        description=__doc__,
        epilog="Optional external batch evidence: set RACE_BASELINE_PROVENANCE. "
               "Its default is empty; only numeric production costs are retained.")
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path, help="defaults to ROOT/races/races.jsonl")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    try:
        rows, skipped = build_rows(args.root)
        result = {"render_rows": sum(r["row_type"] == "render" for r in rows),
                  "race_rows": sum(r["row_type"] == "race" for r in rows), "skipped": skipped,
                  "disagreements": [{"race": r["id"], "reason": r["disagreement_reason"]}
                                    for r in rows if r.get("agrees") is False]}
        if not args.dry_run:
            appended = append_rows(args.output or args.root / "races/races.jsonl", rows)
            # A recovery is news about the file, not a count of rows, so it is reported
            # beside the counts where a reader will see it rather than inside them.
            recovered = appended.pop("recovered_damaged_tail", None)
            if recovered is not None:
                result["recovered_damaged_tail"] = recovered
            result["appended"] = appended
    except (OSError, ValueError, KeyError, StopIteration) as exc:
        parser.exit(2, f"backfill_races: {exc}\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
