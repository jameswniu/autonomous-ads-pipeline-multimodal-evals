#!/usr/bin/env python3
"""Offline checks for the append-only race ledger."""

import errno
import hashlib
import json
import os
import re
import signal
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from backfill_races import (EXTERNAL_PROVENANCE_LABEL, Sources, _load_scorer,  # noqa: E402
                            append_rows, baseline_cost, build_rows)
from score_race import resolve_panel, score_race  # noqa: E402


def ledger_rows():
    return [json.loads(line) for line in (ROOT / "races/races.jsonl").read_text().splitlines()
            if line.strip()]


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


# Any of these outranks `git -C`, so an inherited value would point every call below
# at some other repository, or at its index, instead of the one named.
_GIT_ENV_OVERRIDES = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY",
                      "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_NAMESPACE", "GIT_COMMON_DIR")


def _git(repo, *args, **kwargs):
    env = {key: value for key, value in os.environ.items() if key not in _GIT_ENV_OVERRIDES}
    # Never climb out of `repo` into an enclosing repository.
    env["GIT_CEILING_DIRECTORIES"] = str(Path(repo).resolve().parent)
    return subprocess.run(["git", "-C", str(repo), *args], env=env, capture_output=True, **kwargs)


def _extract_tree(repo, revision, destination):
    """Write every regular file of `revision` under `destination`, ignoring attributes."""
    listing = _git(repo, "ls-tree", "-r", "-z", "--full-tree", revision)
    assert listing.returncode == 0, listing.stderr.decode(errors="replace")
    entries = []
    for record in filter(None, listing.stdout.split(b"\0")):
        meta, name = record.split(b"\t", 1)
        mode, kind, object_id = meta.split(b" ")
        if kind == b"blob" and mode in (b"100644", b"100755"):
            entries.append((object_id, name.decode("utf-8")))
    batch = _git(repo, "cat-file", "--batch", input=b"".join(oid + b"\n" for oid, _ in entries))
    assert batch.returncode == 0, batch.stderr.decode(errors="replace")
    stream, position, root = batch.stdout, 0, destination.resolve()
    for object_id, name in entries:
        header_end = stream.index(b"\n", position)
        header = stream[position:header_end].split(b" ")
        assert header[0] == object_id and header[1] == b"blob", header
        size = int(header[2])
        body = stream[header_end + 1:header_end + 1 + size]
        position = header_end + 1 + size + 1
        target = (root / name).resolve()
        assert target.is_relative_to(root), name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(body)


def _rows_survive(rows, merged):
    """True when `rows` appear in `merged` in the same relative order."""
    remaining = iter(merged)
    return all(row in remaining for row in rows)


def assert_ledger_only_grew(repo, ledger="races/races.jsonl"):
    """Check that no commit reachable from HEAD dropped or rewrote a published row.

    One rule, applied at every commit rather than along one line of history. An
    ordinary commit may only extend its parent's ledger, so an edited measurement or
    a deleted row breaks the prefix at the commit that did it. A merge is the one
    place where growth cannot be a prefix, since two branches may each append
    different rows and an honest resolution interleaves them, so each parent is asked
    the weaker question instead, whether all of its rows still appear in order.

    Walking every reachable commit rather than first parents is what closes the last
    way around this. Checking a merged branch only at its tip lets a side branch add a
    row in one commit, delete it in the next, and merge the result, with the deletion
    never examined by anything.
    """
    repo = Path(repo)
    shallow = _git(repo, "rev-parse", "--is-shallow-repository", text=True)
    listing = _git(repo, "rev-list", "--parents", "HEAD", text=True)
    if listing.returncode or shallow.returncode or shallow.stdout.strip() != "false":
        return 0  # no history to compare against, and truncated history is not history

    seen = {}

    def version(revision):
        if revision not in seen:
            shown = _git(repo, "show", f"{revision}:{ledger}")
            seen[revision] = shown.stdout if shown.returncode == 0 else b""
        return seen[revision]

    checked = 0
    for line in listing.stdout.splitlines():
        identifiers = line.split()
        revision, parents = identifiers[0], identifiers[1:]
        content = version(revision)
        for parent in parents:
            before = version(parent)
            if len(parents) == 1:
                assert content.startswith(before), (
                    f"{revision} rewrote or dropped ledger rows committed in {parent}")
            else:
                assert _rows_survive(before.splitlines(True), content.splitlines(True)), (
                    f"{revision} merged {parent} but did not keep its ledger rows")
        if any(content != version(parent) for parent in parents) or (not parents and content):
            checked += 1
    current = (repo / ledger).read_bytes()
    assert current.startswith(version("HEAD")), (
        "the working ledger rewrote or dropped rows that are already committed")
    return checked


def ledger_build_root(repo, workdir):
    """The tree the checked-in ledger has to reproduce from.

    The ledger is immutable history. Its rows hash README.md, the boards, the probe
    sources and their outputs as they stood when each row was written, so rebuilding
    it from today's working tree fails the first time anyone edits the README, and
    regenerating the ledger to match would rewrite the evidence it exists to keep.
    Once races.jsonl is committed and unmodified, the build tree is therefore the
    commit that last wrote it. While the ledger is uncommitted or edited, or when
    there is no git history at all (a source download), the working tree is the
    build tree, which is also where tampering with an uncommitted ledger shows up.
    """
    repo = Path(repo)
    try:
        status = _git(repo, "status", "--porcelain", "--", "races/races.jsonl", text=True)
        revision = _git(repo, "log", "-1", "--format=%H", "--", "races/races.jsonl", text=True)
        # In a shallow clone `log` stops at the graft boundary, so the newest commit it
        # can name may not be the one that wrote the ledger, and the tree it hands back
        # would be the wrong evidence. Truncated history is no history for this purpose.
        shallow = _git(repo, "rev-parse", "--is-shallow-repository", text=True)
    except OSError:
        return repo
    if (status.returncode or revision.returncode or status.stdout.strip()
            or not revision.stdout.strip()
            or shallow.returncode or shallow.stdout.strip() != "false"):
        return repo
    snapshot = Path(workdir) / "ledger-build-tree"
    snapshot.mkdir(parents=True)
    _extract_tree(repo, revision.stdout.strip(), snapshot)
    return snapshot


