# One path in, for a person or an agent that has never seen this repository.
#
#   make setup    a virtualenv with exactly what CI installs
#   make check    everything CI runs, in the order CI runs it
#   make hooks    the pre-commit PII gate, once per clone
#
# ffmpeg and ffprobe are system binaries and have to be on PATH already.
# The two gates that locate a face need `make setup-face` on top; every test
# passes without them because their imports are lazy.

VENV   ?= .venv
PY     := $(VENV)/bin/python
PIP    := $(PY) -m pip
export PATH := $(CURDIR)/$(VENV)/bin:$(PATH)

.PHONY: setup setup-face check pipcheck imports selftests test derive certify lint figures ffmpeg hooks clean

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

# The same steps CI runs, in the order checks.yml runs them. A step missing here
# is a way for a local green to disagree with the Actions tab, and the first cut of
# this target left out three of them while its comment claimed parity.
check: setup ffmpeg pipcheck imports derive selftests certify lint test figures

# Installed state is verified on every run, not only at install time. A stamp
# proves the dependency files were read once; it cannot see a package removed or
# pinned by hand since, and pip's own resolver check can.
pipcheck: setup
	$(PIP) check

# Every probe and gate has to import on a bare install, face extra or not.
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

test: setup
	COVERAGE_PROCESS_START=$(CURDIR)/pyproject.toml $(PY) -m pytest tests/ -q --cov --cov-report=term
	$(PY) -m coverage report --fail-under=50 >/dev/null

derive: setup
	$(PY) evals/derive.py

certify: setup
	$(PY) evals/certify.py

lint: setup
	$(VENV)/bin/ruff check .

figures: setup
	$(PY) tools/render_map.py --check
	$(PY) tools/render_tiers.py --check

hooks:
	git config core.hooksPath .githooks && chmod +x .githooks/pre-commit .githooks/commit-msg
	@echo "pre-commit PII gate installed for this clone"

clean:
	rm -rf $(VENV) .coverage .coverage.* .pytest_cache
