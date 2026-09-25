# For an agent or a person opening this repository cold

This is an autonomous ad pipeline and the evals that gate it. The pipeline is a
LangGraph in `pipeline/graph.py`, and every gate it routes on is a script in
`gates/`, `guards/` or `probes/` that you can also run on its own.

## Run everything CI runs

```
make check
```

That creates `.venv`, installs what CI installs, and runs lint, the threshold
derivation, the instrument certificate, the figure byte-checks, the test suite
with coverage, a dry run of one spot through the graph, and the August ledgers
checked against the graph's edges. CI runs this same target, so green here means
green on the Actions tab.

Prerequisites: `python3` 3.10 or newer, and `ffmpeg` with `ffprobe` on PATH.
Nothing needs an account, a key, or a GPU.

## The graph

```
make dry                                                  # one spot, stops before any spend
.venv/bin/python -m pipeline.run --board shoots/graph-zai-cast/boards.json --spot zai --mode dry
```

A dry run executes the board gate for real, records the scene requests a live run
would send and what they would cost, and stops. `--mode live` spends, checks the whole
environment listed at the top of `pipeline/live.py` before it starts, and never runs in
CI. A live run that reaches the eye or the review exits 3 and waits. `--resume <run-dir>
--answer '<json>'` continues it. An answer the graph cannot act on is refused and the run
keeps waiting, and a flag someone has to read off a picture is never answered by a
preset. `--resume <run-dir> --from <step>` re-enters it before a step that failed on a
defect since fixed, without paying again for the steps before it. The step list every
surface reads is `pipeline/steps.py`, and what a run writes to its ledger is in
`pipeline/SCHEMA.md`.

## Individual commands, once `make setup` has run

```
.venv/bin/python evals/derive.py         # every threshold against its labels
.venv/bin/python evals/certify.py        # can each probe still measure a known shift
.venv/bin/python -m pytest tests/ -q     # the suite, with the counts read from the files they describe
```

## What is optional

`make setup-face` installs insightface and mediapipe for the two gates that
locate a face. The tests do not need them, because those imports are lazy.
Measuring a real clip with `gates/mouth_sync_probe.py` or `gates/source_gate.py`
does.

## Before committing

`make hooks` wires the pre-commit PII gate for this clone. It runs a deterministic
pattern scan and then a language-model review of the staged diff, and either one
failing stops the commit. The review runs through `tools/reviewers/claude_cli.sh`,
which expects the `claude` CLI on PATH.

## Where things are

`README.md` is the argument. `docs/PIPELINE.md` is how the pipeline went from an
agent reading a doctrine file to this graph, and what stayed out. `docs/EVALS.md`
is the method, including which of unit, probe, eval or runner every check is.
`docs/TIERS.md` is the shoot, tier by tier, with the ledgers behind each number.
`evals/labels.csv` is the grades and `evals/derive.py` is what turns them into
thresholds.
