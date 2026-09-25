#!/usr/bin/env python3
"""Recompute the gating thresholds from labelled exemplars, and say which are
actually derived and which were typed by hand.

The README claims taste was captured as labels and compiled into thresholds.
This file is that claim, executable. Three checks, in order of how much they can
embarrass the author:

  1. REPRODUCE. Every labelled row whose pixels ship in this repo is re-measured
     with the probe's OWN function, to about two decimals rather than exactly,
     because these metrics decode through ffmpeg and swscale is not identical
     across builds. A row that ships pixels for a probe with no
     recomputation function is a FAILURE, not a skip: silently not-checking is
     how a wrong label becomes the bracket edge with everything reporting green.

  2. BRACKET. Every gating constant must sit strictly inside the interval its own
     labels imply. Polarity matters and is declared per gate. A CEILING passes
     below itself, so it belongs between the worst pass and the best reject. A
     FLOOR passes above itself, so the interval runs the other way. Getting this
     wrong does not merely invert a comparison, it makes the assertion
     unsatisfiable, which then reads as "no labels yet" instead of "tool broken".

  3. SPLIT. Report DERIVED (backed by a labelled pass/reject pair on the same
     axis) against AUTHORED (not). Print the real count.

WHAT THIS DOES NOT COVER, because a tool that hides its own gaps is the thing
this repo is about. Several probes refuse clips using inline literals rather than
named constants: lipsync_probe's nine, and spasm_probe's `post.sum() < 0.30*fps`.
They cannot be bracketed until they are named, so they are absent from GATES and
absent from the denominator. The count below is therefore NOT "every way this
suite can refuse a clip". It is "every NAMED constant that can".

The bracket is also one sided by construction, so a TWO sided band does not fit
it. sync_probe accepts a lag between LAG_MIN and LAG_MAX, and neither edge alone
is the threshold; only LAG_MAX is scored here. Forcing the pair into a ceiling
would report a number that is arithmetically fine and means nothing.

Exit 0 all checks pass / 1 a check failed / 2 the labels could not be read.

    python3 evals/derive.py
    python3 evals/derive.py --json
"""
import csv
import glob
import hashlib
import json
import math
import os
import re
import sys
import types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LABELS = os.path.join(ROOT, "evals", "labels.csv")

CEILING = "ceiling"   # value <= C passes; rejects sit ABOVE the constant
FLOOR = "floor"       # value >= C passes; rejects sit BELOW the constant

