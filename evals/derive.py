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
import json
import os
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
    path = os.path.join(ROOT, "probes", f"{name}.py")
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

    failures, repro, out = [], [], []
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

    # --- 2 + 3. bracket and classify ------------------------------------
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
            if not inside(polarity, value, pe, re_):
                rec["status"] = "REFUTED"
                failures.append(
                    f"{module}.{const} = {value:g} sits outside the interval its own "
                    f"labels imply ({polarity}: pass edge {pe:g}, reject edge {re_:g})")
        else:
            rec.update(status="AUTHORED", pass_edge=None, reject_edge=None)
        out.append(rec)

    gates = [r for r in out if r["gating"]]
    derived = [r for r in gates if r["status"] == "DERIVED"]
    authored = [r for r in gates if r["status"] == "AUTHORED"]
    refuted = [r for r in gates if r["status"] == "REFUTED"]

    if as_json:
        print(json.dumps({"gates": out, "reproduced": repro,
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

    n_live = sum(1 for r in rows if r["pixels"] != "withheld")
    n_ok = sum(1 for r in repro if r.get("ok"))
    verb = ("were recomputed" if n_ok == n_live
            else f"ship pixels, {n_ok} of which recomputed")
    print(f"\n{n_live} of {len(rows)} labelled rows {verb}. "
          f"The rest are attested from the derivation notes; those source renders are "
          f"not retained.")

    if failures:
        print("\nFAILURES")
        for f in failures:
            print(f"  {f}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