def test_scorer_reproduces_every_hand_winner_with_scores():
    rows = ledger_rows()
    renders = {row["id"]: row for row in rows if row["row_type"] == "render"}
    races = {row["id"]: row for row in rows if row["row_type"] == "race"}
    catalog = json.loads((ROOT / "races/panels.json").read_text())

    expected_complete = {
        "race:ads2-redo:orchard": ("seedance2", True),
        "race:ads6-omni:orchard": ("omni", True),
        "race:ads6-omni:lantern": ("wan3", True),
        "race:ads6-omni:harbor": ("omni", True),
        "race:ads6-omni:slowroad": ("seedance2", True),
    }
    complete = {}
    for race_id, race in races.items():
        competitors = [renders[render_id] for render_id in race["render_ids"]]
        if race["missing_scores"]:
            assert race["computed_winner"] is None
            assert race["agrees"] is None
            assert race["status"] == "missing_scores"
            continue
        values = {
            render["engine"]: {
                probe: measurement["value"]
                for probe, measurement in render["probes"].items()
            }
            for render in competitors
        }
        result = score_race(values, resolve_panel(catalog, race["brief_id"]))
        assert result == race["score"]
        assert result["winner"] == race["computed_winner"]
        expected_agreement = result["winner"] == race["recorded_winner"]
        assert race["agrees"] is expected_agreement
        if expected_agreement:
            assert race["disagreement_reason"] is None
        else:
            assert race["disagreement_reason"]
        complete[race_id] = (race["computed_winner"], race["agrees"])

    # This assertion is intentionally explicit: if a future backfill exposes a
    # disagreement, update the recorded expectation instead of bending scoring.
    assert complete == expected_complete


def test_incomplete_hand_races_are_recorded_not_invented():
    races = {row["id"]: row for row in ledger_rows() if row["row_type"] == "race"}
    assert {
        race_id for race_id, race in races.items() if race["status"] == "missing_scores"
    } == {
        "race:ads2-redo:lantern",
        "race:ads2-redo:harbor",
        "race:ads2-redo:quiet",
        "race:ads2-redo:slowroad",
    }
    assert races["race:ads2-redo:quiet"]["recorded_winner"] == "heygen"


def test_backfill_is_idempotent(tmp_path):
    output = tmp_path / "races.jsonl"
    env = dict(os.environ)
    env.pop("RACE_BASELINE_PROVENANCE", None)
    args = [
        sys.executable,
        str(ROOT / "tools/backfill_races.py"),
        # The last assertion compares against the committed ledger, so the run has to
        # read the tree that ledger was built from. Against today's files it would
        # fail on the first unrelated README edit.
        "--root",
        str(ledger_build_root(ROOT, tmp_path)),
        "--output",
        str(output),
    ]
    first = subprocess.run(args, cwd=ROOT, env=env, capture_output=True, text=True, check=True)
    first_result = json.loads(first.stdout)
    first_bytes = output.read_bytes()
    second = subprocess.run(args, cwd=ROOT, env=env, capture_output=True, text=True, check=True)
    second_result = json.loads(second.stdout)

    assert first_result["appended"] == {
        "race_rows": 9, "render_rows": 28, "unchanged_rows": 0,
    }
    assert second_result["appended"] == {
        "race_rows": 0, "render_rows": 0, "unchanged_rows": 37,
    }
    assert output.read_bytes() == first_bytes
    assert first_bytes == (ROOT / "races/races.jsonl").read_bytes()
    assert any(item["item"] == EXTERNAL_PROVENANCE_LABEL for item in first_result["skipped"])


def test_failed_append_rolls_back_and_retry_is_idempotent(tmp_path):
    output = tmp_path / "races.jsonl"
    # Non-ASCII bytes and noncanonical spacing must survive rollback verbatim.
    committed = {"schema_version": 1, "row_type": "race", "id": "race:committed:café"}
    before = (json.dumps(committed, ensure_ascii=False) + "\n").encode("utf-8")
    output.write_bytes(before)
    args = ["--output", str(output)]
    env = dict(os.environ, RACE_BASELINE_PROVENANCE="")
    # Limit only the child process: the OS allows 1234 bytes of the append,
    # then fails the remaining write with EFBIG instead of sending SIGXFSZ.
    limited_backfill = """
import resource
import signal
import sys
from pathlib import Path

sys.path.insert(0, "tools")
from backfill_races import main

output = Path(sys.argv[sys.argv.index("--output") + 1])
signal.signal(signal.SIGXFSZ, signal.SIG_IGN)
_, hard = resource.getrlimit(resource.RLIMIT_FSIZE)
resource.setrlimit(resource.RLIMIT_FSIZE, (output.stat().st_size + 1234, hard))
main(sys.argv[1:])
"""
    failed = subprocess.run([sys.executable, "-c", limited_backfill, *args],
                            cwd=ROOT, env=env, capture_output=True, text=True)
    assert failed.returncode == 2, failed.stdout + failed.stderr
    assert "File too large" in failed.stderr
    assert output.read_bytes() == before

    command = [sys.executable, str(ROOT / "tools/backfill_races.py"), *args]
    retry = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, text=True, check=True)
    assert json.loads(retry.stdout)["appended"] == {
        "race_rows": 9, "render_rows": 28, "unchanged_rows": 0,
    }
    after = output.read_bytes()
    assert after.startswith(before)
    assert len([json.loads(line) for line in after.splitlines()]) == 38

    repeated = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, text=True, check=True)
    assert json.loads(repeated.stdout)["appended"] == {
        "race_rows": 0, "render_rows": 0, "unchanged_rows": 37,
    }
    assert output.read_bytes() == after