# Each gate declares the AXIS it draws labels from. Two constants in one module
# are not the same axis just because they share a unit: mirror_probe's
# REPEAT_REJECT (a share of the unrelated-frame distance) and MIRROR_REJECT (a
# share of the matched-span control) are both shares and are unrelated, and
# matching on unit alone would let one label pair derive both.
#
# gating=False means the constant shapes a measurement but cannot by itself
# refuse a clip. Those are scored and printed, but kept out of the headline count.
#
# module,           constant,         axis,              polarity, scale, gating
GATES = [
    ("bg_detail",        "MAX_DETAIL",     "bg_gradient",     CEILING, 1.0,  True),
    ("scene_simplicity", "III_MAX",        "scene_gradient",  CEILING, 1.0,  True),
    ("eye_eval",         "BG_MAX",         "eye_gradient",    CEILING, 1.0,  True),
    ("level_probe",      "SCENE_MAX",      "scene_level",     CEILING, 1.0,  True),
    ("level_probe",      "FACE_MAX",       "face_level",      CEILING, 1.0,  True),
    ("level_probe",      "RELATION_MAX",   "relation_level",  CEILING, 1.0,  True),
    ("coherence_probe",  "REST_MIN",       "rest_fraction",   FLOOR,   1.0,  True),
    # Floors: a clip is refused for sitting BELOW these.
    ("mirror_probe",     "CONTROL_FLOOR",  "replay_signal",   FLOOR,   1.0,  True),
    ("mirror_probe",     "REPEAT_REJECT",  "repeat_distance", FLOOR,   1.0,  True),
    ("mirror_probe",     "MIRROR_REJECT",  "replay_distance", FLOOR,   1.0,  True),
    # Not a verdict threshold. sync_probe's LAG_MAX is documented as a DISCLOSURE that must
    # never refuse a clip ("Report the number, never let it refuse a clip"),
    # which guards/ship_gate.sh honours by catching its exit 1. Counting it as a
    # gate overstated the derived tally, so it is scored but not counted.
    ("sync_probe",       "LAG_MAX",        "mouth_lag_ms",    CEILING, 40.0, False),
    # gates/mouth_sync_probe.py, the lip-sync check that actually refuses a master. Its labels
    # are the verdicts recorded beside the shipped masters in shoots/*/landings.jsonl.
    # Only FAIL_CORR can refuse a master. PASS_CORR and PASS_LAG sort PASS from REVIEW, and
    # ad_gates.sh:49 lets every REVIEW through to the eye, so neither can stop a clip on its own.
    # They are scored here and kept out of the gating denominator, the same way LAG_MAX is.
    ("mouth_sync_probe", "FAIL_CORR",      "mouth_corr",      FLOOR,   1.0,  True),
    ("mouth_sync_probe", "PASS_CORR",      "mouth_corr",      FLOOR,   1.0,  False),
    ("mouth_sync_probe", "PASS_LAG",       "mouth_lag_abs_s", CEILING, 1.0,  False),
    # gates/jaw_gate.py, which refuses a closer before it enters a build. The number is the
    # latest dated ruling in the doctrine, and no labelled pass/reject pair on the jaw axis is
    # committed, so it counts AUTHORED until one is.
    ("jaw_gate",         "JAW_MAX",        "jaw_rubber",      CEILING, 1.0,  True),
    # gates/cast_gate.py, which refuses a scene whose person is not the presenter. The floor
    # sits halfway across a measured gap between strangers and her own takes, and no labelled
    # pair on the face axis is committed, so it counts AUTHORED until one is.
    ("cast_gate",        "CAST_MIN",       "face_similarity", FLOOR,   1.0,  True),
]

# Delivery targets rather than judgements. The build masters every spot to them, and the ship
# gate reads the result back. No grade could move a loudness target, so these are reported
# apart from the count above and never folded into it, which would flatter the DERIVED share
# or the AUTHORED one depending on where they were put.
SPECS = [
    ("loudness_gate", "TARGET_I",    "LUFS integrated, the loudnorm target every build masters to"),
    ("loudness_gate", "TOLERANCE_I", "LU either side of the target"),
    ("loudness_gate", "MAX_TP",      "dBTP, the loudnorm true-peak ceiling"),
]

# How to re-measure a labelled frame, per probe.
# Each takes (module, path, row). The row is passed because a measurement can
# need a parameter the label carries, such as a timestamp or which of two axes
# one call returns, even though none of the probes shipped here needs it yet.
RECOMPUTE = {
    "bg_detail": lambda m, path, row: m.detail(path),
    "scene_simplicity": lambda m, path, row: m.measure(path),
    "mirror_probe": lambda m, path, row: m.control(path),
}


# Checking a WITHHELD row, which is the hole a reviewer put a finger in on
# 2026-09-21. A row that ships no pixels cannot be re-measured, so on its own it
# is a number somebody typed, and nothing in CI would notice if it drifted or was
# nudged to make a threshold pass. For mouth_sync_probe it does not have to stay
# that way. Every one of these masters was gated when it shipped and the verdict
# was written into shoots/<shoot>/landings.jsonl, which IS committed, as
# "PASS corr 0.30 lag +0.08". That line is the record the label was read from, so
# the label is re-read from it on every run. Edit either one alone and this fails.
MOUTH = re.compile(r"(PASS|REVIEW|FAIL)\s+corr\s+(-?[\d.]+)\s+lag\s+([-+]?[\d.]+)")


