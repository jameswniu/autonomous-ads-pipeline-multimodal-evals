# For an agent or a person opening this repository cold

This is an autonomous ad pipeline and the evals that gate it. Nothing here is a
package. Every file is a leaf you run directly.

## Run everything CI runs

```
make check
```

That creates `.venv`, installs what CI installs, and runs lint, the threshold
derivation, the instrument certificate, the figure byte-checks, and the test
suite with coverage. Green means the same thing here as on the Actions tab.

Prerequisites: `python3` 3.10 or newer, and `ffmpeg` with `ffprobe` on PATH.
Nothing needs an account, a key, or a GPU.

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

`README.md` is the argument. `docs/EVALS.md` is the method, including which of
unit, probe, eval or runner every check is. `docs/TIERS.md` is the shoot, tier by
tier, with the ledgers behind each number. `evals/labels.csv` is the grades and
`evals/derive.py` is what turns them into thresholds.