def test_killed_append_recovers_and_retry_matches_a_clean_run(tmp_path):
    """A process killed mid-append must cost the next run nothing.

    The sibling test above ignores SIGXFSZ so the write fails with EFBIG and the
    rollback in append_rows runs. Here the signal keeps its default action, so
    the process dies with the partial bytes on disk and no handler ever runs,
    which is the only way the torn tail actually reaches the next reader.
    """
    output = tmp_path / "races.jsonl"
    committed = {"schema_version": 1, "row_type": "race", "id": "race:committed"}
    before = (json.dumps(committed) + "\n").encode("utf-8")
    output.write_bytes(before)
    args = ["--output", str(output)]
    env = dict(os.environ, RACE_BASELINE_PROVENANCE="")
    killed_backfill = """
import resource
import signal
import sys
from pathlib import Path

sys.path.insert(0, "tools")
from backfill_races import main

output = Path(sys.argv[sys.argv.index("--output") + 1])
signal.signal(signal.SIGXFSZ, signal.SIG_DFL)
_, hard = resource.getrlimit(resource.RLIMIT_FSIZE)
resource.setrlimit(resource.RLIMIT_FSIZE, (output.stat().st_size + 1234, hard))
main(sys.argv[1:])
"""
    killed = subprocess.run([sys.executable, "-c", killed_backfill, *args],
                            cwd=ROOT, env=env, capture_output=True, text=True)
    # The precondition this test exists for: the process really was killed, and
    # it really did leave a torn row behind. Without these the test is vacuous.
    assert killed.returncode == -signal.SIGXFSZ, killed.stdout + killed.stderr
    torn = output.read_bytes()
    assert torn.startswith(before) and len(torn) > len(before)
    assert not torn.endswith(b"\n")

    command = [sys.executable, str(ROOT / "tools/backfill_races.py"), *args]
    retry = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, text=True, check=True)
    report = json.loads(retry.stdout)
    assert report["appended"] == {"race_rows": 9, "render_rows": 28, "unchanged_rows": 0}
    # The interrupted bytes are kept and named, never silently dropped.
    kept = Path(report["recovered_damaged_tail"])
    assert kept.parent == output.parent
    assert kept.read_bytes() == torn[len(before):]
    after = output.read_bytes()
    assert after.startswith(before)
    assert len([json.loads(line) for line in after.splitlines()]) == 38

    clean = tmp_path / "clean.jsonl"
    clean.write_bytes(before)
    subprocess.run([sys.executable, str(ROOT / "tools/backfill_races.py"),
                    "--output", str(clean)], cwd=ROOT, env=env, capture_output=True, check=True)
    assert after == clean.read_bytes()

    repeated = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, text=True, check=True)
    assert json.loads(repeated.stdout)["appended"] == {
        "race_rows": 0, "render_rows": 0, "unchanged_rows": 37,
    }
    assert output.read_bytes() == after


def test_a_damaged_tail_with_no_work_fails_loudly_and_changes_nothing(tmp_path):
    """Reading is not repairing, and a ledger no reader can parse is not a success."""
    output = tmp_path / "races.jsonl"
    committed = {"schema_version": 1, "row_type": "race", "id": "race:committed"}
    hand_edited = (json.dumps(committed) + "\n" + '{"schema_version": 1, "row_typ').encode("utf-8")
    output.write_bytes(hand_edited)

    # Every proposed row is already present, so there is nothing to write.
    try:
        append_rows(output, [committed])
    except ValueError as exc:
        assert "damaged final line" in str(exc) and "unchanged" in str(exc)
    else:
        raise AssertionError("a ledger with a damaged final line was reported as a success")
    assert output.read_bytes() == hand_edited
    assert list(output.parent.glob("*.damaged-*")) == []


def test_a_row_that_could_not_be_read_back_is_never_written(tmp_path):
    """Whatever the reader would refuse, the writer refuses first, before touching the file."""
    output = tmp_path / "races.jsonl"
    committed = {"schema_version": 1, "row_type": "race", "id": "race:committed"}
    before = (json.dumps(committed) + "\n").encode("utf-8")
    output.write_bytes(before)

    rejected = [
        ("a schema this version cannot read", {"schema_version": 2, "row_type": "race", "id": "race:new"}),
        # Used to be written and flushed, then raise while counting what had been written.
        ("no row type at all", {"schema_version": 1, "id": "race:new"}),
        ("an unknown row type", {"schema_version": 1, "row_type": "note", "id": "race:new"}),
        ("no identity", {"schema_version": 1, "row_type": "race"}),
        ("not an object", ["schema_version", 1]),
    ]
    for description, row in rejected:
        try:
            append_rows(output, [row])
        except ValueError:
            pass
        else:
            raise AssertionError(f"a row with {description} was accepted")
        assert output.read_bytes() == before, f"a row with {description} reached the file"

    # The ledger is still readable and still appendable afterwards.
    assert append_rows(output, [{"schema_version": 1, "row_type": "render", "id": "render:new"}]) == {
        "race_rows": 0, "render_rows": 1, "unchanged_rows": 0,
    }