def ledger_mouth():
    """{"<shoot>/<master>": {verdict, mouth_corr, mouth_lag_abs_s}} from the ledgers.

    Keyed by SHOOT and master, not master alone, and only a record whose kind is
    "gated master", which is the kind written when a gate passed judgement. Three
    ways this could otherwise be fooled, all raised by a reviewer on 2026-09-21
    and none of them hypothetical, since these ledgers already carry withdrawn
    and superseded entries: a second record for the same master quietly winning
    because it was read last, a withdrawn record standing in for the gated one,
    and a master of the same name in another shoot answering for this one. A
    duplicate is recorded as a conflict rather than resolved, because picking a
    winner is the failure.
    """
    found, seen = {}, {}
    for path in sorted(glob.glob(os.path.join(ROOT, "shoots", "*", "landings.jsonl"))):
        shoot = os.path.basename(os.path.dirname(path))
        for line in open(path):
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            hit = MOUTH.search(str(rec.get("mouth", "")))
            if not rec.get("master") or not hit or rec.get("kind") != "gated master":
                continue
            key = f"{shoot}/{rec['master']}"
            seen[key] = seen.get(key, 0) + 1
            found[key] = {
                "verdict": hit.group(1),
                "mouth_corr": float(hit.group(2)),
                "mouth_lag_abs_s": abs(float(hit.group(3))),
            }
    for key, n in seen.items():
        if n > 1:
            found[key] = {"conflict": n}
    return found


ATTESTED = {"mouth_sync_probe": ledger_mouth}


# The certificate feeds the bracket. evals/certify.py measures each lip-sync probe's
# RESOLUTION, the scatter left after fitting its readings against known doses, and a
# threshold that sits closer to a labelled edge than the instrument can resolve is not
# a threshold, it is noise with a number on it. So a time-axis constant has to clear
# each edge by K_SIGMA times that scatter.
#
# K_SIGMA is 2, which is a choice and not a measurement: two sigma is the usual
# distance at which two readings are called apart, and a bracket this suite has is
# rarely wide enough to afford three.
#
# Sigma is reported in milliseconds, so each time axis says how many of ITS units make
# one millisecond. An axis absent here gets no margin and the report says the constant
# is unmargined rather than implying it passed one.
K_SIGMA = 2.0
CERTIFICATE = os.path.join(ROOT, "evals", "certificates.json")
MS_PER_UNIT = {"mouth_lag_ms": 1.0, "mouth_lag_abs_s": 0.001}


def resolutions():
    """({probe: sigma in ms}, [problems]) from the committed certificate.

    A missing, truncated or unparseable certificate used to return an empty dict,
    which silently switched every margin off while the run still reported success.
    That is the shape of failure this whole file exists to refuse, so the problems
    come back beside the readings and the caller fails on them.
    """
    if not os.path.exists(CERTIFICATE):
        return {}, [f"no certificate at {os.path.relpath(CERTIFICATE, ROOT)}, so no "
                    f"threshold can be checked against the instrument's resolution"], []
    try:
        with open(CERTIFICATE) as fh:
            doc = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        return {}, [f"the certificate could not be read ({exc}), so every margin would "
                    f"have been skipped silently"], []

    found, problems, problems_note = {}, [], []
    entries = doc.get("certificates")
    if not isinstance(entries, list) or not entries:
        return {}, ["the certificate names no probes"], []
    for c in entries:
        probe = c.get("probe", "?")
        # A certificate is a claim about one version of one file. Edit the probe and a
        # committed receipt keeps saying TRACKS about code that no longer exists, and
        # the margin below comes from a number nothing measured. The hash is what makes
        # the receipt refuseable, including one hand-edited to TRACKS with sigma 0.
        src = os.path.join(ROOT, "probes", f"{probe}.py")
        stamped = c.get("source_sha256")
        if not stamped:
            problems.append(f"{probe} is certified with no source hash, so the receipt "
                            f"cannot be tied to the probe it describes")
            continue
        if not os.path.exists(src):
            problems.append(f"{probe} is certified but probes/{probe}.py is gone")
            continue
        with open(src, "rb") as fh:
            now = hashlib.sha256(fh.read()).hexdigest()
        if now != stamped:
            problems.append(f"{probe} changed since it was certified; rerun "
                            f"python3 evals/certify.py --write")
            continue
        # The ruler too. Hashing only the probe binds the receipt to the thing measured
        # and not to the thing measuring: the stimulus, the dosing and the fit all live
        # in certify.py and any of them can change while the probe is untouched.
        certifier = os.path.join(ROOT, "evals", "certify.py")
        with open(certifier, "rb") as fh:
            ruler = hashlib.sha256(fh.read()).hexdigest()
        if c.get("certifier_sha256") != ruler:
            problems.append(f"{probe} was certified by a different version of "
                            f"evals/certify.py; rerun python3 evals/certify.py --write")
            continue
        if c.get("verdict") != "TRACKS":
            problems.append(f"{probe} is certified {c.get('verdict', 'with no verdict')}, "
                            f"so its readings set no resolution")
            continue
        try:
            sigma = float(c["sigma_ms"])
        except (KeyError, TypeError, ValueError):
            problems.append(f"{probe} certifies TRACKS with no readable sigma_ms")
            continue
        if not math.isfinite(sigma) or sigma < 0:
            problems.append(f"{probe} reports sigma_ms {sigma}, which is not a resolution")
            continue
        if sigma == 0:
            # A scatter of exactly zero is not a perfect instrument, it is a reading
            # finer than the probe can report. sync_probe quantises its answer to the
            # dose grid, so it returns every dose exactly and its true resolution is
            # somewhere below one bin. Granting a zero margin from that would be a
            # check that passes by construction while reading as a check, so the probe
            # is left unmargined and the report says why.
            problems_note.append(
                f"{probe} reports no scatter at all, so its resolution is finer than it "
                f"can report and no margin can be derived from it")
            continue
        if probe in found:
            problems.append(f"{probe} is certified more than once, so there is no single "
                            f"resolution to margin against")
            continue
        found[probe] = sigma
    return found, problems, problems_note


