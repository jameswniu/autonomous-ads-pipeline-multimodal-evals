# One path in, for a person or an agent that has never seen this repository.
#
#   make setup    a virtualenv with exactly what CI installs
#   make check    everything CI runs; CI runs this target, so the two cannot drift
#   make dry      one spot through the graph, stopping before any spend
#   make replay   the August ledgers checked against the graph's edges
#   make hooks    the pre-commit PII gate, once per clone
#
# ffmpeg and ffprobe are system binaries and have to be on PATH already.
# The two gates that locate a face need `make setup-face` on top; every test
# passes without them because their imports are lazy.

# The Make that ships with macOS is 3.81, which ignores .SHELLFLAGS, so there a
# failing command piped into tee still exits 0 and the target reads green. Every
# piped recipe sets pipefail itself for that reason; the flags below cover the rest
# on any newer Make.
SHELL        := /bin/bash
.SHELLFLAGS  := -eo pipefail -c
VENV   ?= .venv
PY     := $(VENV)/bin/python
PIP    := $(PY) -m pip
OUT    := .reports
export PATH := $(CURDIR)/$(VENV)/bin:$(PATH)

.PHONY: setup setup-face check pipcheck imports selftests test derive certify lint figures dry replay ffmpeg hooks clean

# When CI provides a job summary, a report lands there under its own heading, and the
# write is checked where it happens. A redirect that goes nowhere leaves a green run
# with an empty summary, which is how the first version of this failed silently.
define summarize
	@if [ -n "$${GITHUB_STEP_SUMMARY:-}" ]; then \
	  { echo "### $(1)"; echo; echo '```'; cat "$(2)"; echo '```'; } >> "$$GITHUB_STEP_SUMMARY"; \
	  grep -qF "$(3)" "$$GITHUB_STEP_SUMMARY" || { echo "summary is missing its report: $(1)"; exit 1; }; \
	fi
endef

# Keyed on the dependency files, not on whether pytest happens to exist. An older
# checkout's environment can have pytest and lack ruff, or hold versions the
# current requirements no longer allow, and a check that then ran against stale
# packages while reporting setup succeeded is the exact false green this repo
# is about. Change requirements.txt or pyproject.toml and setup runs again.
setup: $(VENV)/.stamp

$(VENV)/bin/python:
	python3 -m venv $(VENV)

$(VENV)/.stamp: requirements.txt pyproject.toml $(VENV)/bin/python
	$(PY) -m ensurepip --upgrade >/dev/null 2>&1 || true
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements.txt
	$(PIP) install pytest pytest-cov ruff
	$(PIP) check
	$(PY) -c 'import sys; print(sys.version)' > $@

setup-face: setup
	$(PIP) install "insightface>=0.7" "mediapipe>=0.10"

# CI runs exactly this target. An earlier version kept CI's steps as a separate list
# and claimed the two matched, and they did not: a different order and a missing check.
check: setup ffmpeg pipcheck imports derive selftests certify lint test figures dry replay

# Installed state is verified on every run, not only at install time. A stamp
# proves the dependency files were read once; it cannot see a package removed or
# pinned by hand since, and pip's own resolver check can.
pipcheck: setup
	$(PIP) check

# Every probe and gate has to import on a bare install, face extra or not. This is how
# Pillow was caught missing from requirements.txt while eight files imported it.
imports: setup
	@for f in probes/*.py gates/*.py; do \
	  $(PY) -c "import importlib.util,sys; s=importlib.util.spec_from_file_location('p','$$f'); m=importlib.util.module_from_spec(s); s.loader.exec_module(m)" \
	    || { echo "FAILED TO IMPORT: $$f"; exit 1; }; \
	done; echo "all probes and gates import"

selftests:
	bash gates/script_match.sh --selftest
	bash guards/prop_gate.sh selftest

ffmpeg:
	@command -v ffmpeg >/dev/null && command -v ffprobe >/dev/null \
	  || { echo "ffmpeg and ffprobe must be on PATH"; exit 1; }

# COVERAGE_PROCESS_START is what makes the number honest. The gates and probes are run
# as subprocesses by their tests, and without it every one of them reads 0% while being
# exercised: 27% against the real figure.
test: setup
	@mkdir -p $(OUT)
	set -o pipefail; COVERAGE_PROCESS_START=$(CURDIR)/pyproject.toml $(PY) -m pytest tests/ -q --cov --cov-report=term | tee $(OUT)/test.txt
	$(call summarize,Tests and coverage,$(OUT)/test.txt,TOTAL)
	$(PY) -m coverage report --fail-under=50 >/dev/null

derive: setup
	@mkdir -p $(OUT)
	set -o pipefail; $(PY) evals/derive.py | tee $(OUT)/derive.txt
	$(call summarize,Threshold calibration,$(OUT)/derive.txt,NAMED gating thresholds)

certify: setup
	@mkdir -p $(OUT)
	set -o pipefail; $(PY) evals/certify.py | tee $(OUT)/certify.txt
	$(call summarize,Instrument certificate,$(OUT)/certify.txt,TRACKS slope)

lint: setup
	$(VENV)/bin/ruff check .

figures: setup
	$(PY) tools/render_map.py --check
	$(PY) tools/render_tiers.py --check

# One committed spot through the graph. The board gate runs for real, the run records
# the requests a live run would send and what they would cost, then stops, with no keys.
dry: setup
	@mkdir -p $(OUT)
	set -o pipefail; $(PY) -m pipeline.run --board shoots/graph-zai-chain/boards.json --spot zai --mode dry \
	  --run-dir $(OUT)/dry-$$(date +%s) | tee $(OUT)/dry.txt
	@grep -q "outcome: dry: stopped before the first spend" $(OUT)/dry.txt
	$(call summarize,Dry run through the graph,$(OUT)/dry.txt,outcome: dry)

replay: setup
	@mkdir -p $(OUT)
	set -o pipefail; $(PY) -m pipeline.replay | tee $(OUT)/replay.txt
	$(call summarize,August ledgers against the graph,$(OUT)/replay.txt,Transitions on the record)

hooks:
	git config core.hooksPath .githooks && chmod +x .githooks/pre-commit .githooks/commit-msg
	@echo "pre-commit PII gate installed for this clone"

clean:
	rm -rf $(VENV) $(OUT) .coverage .coverage.* .pytest_cache