def test_a_failed_validation_leaves_a_damaged_tail_alone(tmp_path):
    """A run that raises must not have already shortened the file."""
    output = tmp_path / "races.jsonl"
    unreadable = {"schema_version": 2, "row_type": "race", "id": "race:newer"}
    hand_edited = (json.dumps(unreadable) + "\n" + "not json at all").encode("utf-8")
    output.write_bytes(hand_edited)
    try:
        append_rows(output, [{"schema_version": 1, "row_type": "render", "id": "render:new"}])
    except ValueError as exc:
        assert "unsupported ledger row" in str(exc)
    else:
        raise AssertionError("an unreadable ledger was accepted")
    assert output.read_bytes() == hand_edited
    assert list(output.parent.glob("*.damaged-*")) == []


def test_complete_final_row_missing_its_newline_is_never_discarded(tmp_path):
    """Recovery truncates torn bytes, and only torn bytes."""
    output = tmp_path / "races.jsonl"
    first = {"schema_version": 1, "row_type": "race", "id": "race:first"}
    last = {"schema_version": 1, "row_type": "render", "id": "render:unterminated"}
    addition = {"schema_version": 1, "row_type": "render", "id": "render:new"}
    # The final row is whole; only its terminator is missing.
    output.write_bytes((json.dumps(first) + "\n" + json.dumps(last)).encode("utf-8"))

    assert append_rows(output, [addition]) == {
        "race_rows": 0, "render_rows": 1, "unchanged_rows": 0,
    }
    assert [json.loads(line) for line in output.read_bytes().splitlines()] == [first, last, addition]
    assert append_rows(output, [last, addition]) == {
        "race_rows": 0, "render_rows": 0, "unchanged_rows": 2,
    }


def test_unterminated_row_with_unsupported_schema_is_rejected_untouched(tmp_path):
    """Recovery must not delete a complete row just because this version cannot read it."""
    output = tmp_path / "races.jsonl"
    previous = {"schema_version": 1, "row_type": "race", "id": "race:previous"}
    newer = {"schema_version": 2, "row_type": "race", "id": "race:from-a-newer-writer"}
    before = (json.dumps(previous) + "\n" + json.dumps(newer)).encode("utf-8")
    output.write_bytes(before)
    addition = {"schema_version": 1, "row_type": "render", "id": "render:new"}
    try:
        append_rows(output, [addition])
    except ValueError as exc:
        assert "unsupported ledger row" in str(exc)
    else:
        raise AssertionError("an unreadable final row was accepted")
    assert output.read_bytes() == before


def test_a_failed_backup_leaves_the_ledger_whole(tmp_path):
    """A backup that cannot be written must not cost the ledger its damaged bytes.

    The failure has to be PERSISTENT. With a one-shot fault the rollback simply
    rewrites the tail and every arrangement looks correct, which is why this uses a
    file size limit: the copy fails, and so would any attempt to put the tail back.
    """
    output = tmp_path / "races.jsonl"
    committed = {"schema_version": 1, "row_type": "race", "id": "race:committed"}
    # Larger than the limit below, so neither the copy nor a restore could complete.
    damaged = b'{"schema_version": 1, "row_type": "' + b"x" * 2000
    before = (json.dumps(committed) + "\n").encode("utf-8") + damaged
    output.write_bytes(before)

    limited = """
import json
import resource
import signal
import sys
from pathlib import Path

sys.path.insert(0, "tools")
from backfill_races import append_rows

signal.signal(signal.SIGXFSZ, signal.SIG_IGN)
resource.setrlimit(resource.RLIMIT_FSIZE, (1024, resource.getrlimit(resource.RLIMIT_FSIZE)[1]))
output = Path(sys.argv[1])
rows = [json.loads(sys.argv[2]), json.loads(sys.argv[3])]
try:
    append_rows(output, rows)
except BaseException as exc:
    print(type(exc).__name__, file=sys.stderr)
    raise SystemExit(3)
raise SystemExit(0)
"""
    addition = {"schema_version": 1, "row_type": "render", "id": "render:new"}
    attempt = subprocess.run(
        [sys.executable, "-c", limited, str(output), json.dumps(committed), json.dumps(addition)],
        cwd=ROOT, capture_output=True, text=True, env=dict(os.environ, RACE_BASELINE_PROVENANCE=""))
    assert attempt.returncode == 3, attempt.stdout + attempt.stderr

    assert output.read_bytes() == before
    # No half-written copy is left behind pretending to hold the bytes.
    assert list(output.parent.glob("*.damaged-*")) == []

    recovered = append_rows(output, [committed, addition])
    assert Path(recovered["recovered_damaged_tail"]).read_bytes() == damaged
    after = output.read_bytes()
    assert after.endswith(b"\n")
    assert [json.loads(line) for line in after.splitlines()] == [committed, addition]