def margin(module, axis, sigmas):
    """How far a constant on this axis must sit from an edge, in the axis's own unit."""
    if axis not in MS_PER_UNIT or module not in sigmas:
        return None
    return K_SIGMA * sigmas[module] * MS_PER_UNIT[axis]


# How closely a measurement can be expected to come back, and why it differs.
#
# Two kinds of measurement here, with genuinely different reproducibility:
#
#   FRAME 0 or a whole-image read. bg_detail and scene_simplicity decode one
#   frame from the start, or an image. Across macOS and the ubuntu runner these
#   land within 0.016, so a small absolute window holds them.
#
#   A WHOLE-CLIP decode at a fixed rate. mirror_probe resamples the stream to 10
#   frames a second and compares frames a third of the clip apart, so a build that
#   drops or duplicates a frame at the resample is measuring a slightly different
#   pair. Measured on the earlier fixtures: the control distance moved 545.5 to
#   539.6 (1.1%) between macOS and the ubuntu runner. That is not decode noise on
#   a pixel, it is a different frame, and no tolerance makes it exact. A 10% window
#   says what these rows actually promise, and a real threshold drift moves them
#   far further.
TOLERANCE = {
    "bg_detail": ("abs", 0.05),
    "scene_simplicity": ("abs", 0.05),
    "mirror_probe": ("rel", 0.10),
}


def tolerance(probe, label):
    kind, k = TOLERANCE.get(probe, ("abs", 0.05))
    return max(0.05, k * abs(label)) if kind == "rel" else k


def load_module(name):
    """Compile the probe from SOURCE, never from cached bytecode.

    spec_from_file_location + exec_module reads __pycache__, and its staleness
    check is (mtime, size). Change a constant to another value of the same length
    inside one filesystem-timestamp tick and Python serves the old bytecode. That
    happened while testing this file: it reported a threshold not in the source.
    A checker that can read a stale copy of what it checks is worse than none.
    """
    # probes/ first, then gates/. mouth_sync_probe is the only lip-sync check that BLOCKS a
    # master, and it lives in gates/, which this file could not reach until 2026-09-21. Its
    # constants were therefore in neither the derived count nor the denominator.
    path = os.path.join(ROOT, "probes", f"{name}.py")
    if not os.path.exists(path):
        path = os.path.join(ROOT, "gates", f"{name}.py")
    with open(path) as fh:
        src = fh.read()
    mod = types.ModuleType(f"_probe_{name}")
    mod.__file__ = path
    exec(compile(src, path, "exec"), mod.__dict__)
    return mod


