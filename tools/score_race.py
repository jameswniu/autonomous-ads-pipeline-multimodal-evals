#!/usr/bin/env python3
"""Rank recorded numeric probe values offline. No rendering or vendor calls."""

import argparse
import copy
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def resolve_panel(catalog, brief_id):
    """Apply the documented audience overrides within a panel type."""
    brief = catalog["briefs"][brief_id]
    panel = copy.deepcopy(catalog["panels"][brief["panel_type"]])
    panel["panel_type"] = brief["panel_type"]
    for row in panel["rows"]:
        row.update(brief.get("row_overrides", {}).get(row["probe"], {}))
    return panel


def score_race(probe_values, panel):
    """Return winner and audit trail for {engine: {probe: numeric_value}}.

    Each engine tied for the best reading earns one full row, as in README.md:250,268.
    Most rows wins; compare the gate only among tied leaders. A remaining exact
    gate tie is unresolved (winner=None), because the sources give no third rule.
    Missing, nonnumeric or nonfinite values are errors, never free row wins.
    Bars are reporting context, not eligibility filters (README.md:230-231).
    """
    if len(probe_values) < 2:
        raise ValueError("a race needs at least two engines")
    if any(not isinstance(engine, str) or not engine for engine in probe_values):
        raise ValueError("engine identifiers must be nonempty strings")
    rows = panel["rows"]
    probes = [row["probe"] for row in rows]
    if not probes or len(set(probes)) != len(probes):
        raise ValueError("panel must have unique probe rows")
    if panel["gate"] not in probes:
        raise ValueError("gate must name a panel row")
    if any(row["direction"] not in ("up", "down") for row in rows):
        raise ValueError("probe direction must be up or down")

    engines = sorted(probe_values)
    for engine in engines:
        for probe in probes:
            value = probe_values[engine].get(probe)
            if (isinstance(value, bool) or not isinstance(value, (int, float))
                    or not math.isfinite(value)):
                raise ValueError(f"{engine}/{probe}: missing or nonfinite numeric score")

    wins = dict.fromkeys(engines, 0)
    row_winners = {}
    for row in rows:
        probe = row["probe"]
        best = (max if row["direction"] == "up" else min)(
            probe_values[engine][probe] for engine in engines)
        leaders = [engine for engine in engines if probe_values[engine][probe] == best]
        row_winners[probe] = leaders
        for engine in leaders:
            wins[engine] += 1

    leaders = [engine for engine in engines if wins[engine] == max(wins.values())]
    gate_winners = []
    decided_by = "row_count"
    finalists = leaders
    if len(leaders) > 1:
        gate = next(row for row in rows if row["probe"] == panel["gate"])
        best = (max if gate["direction"] == "up" else min)(
            probe_values[engine][gate["probe"]] for engine in leaders)
        gate_winners = [engine for engine in leaders
                        if probe_values[engine][gate["probe"]] == best]
        finalists = gate_winners
        decided_by = "gate" if len(finalists) == 1 else "unresolved_gate_tie"
    return {
        "winner": finalists[0] if len(finalists) == 1 else None,
        "row_wins": wins,
        "row_winners": row_winners,
        "tied_leaders": leaders if len(leaders) > 1 else [],
        "gate_winners": gate_winners,
        "decided_by": decided_by,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("values", type=Path, help="JSON object: engine -> probe -> number")
    parser.add_argument("--brief", required=True, help="brief id in the panel catalog")
    parser.add_argument("--panels", type=Path, default=ROOT / "races/panels.json")
    args = parser.parse_args(argv)
    try:
        catalog = json.loads(args.panels.read_text())
        result = score_race(json.loads(args.values.read_text()),
                            resolve_panel(catalog, args.brief))
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.exit(2, f"score_race: {exc}\n")
    print(json.dumps(result, indent=2, sort_keys=True, allow_nan=False))
    return 0 if result["winner"] is not None else 1


if __name__ == "__main__":
    raise SystemExit(main())