def test_a_failed_append_puts_the_damaged_tail_back(tmp_path):
    """Clearing the tail belongs to the append, so a failure undoes both."""
    output = tmp_path / "races.jsonl"
    committed = {"schema_version": 1, "row_type": "race", "id": "race:committed"}
    addition = {"schema_version": 1, "row_type": "render", "id": "render:new"}
    damaged = b'{"schema_version": 1, "row_ty'
    before = (json.dumps(committed) + "\n").encode("utf-8") + damaged
    output.write_bytes(before)

    real_fsync = os.fsync
    committed_bytes = (json.dumps(committed) + "\n").encode("utf-8")
    reached = {"truncated": False, "fired": False}

    def fail_on_the_append(fd):
        # Keyed on what the file looks like rather than on a call count, so adding a
        # flush elsewhere cannot quietly move this failure to a different step.
        size = output.stat().st_size
        if size == len(committed_bytes):
            reached["truncated"] = True
        elif reached["truncated"] and size > len(committed_bytes) and not reached["fired"]:
            # Once only, so the rollback's own flush is not caught by the same fault.
            reached["fired"] = True
            raise OSError(errno.EIO, "simulated fsync failure")
        return real_fsync(fd)

    with patch("backfill_races.os.fsync", side_effect=fail_on_the_append):
        try:
            append_rows(output, [committed, addition])
        except ValueError as exc:
            assert "the damaged tail was put back" in str(exc)
            kept = Path(str(exc).rsplit(" is at ", 1)[1].rstrip(")"))
        else:
            raise AssertionError("a failed append was reported as a success")

    # The file is exactly as it was found, damaged bytes and all, and the copy is real.
    assert output.read_bytes() == before
    assert kept.read_bytes() == damaged

    recovered = append_rows(output, [committed, addition])
    assert recovered["render_rows"] == 1
    assert Path(recovered["recovered_damaged_tail"]).read_bytes() == damaged
    after = output.read_bytes()
    assert after.endswith(b"\n")
    assert [json.loads(line) for line in after.splitlines()] == [committed, addition]


def test_fsync_failure_rolls_back_before_retry(tmp_path):
    output = tmp_path / "races.jsonl"
    committed = {"schema_version": 1, "row_type": "race", "id": "race:committed"}
    addition = {"schema_version": 1, "row_type": "render", "id": "render:new"}
    before = (json.dumps(committed) + "\n").encode("utf-8")
    output.write_bytes(before)

    real_fsync = os.fsync

    def fail_sync(fd):
        if sync.call_count == 1:
            # The append is visible before durability can be confirmed.
            assert output.read_bytes().startswith(before)
            assert output.stat().st_size > len(before)
            raise OSError(errno.EIO, "simulated fsync failure")
        return real_fsync(fd)

    with patch("backfill_races.os.fsync", side_effect=fail_sync) as sync:
        try:
            append_rows(output, [committed, addition])
        except OSError as exc:
            assert exc.errno == errno.EIO
        else:
            raise AssertionError("fsync failure was reported as a successful append")
        assert sync.call_count == 2
    assert output.read_bytes() == before

    with patch("backfill_races.os.fsync", wraps=real_fsync) as sync:
        assert append_rows(output, [committed, addition]) == {
            "race_rows": 0, "render_rows": 1, "unchanged_rows": 1,
        }
        sync.assert_called_once()
    after = output.read_bytes()
    assert after.startswith(before)
    assert [json.loads(line) for line in after.splitlines()] == [committed, addition]
    assert append_rows(output, [committed, addition]) == {
        "race_rows": 0, "render_rows": 0, "unchanged_rows": 2,
    }
    assert output.read_bytes() == after


def test_probe_implementation_and_output_hashes_are_recorded(tmp_path):
    build_root = ledger_build_root(ROOT, tmp_path)
    renders = [row for row in ledger_rows() if row["row_type"] == "render"]
    assert renders
    for render in renders:
        assert set(render["probes"]) == {
            "hand_probe", "bg_detail", "eye_eval", "scene_simplicity", "level_probe"
        }
        for measurement in render["probes"].values():
            implementation = build_root / measurement["file"]
            assert measurement["sha256"] == sha256(implementation)
            assert measurement["hash_basis"] == "repository_snapshot_at_backfill"

    redo = [row for row in renders if row["shoot"] == "ads6-omni"]
    assert len(redo) == 8
    for render in redo:
        for measurement in render["probes"].values():
            outputs = [source for source in measurement["sources"]
                       if source["path"].startswith("shoots/ads6-omni/probe-outputs/")]
            assert len(outputs) == 1
            output = build_root / outputs[0]["path"]
            assert outputs[0]["sha256"] == sha256(output)
            assert measurement["panel_score_agrees"] is True


def test_the_committed_ledger_has_only_ever_grown():
    """Every committed version of the ledger is a prefix of the version after it.

    Pinning verification to the commit that last wrote the ledger answers "does this
    reproduce" but not "is this the same ledger", because a rewrite carries its own
    pin with it. Someone could change a recorded measurement, regenerate, commit, and
    every reproduction check would still agree with itself. Append-only history has a
    property no single revision can forge: earlier bytes survive unchanged. A rewritten
    row breaks the prefix at the commit that introduced it, and this says which one.
    """
    assert_ledger_only_grew(ROOT)


def test_checked_in_ledger_is_exact_backfill(tmp_path):
    with patch.dict(os.environ, {"RACE_BASELINE_PROVENANCE": ""}):
        expected, _skipped = build_rows(ledger_build_root(ROOT, tmp_path))
    assert ledger_rows() == expected