def read_labels():
    with open(LABELS) as fh:
        body = [ln for ln in fh if not ln.lstrip().startswith("#")]
    rows = []
    for r in csv.DictReader(body):
        if not r.get("probe"):
            continue
        try:
            r["measured"] = float(r["measured"])
        except (TypeError, ValueError):
            raise ValueError(
                f"row {r.get('item')!r} has a non-numeric measured value "
                f"{r.get('measured')!r}") from None
        rows.append(r)
    return rows


def bracket(polarity, passes, rejects):
    """Orient the interval so the constant belongs strictly inside it."""
    if polarity == CEILING:
        return max(passes), min(rejects)
    return min(passes), max(rejects)


def inside(polarity, value, pass_edge, reject_edge):
    if polarity == CEILING:
        return pass_edge < value < reject_edge
    return reject_edge < value < pass_edge


def main():
    as_json = "--json" in sys.argv
    if not os.path.exists(LABELS):
        print(f"no labels at {LABELS}", file=sys.stderr)
        return 2
    try:
        rows = read_labels()
    except ValueError as exc:
        print(f"labels unreadable: {exc}", file=sys.stderr)
        return 2
    if not rows:
        print(f"{LABELS} parsed to zero rows", file=sys.stderr)
        return 2

    by_probe = {}
    for r in rows:
        by_probe.setdefault(r["probe"], []).append(r)

    # A row whose (probe, axis) matches no gate is not evidence, it is a typo
    # that looks like evidence. Dropping it quietly is the exact failure this
    # file exists to catch, so an unmatched label is a hard failure.
    known = {(m, a) for m, _c, a, _p, _s, _g in GATES}
    orphans = [f"{r['probe']}/{r['axis']} ({r['item']})"
               for r in rows if (r["probe"], r["axis"]) not in known]

    failures, repro, out, refuted_notes = [], [], [], []
    for o in sorted(set(orphans)):
        failures.append(f"label {o} matches no gate; check the probe and axis spelling")

    # --- 1. reproduce every row that ships pixels ------------------------
    for probe, rs in sorted(by_probe.items()):
        shipped = [r for r in rs if r["pixels"] != "withheld"]
        if not shipped:
            continue
        if probe not in RECOMPUTE:
            failures.append(
                f"{probe}: {len(shipped)} row(s) ship pixels but there is no "
                f"RECOMPUTE entry, so those labels are unverified")
            for r in shipped:
                repro.append({"item": r["item"], "ok": False, "why": "no recompute fn"})
            continue
        mod = load_module(probe)
        for r in shipped:
            path = os.path.join(ROOT, r["pixels"])
            if not os.path.exists(path):
                failures.append(f"{probe}: {r['pixels']} is listed but missing")
                repro.append({"item": r["item"], "ok": False, "why": "missing"})
                continue
            got = RECOMPUTE[probe](mod, path, r)
            # 0.05, not 0.02, and the number is measured rather than guessed.
            # These metrics decode through ffmpeg, and swscale is not identical
            # across builds: one labelled still read 3.035 on macOS and 3.051 on the
            # ubuntu runner. A 0.016 gap failed a 0.02 window, which is how this
            # was found.
            #
            # Pinning the scaler was tried and REJECTED. It does make the resample
            # deterministic, but it is a different filter, not a stabilised one:
            # the same frame moved 3.035 to 2.748. Every attested row in labels.csv
            # was measured with the default and its source render is gone, so
            # pinning would silently re-base the shipped rows against historical
            # numbers that can never be recomputed to match. A wider window keeps
            # every value on one footing.
            #
            # So "recomputable" here means to about two decimals, not bit exact. A
            # threshold drifting for real moves the value far more than 0.05.
            tol = tolerance(probe, r["measured"])
            ok = abs(got - r["measured"]) <= tol
            if not ok:
                failures.append(f"{probe}: {r['item']} recomputes {got:.2f}, "
                                f"label says {r['measured']:.2f}")
            repro.append({"item": r["item"], "label": r["measured"],
                          "recomputed": round(got, 3), "ok": ok})

    # --- 1b. a withheld row for an attested probe is checked against the ledger
    attested = []
    for probe, rs in sorted(by_probe.items()):
        if probe not in ATTESTED:
            continue
        recorded = ATTESTED[probe]()
        for r in [x for x in rs if x["pixels"] == "withheld"]:
            note = r.get("note", "") or ""
            cites = re.search(r"([\w.-]+)/landings\.jsonl", note)
            if not cites:
                # Fail closed. This probe's labels are attested BY a ledger, so a
                # withheld row that names none is a number with nothing behind it,
                # and skipping it is how the check quietly stops covering new rows.
                failures.append(
                    f"{probe}: {r['item']} ships no pixels and its note names no "
                    f"landing ledger, so nothing can check it")
                attested.append({"item": r["item"], "axis": r["axis"], "ok": False,
                                 "why": "no ledger cited"})
                continue
            key = f"{cites.group(1)}/{r['item']}"
            rec = recorded.get(key)
            if rec is None:
                failures.append(
                    f"{probe}: {r['item']} cites {cites.group(1)}/landings.jsonl but no "
                    f"gated master record there names it")
                attested.append({"item": key, "axis": r["axis"], "ok": False,
                                 "why": "no gated record in the ledger it cites"})
                continue
            if "conflict" in rec:
                failures.append(
                    f"{probe}: {key} has {rec['conflict']} gated master records, so "
                    f"there is no single recorded verdict to check against")
                attested.append({"item": key, "axis": r["axis"], "ok": False,
                                 "why": "duplicate ledger records"})
                continue
            if r["axis"] not in rec:
                continue
            ok = abs(rec[r["axis"]] - r["measured"]) < 1e-9
            if not ok:
                failures.append(
                    f"{probe}: {key} {r['axis']} is labelled {r['measured']} "
                    f"and the ledger records {rec[r['axis']]}")
            # The note names the verdict the probe gave. A REVIEW that a human
            # passed is the most load-bearing row in this file, so a note that
            # drifts from the record is caught here too.
            said = re.search(r"records (PASS|REVIEW|FAIL)", r.get("note", "") or "")
            if said and said.group(1) != rec["verdict"]:
                ok = False
                failures.append(
                    f"{probe}: {key} notes say the probe recorded "
                    f"{said.group(1)} and the ledger says {rec['verdict']}")
            attested.append({"item": key, "axis": r["axis"], "ok": ok,
                             "ledger": rec[r["axis"]], "label": r["measured"]})

    # --- 2 + 3. bracket and classify ------------------------------------
    sigmas, cert_problems, cert_notes = resolutions()
    failures.extend(cert_problems)
    excluded = {}
    for module, const, axis, polarity, scale, gating in GATES:
        mod = load_module(module)
        raw = getattr(mod, const, None)
        if raw is None:
            failures.append(f"{module}.{const} no longer exists")
            continue
        value = float(raw) * scale
        rs = [r for r in by_probe.get(module, []) if r["axis"] == axis]
        passes = [r["measured"] for r in rs if r["verdict"] == "pass"]
        rejects = [r["measured"] for r in rs if r["verdict"] == "reject"]
        other = [r for r in rs if r["verdict"] not in ("pass", "reject")]
        if other:
            excluded[f"{module}.{const}"] = [(r["item"], r["verdict"]) for r in other]

        rec = {"module": module, "constant": const, "axis": axis,
               "polarity": polarity, "value": float(raw),
               "compared_as": round(value, 3), "gating": gating,
               "n_pass": len(passes), "n_reject": len(rejects),
               "n_excluded": len(other)}

        if passes and rejects:
            pe, re_ = bracket(polarity, passes, rejects)
            rec.update(status="DERIVED", pass_edge=pe, reject_edge=re_)
            room = margin(module, axis, sigmas)
            rec["margin"] = room
            if room is not None:
                # Pull both edges inward by the margin, so a constant sitting closer to
                # one than the instrument can resolve is refused here rather than
                # enforced downstream as if it meant something.
                if polarity == CEILING:
                    tight_pass, tight_reject = pe + room, re_ - room
                else:
                    tight_pass, tight_reject = pe - room, re_ + room
                rec["margin_pass_edge"] = round(tight_pass, 4)
                rec["margin_reject_edge"] = round(tight_reject, 4)
                if inside(polarity, value, pe, re_) and not inside(
                        polarity, value, tight_pass, tight_reject):
                    rec["status"] = "REFUTED"
                    failures.append(
                        f"{module}.{const} = {value:g} sits inside its labelled interval "
                        f"but within {K_SIGMA:g} sigma ({room:g}) of an edge, which is "
                        f"closer than the probe can resolve")
            if not inside(polarity, value, pe, re_):
                rec["status"] = "REFUTED"
                failures.append(
                    f"{module}.{const} = {value:g} sits outside the interval its own "
                    f"labels imply ({polarity}: pass edge {pe:g}, reject edge {re_:g})")
        else:
            rec.update(status="AUTHORED", pass_edge=None, reject_edge=None)

        # A constant that REFUSES a clip the human passed is refuted by that fact alone, with or
        # without a reject on the other side. Requiring both edges hid exactly that: the blocking
        # probe's correlation floor sits above eight masters that shipped with the eye's approval
        # (2026-09-21).
        refused = [v for v in passes if (polarity == FLOOR and v < value) or (polarity == CEILING and v > value)]
        if refused:
            rec["status"] = "REFUTED"
            rec["refuses_passes"] = sorted(refused)
            worst = min(refused) if polarity == FLOOR else max(refused)
            line = (f"{module}.{const} = {value:g} refuses {len(refused)} labelled pass(es) "
                    f"({polarity}, worst {worst:g})")
            # A gating constant that refuses a labelled pass fails the build. One that cannot
            # refuse a clip on its own is reported just as loudly and does not, the same rule the
            # denominator already uses.
            (failures if gating else refuted_notes).append(line)
        out.append(rec)

    gates = [r for r in out if r["gating"]]
    # WHICH GATES THE CERTIFICATE ACTUALLY REACHES, which today is none of the blocking
    # ones, and saying so is the point. certify.py doses a synthetic clip whose motion
    # follows its own audio, so it can certify a probe that reads a LAG in time. It
    # cannot certify a correlation floor, and it cannot reach gates/mouth_sync_probe.py
    # at all, because that probe needs a face and the reference clip is a moving bar.
    # mouth_sync_probe is the check that refuses a master, so the most important gate
    # here is the one with no instrument certificate behind it. A reviewer should read
    # that from the tool, not discover it.
    coverage, off_axis = list(cert_notes), []
    for r in out:
        if r.get("margin") is not None:
            continue
        name = f"{r['module']}.{r['constant']}"
        if r["axis"] not in MS_PER_UNIT:
            if r["gating"]:
                off_axis.append(name)
        else:
            blocks = "BLOCKS a clip and " if r["gating"] else ""
            why = ("its certificate yields no usable resolution, see above"
                   if any(r["module"] in n for n in cert_notes)
                   else f"{r['module']} has no entry in the certificate")
            coverage.append(f"{name} is on a time axis, {blocks}has no margin: {why}")
    if off_axis:
        coverage.append(
            f"{len(off_axis)} blocking thresholds measure something other than time, so "
            f"the certificate cannot speak to them at all: {', '.join(off_axis)}")

    derived = [r for r in gates if r["status"] == "DERIVED"]
    authored = [r for r in gates if r["status"] == "AUTHORED"]
    refuted = [r for r in gates if r["status"] == "REFUTED"]

    specs = [{"module": m, "constant": c, "value": getattr(load_module(m), c), "what": w} for m, c, w in SPECS]

    if as_json:
        print(json.dumps({"gates": out, "reproduced": repro, "spec": specs,
                          "ledger_attested": attested,
                          "uncertified": coverage,
                          "derived": len(derived), "authored": len(authored),
                          "refuted": len(refuted), "n_gating": len(gates),
                          "excluded_rows": excluded, "failures": failures}, indent=2))
        return 1 if failures else 0

    if repro:
        print("REPRODUCED FROM SHIPPED PIXELS")
        for r in repro:
            mark = "ok" if r.get("ok") else "FAIL"
            if "recomputed" in r:
                print(f"  {mark:4s} {r['item']:36s} label {r['label']:>7.2f}   "
                      f"recomputed {r['recomputed']:>8.3f}")
            else:
                print(f"  {mark:4s} {r['item']:36s} {r.get('why', '')}")
        print()

    print(f"{'GATE':40s} {'VALUE':>8s} {'POLARITY':>9s}  "
          f"{'PASS EDGE':>9s} {'REJECT EDGE':>11s}  STATUS")
    for r in sorted(out, key=lambda x: (not x["gating"], x["status"], x["module"])):
        pe = f"{r['pass_edge']:.2f}" if r["pass_edge"] is not None else "-"
        re_ = f"{r['reject_edge']:.2f}" if r["reject_edge"] is not None else "-"
        tail = "" if r["gating"] else "  (not a gate)"
        print(f"{r['module'] + '.' + r['constant']:40s} {r['compared_as']:>8.2f} "
              f"{r['polarity']:>9s}  {pe:>9s} {re_:>11s}  {r['status']}{tail}")

    if coverage:
        print("\nWHAT THE CERTIFICATE DOES NOT REACH, named rather than left silent")
        for line in coverage:
            print(f"  {line}")

    margined = [r for r in out if r.get("margin") is not None]
    if margined:
        print("\nHEADROOM AGAINST THE CERTIFIED RESOLUTION "
              f"(a constant must clear each labelled edge by {K_SIGMA:g} sigma)")
        for r in margined:
            room = r["margin"]
            sigma_unit = room / K_SIGMA if K_SIGMA else 0.0
            near = min(abs(r["compared_as"] - r["pass_edge"]),
                       abs(r["compared_as"] - r["reject_edge"]))
            how = (f"{near / sigma_unit:.1f} sigma" if sigma_unit
                   else "no scatter to clear, the probe read every dose exactly")
            print(f"  {r['module'] + '.' + r['constant']:36s} nearest edge {near:g} away, {how}")

    if refuted_notes:
        print("\nREFUTED BY THEIR OWN LABELS, scored but unable to refuse a clip on their own")
        for line in refuted_notes:
            print(f"  {line}")

    if excluded:
        print("\nROWS EXCLUDED FROM A BRACKET (verdict neither pass nor reject)")
        for gate, items in excluded.items():
            for item, verdict in items:
                print(f"  {gate:40s} {item} -> {verdict}")

    print(f"\n{len(derived)} of {len(gates)} NAMED gating thresholds are DERIVED from a "
          f"labelled pass/reject pair on the same axis.")
    print(f"{len(authored)} are AUTHORED: typed by hand, no exemplar pair in "
          f"{os.path.relpath(LABELS, ROOT)}.")
    if refuted:
        print(f"{len(refuted)} are REFUTED by their own labels.")
    print(f"{len(out) - len(gates)} further constants are scored above but kept out of "
          f"that count because they cannot refuse a clip on their own.")
    print(f"{len(specs)} more are SPEC, delivery targets no grade could move: "
          + ", ".join(f"{x['module']}.{x['constant']} = {x['value']:g} ({x['what']})" for x in specs) + ".")

    n_live = sum(1 for r in rows if r["pixels"] != "withheld")
    n_ok = sum(1 for r in repro if r.get("ok"))
    n_att = sum(1 for a in attested if a.get("ok"))
    n_notes = len(rows) - n_live - len(attested)
    verb = ("were recomputed" if n_ok == n_live
            else f"ship pixels, {n_ok} of which recomputed")
    print(f"\n{n_live} of {len(rows)} labelled rows {verb}, and {n_att} more were "
          f"re-read from the committed landing ledger that recorded them.")
    print(f"The remaining {n_notes} are attested from the derivation notes; those "
          f"source renders are not retained.")

    if failures:
        print("\nFAILURES")
        for f in failures:
            print(f"  {f}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
