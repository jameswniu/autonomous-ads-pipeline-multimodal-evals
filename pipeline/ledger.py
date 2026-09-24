"""The run ledger: one append-only JSON-lines file per run, one schema, written by code.

Nothing wrote the August ledgers but the agent running the shoot, by hand, so their
shape drifts from one shoot to the next: every request id is the literal string
"<request-id>", timestamps are dates with no time, one shoot's landings carry no
timestamp at all, and board verdicts, voice takes and build parameters were never
written down. pipeline/replay.py reads those as they are. This is what the graph
writes instead, and the schema is in pipeline/SCHEMA.md.

A run writes into its own directory, never into shoots/<batch>/. The committed
ledgers are history, and two tests and evals/derive.py treat a second gated-master
row for the same master as a conflict, which is correct: history does not change.
"""
import datetime as dt
import hashlib
import json
import os
import uuid

SCHEMA_VERSION = 1

# Every row carries these, set here. A field of the same name from a caller would silently
# overwrite the row's own seq or time, so it is refused instead.
ENVELOPE = ("schema", "run", "seq", "ts", "kind", "step")


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def fingerprint(identity):
    """What the ledger writes in place of a voice or look id. It shows two rows used the same
    identity without publishing it. It is a plain hash, so it hides an id from a reader but
    confirms one somebody already holds, which is acceptable because an id is useless without
    the account key it belongs to."""
    return "sha256:" + hashlib.sha256(str(identity).encode()).hexdigest()[:12]


class Ledger:
    """Append-only. There is no update and no delete, on purpose."""

    def __init__(self, run_dir, run_id=None):
        self.run_dir = run_dir
        self.run_id = run_id or uuid.uuid4().hex[:12]
        self.path = os.path.join(run_dir, "ledger.jsonl")
        os.makedirs(run_dir, exist_ok=True)
        self.seq = 0
        if os.path.exists(self.path):
            with open(self.path) as fh:
                self.seq = sum(1 for line in fh if line.strip())

    def append(self, kind, step, **fields):
        """Write one event. `step` is the graph node that produced it."""
        clash = sorted(set(fields) & set(ENVELOPE))
        if clash:
            raise ValueError(f"a ledger row cannot set its own {', '.join(clash)}")
        self.seq += 1
        row = {"schema": SCHEMA_VERSION, "run": self.run_id, "seq": self.seq,
               "ts": dt.datetime.now(dt.timezone.utc).isoformat(timespec="milliseconds"),
               "kind": kind, "step": step, **fields}
        with open(self.path, "a") as fh:
            fh.write(json.dumps(row, sort_keys=True) + "\n")
        return row

    def rows(self):
        if not os.path.exists(self.path):
            return []
        with open(self.path) as fh:
            return [json.loads(line) for line in fh if line.strip()]


def new_request_id():
    """A real id, so a landing can be joined to the request that produced it."""
    return "req_" + uuid.uuid4().hex[:16]