def test_scorer_comes_from_the_tree_whose_hash_is_recorded(tmp_path):
    """A row records the scorer's hash, so that file must be the one that ran."""
    alternate = tmp_path / "pinned-checkout"
    (alternate / "tools").mkdir(parents=True)
    (alternate / "tools/score_race.py").write_text(
        "def resolve_panel(catalog, brief):\n"
        "    return {'from_the_pinned_checkout': brief}\n"
        "def score_race(values, panel):\n"
        "    return {'from_the_pinned_checkout': True}\n")

    pinned_resolve, pinned_score = _load_scorer(alternate)
    assert pinned_resolve({}, "orchard") == {"from_the_pinned_checkout": "orchard"}
    assert pinned_score({}, {}) == {"from_the_pinned_checkout": True}

    # This checkout keeps the module already imported, so nothing is loaded twice.
    assert _load_scorer(ROOT) == (resolve_panel, score_race)


def test_a_rewritten_row_is_caught_even_though_it_reproduces(tmp_path):
    """The case the reproduction check cannot see, because a rewrite carries its own pin."""
    repo = tmp_path / "repo"
    (repo / "races").mkdir(parents=True)

    def git(*args):
        result = _git(repo, "-c", "user.name=ledger-test", "-c", "user.email=ledger-test",
                      "-c", "commit.gpgsign=false", "-c", "core.hooksPath=/dev/null", *args, text=True)
        assert result.returncode == 0, result.stderr
        return result.stdout

    git("init", "-q")
    ledger = repo / "races/races.jsonl"
    first = '{"id":"race:one","measurement":0.468}\n'
    ledger.write_text(first)
    git("add", "-A")
    git("commit", "-q", "-m", "ledger")

    # Appending is what the ledger is for, and it stays legal.
    ledger.write_text(first + '{"id":"race:two","measurement":0.5}\n')
    git("commit", "-q", "-am", "append")
    assert assert_ledger_only_grew(repo) == 2

    # Changing an already committed measurement is not, even committed and self-consistent.
    ledger.write_text(first.replace("0.468", "0.469") + '{"id":"race:two","measurement":0.5}\n')
    git("commit", "-q", "-am", "regenerate")
    try:
        assert_ledger_only_grew(repo)
    except AssertionError as exc:
        assert "rewrote or dropped ledger rows" in str(exc)
    else:
        raise AssertionError("a rewritten measurement passed the append-only check")


def test_a_row_deleted_on_a_side_branch_is_caught_after_the_merge(tmp_path):
    """Checking a merged branch only at its tip would miss the commit that deleted a row."""
    repo = tmp_path / "repo"
    (repo / "races").mkdir(parents=True)

    def git(*args):
        result = _git(repo, "-c", "user.name=ledger-test", "-c", "user.email=ledger-test",
                      "-c", "commit.gpgsign=false", "-c", "core.hooksPath=/dev/null", *args, text=True)
        assert result.returncode == 0, result.stderr
        return result.stdout

    git("init", "-q", "-b", "main")
    ledger = repo / "races/races.jsonl"
    shared = '{"id":"race:one"}\n'
    ledger.write_text(shared)
    git("add", "-A")
    git("commit", "-q", "-m", "ledger")

    git("checkout", "-q", "-b", "side")
    ledger.write_text(shared + '{"id":"race:published-then-removed"}\n')
    git("commit", "-q", "-am", "publish evidence")
    # The tip no longer holds it, so a tip-only check sees nothing wrong.
    ledger.write_text(shared)
    git("commit", "-q", "-am", "quietly drop it again")

    git("checkout", "-q", "main")
    merge = _git(repo, "-c", "user.name=ledger-test", "-c", "user.email=ledger-test",
                 "-c", "core.hooksPath=/dev/null", "merge", "-q", "--no-ff", "-m", "merge", "side",
                 text=True)
    assert merge.returncode == 0, merge.stderr
    assert ledger.read_text() == shared

    try:
        assert_ledger_only_grew(repo)
    except AssertionError as exc:
        assert "rewrote or dropped ledger rows" in str(exc)
    else:
        raise AssertionError("a row deleted on a side branch survived the check")


def test_a_merge_that_keeps_both_branches_is_allowed(tmp_path):
    """Two branches appending different rows is honest, and must stay mergeable."""
    repo = tmp_path / "repo"
    (repo / "races").mkdir(parents=True)

    def git(*args):
        result = _git(repo, "-c", "user.name=ledger-test", "-c", "user.email=ledger-test",
                      "-c", "commit.gpgsign=false", "-c", "core.hooksPath=/dev/null", *args, text=True)
        assert result.returncode == 0, result.stderr
        return result.stdout

    git("init", "-q", "-b", "main")
    ledger = repo / "races/races.jsonl"
    shared = '{"id":"race:one"}\n'
    on_side = '{"id":"race:from-the-side"}\n'
    on_main = '{"id":"race:from-main"}\n'
    ledger.write_text(shared)
    git("add", "-A")
    git("commit", "-q", "-m", "ledger")

    git("checkout", "-q", "-b", "side")
    ledger.write_text(shared + on_side)
    git("commit", "-q", "-am", "evidence on the side branch")

    git("checkout", "-q", "main")
    ledger.write_text(shared + on_main)
    git("commit", "-q", "-am", "evidence on main")

    # The honest resolution keeps every row from both sides.
    merge = _git(repo, "merge", "-q", "--no-ff", "--no-commit", "side", text=True)
    assert merge.returncode != 0 or True  # a conflict here is expected and resolved next
    ledger.write_text(shared + on_main + on_side)
    git("add", "races/races.jsonl")
    git("-c", "core.hooksPath=/dev/null", "commit", "-q", "-m", "merge keeping both")

    assert assert_ledger_only_grew(repo) >= 2
    # And it stays mergeable afterwards, rather than failing forever.
    ledger.write_text(shared + on_main + on_side + '{"id":"race:later"}\n')
    git("commit", "-q", "-am", "append after the merge")
    assert assert_ledger_only_grew(repo) >= 3


def test_a_merge_cannot_hide_the_evidence_it_discarded(tmp_path):
    """Resolving a merge in favour of one side must not erase the other side's rows."""
    repo = tmp_path / "repo"
    (repo / "races").mkdir(parents=True)

    def git(*args):
        result = _git(repo, "-c", "user.name=ledger-test", "-c", "user.email=ledger-test",
                      "-c", "commit.gpgsign=false", "-c", "core.hooksPath=/dev/null", *args, text=True)
        assert result.returncode == 0, result.stderr
        return result.stdout

    git("init", "-q", "-b", "main")
    ledger = repo / "races/races.jsonl"
    shared = '{"id":"race:one"}\n'
    ledger.write_text(shared)
    git("add", "-A")
    git("commit", "-q", "-m", "ledger")

    git("checkout", "-q", "-b", "side")
    published = shared + '{"id":"race:published-on-the-side"}\n'
    ledger.write_text(published)
    git("commit", "-q", "-am", "evidence on the side branch")

    git("checkout", "-q", "main")
    ledger.write_text(shared + '{"id":"race:published-on-main"}\n')
    git("commit", "-q", "-am", "evidence on main")

    # Merge that throws the side branch's row away, which is the move this must catch.
    merge = _git(repo, "-c", "user.name=ledger-test", "-c", "user.email=ledger-test",
                 "-c", "core.hooksPath=/dev/null", "merge", "-q", "--no-ff", "-X", "ours",
                 "-m", "merge", "side", text=True)
    assert merge.returncode == 0, merge.stderr
    assert ledger.read_text() == shared + '{"id":"race:published-on-main"}\n'

    try:
        assert_ledger_only_grew(repo)
    except AssertionError as exc:
        assert "did not keep its ledger rows" in str(exc)
    else:
        raise AssertionError("a merge that discarded published rows passed the check")


def test_ledger_build_root_pins_the_commit_that_wrote_the_ledger(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()

    def git(*args):
        result = _git(repo, "-c", "user.name=ledger-test", "-c", "user.email=ledger-test",
                      "-c", "commit.gpgsign=false", "-c", "core.hooksPath=/dev/null", *args, text=True)
        assert result.returncode == 0, result.stderr
        return result.stdout

    git("init", "-q")
    (repo / "races").mkdir()
    (repo / "README.md").write_text("evidence as built\n")
    (repo / "races/races.jsonl").write_text("ledger built from that evidence\n")
    # An attribute that would silently drop the file from `git archive`.
    (repo / ".gitattributes").write_text("README.md export-ignore\n")
    git("add", "-A")
    git("commit", "-q", "-m", "ledger")
    (repo / "README.md").write_text("an unrelated edit, committed later\n")
    git("commit", "-q", "-am", "docs")
    (repo / "README.md").write_text("an unrelated edit, not committed\n")

    pinned = ledger_build_root(repo, tmp_path / "first")
    assert pinned != repo
    assert (pinned / "README.md").read_text() == "evidence as built\n"
    assert (pinned / "races/races.jsonl").read_text() == "ledger built from that evidence\n"

    # An edited ledger has no commit to reproduce from, so it is judged on the working tree.
    (repo / "races/races.jsonl").write_text("tampered\n")
    assert ledger_build_root(repo, tmp_path / "second") == repo

    plain = tmp_path / "plain"
    plain.mkdir()
    assert ledger_build_root(plain, tmp_path / "third") == plain

    # A shallow clone cannot say which commit wrote the ledger, so it must not pretend to.
    (repo / "races/races.jsonl").write_text("ledger built from that evidence\n")
    shallow = tmp_path / "shallow"
    clone = _git(tmp_path, "clone", "-q", "--depth", "1", f"file://{repo}", str(shallow), text=True)
    assert clone.returncode == 0, clone.stderr
    assert _git(shallow, "rev-parse", "--is-shallow-repository", text=True).stdout.strip() == "true"
    assert ledger_build_root(shallow, tmp_path / "fourth") == shallow


def test_public_race_files_contain_no_private_identifiers():
    # Fingerprints keep the removed identifiers out of the test source too.
    # Check substrings, including mixed-case prose and longer path components.
    removed_identifiers = {
        "owner username": (9, "c14509b56c711dbdcec656bd6a5b44b268a45a45b1523b617f7797cf8fcfc1c9"),
        "external project name": (11, "94011c846ddace8629ff65c3cc55757df5e6c369c5c0b8bfa11ff3a6bb6a6663"),
        "person first name": (5, "119c9ae6f9ca741bd0a76f87fba0b22cab5413187afb2906aa2875c38e213603"),
    }
    for relative in ("races/races.jsonl", "races/SCHEMA.md", "races/panels.json",
                     "tools/backfill_races.py", "tools/score_race.py"):
        body = (ROOT / relative).read_text().casefold()
        assert not re.search(r"(?:/(?:users|home)/|[a-z]:[\\/]+users[\\/]+)[^\s/\\\"']+", body), relative
        for category, (width, fingerprint) in removed_identifiers.items():
            assert all(
                hashlib.sha256(body[start:start + width].encode()).hexdigest() != fingerprint
                for start in range(len(body) - width + 1)
            ), f"{relative}: contains removed {category}"


def test_ledger_source_paths_are_relative_to_repository():
    def check(value):
        if isinstance(value, list):
            for item in value:
                check(item)
        elif isinstance(value, dict):
            assert "excerpt" not in value
            assert "excerpt_sha256" not in value
            for key, item in value.items():
                if key in ("path", "file"):
                    path = Path(item)
                    assert not path.is_absolute()
                    assert ".." not in path.parts
                    assert (ROOT / path).resolve().is_relative_to(ROOT)
                    assert (ROOT / path).is_file()
                check(item)
    rows = ledger_rows()
    check(rows)
    baseline_renders = [row for row in rows if row.get("engine") == "heygen"]
    assert len(baseline_renders) == 5
    for row in baseline_renders:
        assert {"label": EXTERNAL_PROVENANCE_LABEL} in row["sources"]


def test_unavailable_external_provenance_uses_public_evidence(tmp_path):
    # Even an unusable old ledger must not become a fallback source.
    (tmp_path / "races").mkdir()
    (tmp_path / "races/races.jsonl").write_text("old private evidence is not JSON\n")
    (tmp_path / "README.md").write_text((ROOT / "README.md").read_text())
    for configured in (None, "", str(tmp_path / "missing.md")):
        with patch.dict(os.environ):
            if configured is None:
                os.environ.pop("RACE_BASELINE_PROVENANCE", None)
            else:
                os.environ["RACE_BASELINE_PROVENANCE"] = configured
            skipped = []
            cost = baseline_cost(Sources(tmp_path), skipped)
        assert cost["amount"] == 116
        assert cost["source"]["path"] == "README.md"
        assert skipped[0]["item"] == EXTERNAL_PROVENANCE_LABEL
        assert str(tmp_path) not in json.dumps([cost, skipped])
        assert "scene_rate" not in cost


def test_configured_external_provenance_exports_only_batch_quantities(tmp_path):
    source = tmp_path / "private-input.md"
    source.write_text(
        "ad2 remake batch (TestPerson, private-demo): 16 video-agent scenes "
        "(one reroll) at 4 credits each and 7 avatar_v closers, "
        "private annotations, 116 credits; narrations confidential\n")
    with patch.dict(os.environ, {"RACE_BASELINE_PROVENANCE": str(source)}):
        rows, skipped = build_rows(ROOT)
    costs = [row["cost"]["records"][0] for row in rows if row.get("engine") == "heygen"]
    assert len(costs) == 5
    for cost in costs:
        assert cost == {
            "amount": 116, "unit": "HeyGen credits", "scope": "batch",
            "batch_id": "heygen-ad2-remake", "scene_count": 16, "closer_count": 7,
            "scene_rate": 4,
            "basis": "recorded batch total; includes rerolls and closers; not allocated to briefs",
            "source": {"label": EXTERNAL_PROVENANCE_LABEL},
        }
    serialized = json.dumps([rows, skipped])
    for private in (str(source), "TestPerson", "private-demo", "private annotations", "confidential"):
        assert private not in serialized
    assert not any(item["item"] == EXTERNAL_PROVENANCE_LABEL for item in skipped)


def test_external_provenance_errors_do_not_quote_private_input(tmp_path):
    source = tmp_path / "private-input.md"
    command = [sys.executable, str(ROOT / "tools/backfill_races.py"), "--dry-run"]
    for content in ("private details\n", "ad2 remake batch private details\n"):
        source.write_text(content)
        result = subprocess.run(
            command, cwd=ROOT,
            env=dict(os.environ, RACE_BASELINE_PROVENANCE=str(source)),
            capture_output=True, text=True)
        assert result.returncode == 2
        assert str(source) not in result.stderr
        assert "private details" not in result.stderr
        assert "baseline provenance" in result.stderr


if __name__ == "__main__":
    tests = [
        test_the_committed_ledger_has_only_ever_grown,
        test_scorer_reproduces_every_hand_winner_with_scores,
        test_incomplete_hand_races_are_recorded_not_invented,
        test_public_race_files_contain_no_private_identifiers,
        test_ledger_source_paths_are_relative_to_repository,
    ]
    temporary_tests = [
        test_probe_implementation_and_output_hashes_are_recorded,
        test_checked_in_ledger_is_exact_backfill,
        test_scorer_comes_from_the_tree_whose_hash_is_recorded,
        test_a_rewritten_row_is_caught_even_though_it_reproduces,
        test_a_merge_cannot_hide_the_evidence_it_discarded,
        test_a_merge_that_keeps_both_branches_is_allowed,
        test_a_row_deleted_on_a_side_branch_is_caught_after_the_merge,
        test_ledger_build_root_pins_the_commit_that_wrote_the_ledger,
        test_backfill_is_idempotent,
        test_failed_append_rolls_back_and_retry_is_idempotent,
        test_killed_append_recovers_and_retry_matches_a_clean_run,
        test_a_damaged_tail_with_no_work_fails_loudly_and_changes_nothing,
        test_a_row_that_could_not_be_read_back_is_never_written,
        test_a_failed_validation_leaves_a_damaged_tail_alone,
        test_complete_final_row_missing_its_newline_is_never_discarded,
        test_unterminated_row_with_unsupported_schema_is_rejected_untouched,
        test_a_failed_backup_leaves_the_ledger_whole,
        test_a_failed_append_puts_the_damaged_tail_back,
        test_fsync_failure_rolls_back_before_retry,
        test_unavailable_external_provenance_uses_public_evidence,
        test_configured_external_provenance_exports_only_batch_quantities,
        test_external_provenance_errors_do_not_quote_private_input,
    ]
    for test in temporary_tests:
        with tempfile.TemporaryDirectory() as directory:
            test(Path(directory))
    for test in tests:
        test()
    print(f"{len(tests) + len(temporary_tests)} passed")
