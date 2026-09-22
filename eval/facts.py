"""Every number the README quotes that eval/run.py does not print, from the files in results/.

Usage:  python3 eval/facts.py
"""
from __future__ import annotations

import csv
import json
import math
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "eval"))
from gate import AXES, kill  # noqa: E402
from run import clip, lines, load, values  # noqa: E402

R = ROOT / "results"
pairs = {p["pair_id"]: p for p in json.loads((R / "pairs.json").read_text())}
votes = list(csv.DictReader((R / "votes.csv").open()))


def pearson(x, y):
    mx, my = statistics.mean(x), statistics.mean(y)
    sx = math.sqrt(sum((a - mx) ** 2 for a in x))
    sy = math.sqrt(sum((b - my) ** 2 for b in y))
    return sum((a - mx) * (b - my) for a, b in zip(x, y)) / (sx * sy)


print("AGREEMENT among raters, decisive votes only (no-preference votes excluded)")
by = defaultdict(list)
for v in votes:
    if v["winner"]:
        by[v["pair_id"]].append(v["winner"])
same = tot = 0
maj = n_dec = 0
for ws in by.values():
    n = len(ws)
    c = Counter(ws)
    maj += max(c.values())
    n_dec += n
    if n >= 2:
        same += sum(k * (k - 1) // 2 for k in c.values())
        tot += n * (n - 1) // 2
ties = sum(1 for v in votes if not v["winner"])
print(f"  two distinct raters pick the same render: {same}/{tot} = {100 * same / tot:.1f}%")
print(f"  the majority side of each pair, in-sample: {maj}/{n_dec} = {100 * maj / n_dec:.1f}%")
print(f"  no-preference votes excluded from both:    {ties} of {len(votes)}")

print("\nPOSITION BIAS in the pairwise runs, results/pairwise_verdicts.jsonl")
pv = defaultdict(list)
for line in (R / "pairwise_verdicts.jsonl").read_text().splitlines():
    d = json.loads(line)
    pv[(d["judge"], d["variant"])].append(d)
base = {}
for (j, var), rows in sorted(pv.items()):
    seen = defaultdict(set)
    for d in rows:
        seen[d["pair_id"]].add(d["pick"])
    conflicts = sum(1 for picks in seen.values() if len(picks) > 1)
    if conflicts:
        # A pair scored twice with two different picks has no single per-pair figure, and
        # keeping either call would make the count depend on file order. Not reported.
        print(f"  {j:7s} {var:5s} {len(seen)} distinct pairs, {conflicts} scored twice with conflicting picks. Not reported")
        continue
    b = sum(1 for picks in seen.values() if picks == {"B"})
    print(f"  {j:7s} {var:5s} picked B on {b}/{len(seen)} distinct pairs = {100 * b / len(seen):.0f}%")
    if var == "base":
        base[j] = {p: next(iter(picks)) for p, picks in seen.items()}
# Claude only. GPT's tail run scored 17 pairs twice with one conflicting pick, so a single
# per-pair figure for it would depend on which call is kept; it is not reported.
for j in ("claude",):
    if (j, "tail") in pv and j in base:
        # base[j] exists only when the base run had no conflicting duplicate; the tail run
        # gets the same check, or a pair scored twice would pick whichever call came last.
        tail = defaultdict(set)
        for d in pv[(j, "tail")]:
            tail[d["pair_id"]].add(d["pick"])
        if any(len(picks) > 1 for picks in tail.values()):
            print(f"  {j:7s} rubric after frames, a tail pair was scored twice with conflicting picks. Not reported")
            continue
        tail = {p: next(iter(picks)) for p, picks in tail.items()}
        common = sorted(set(tail) & set(base[j]))
        bb = sum(1 for p in common if base[j][p] == "B")
        bt = sum(1 for p in common if tail[p] == "B")
        print(f"  {j:7s} rubric after frames, same {len(common)} pairs: base {100 * bb / len(common):.0f}% "
              f"-> tail {100 * bt / len(common):.0f}%")

print("\nCORRELATION of each Claude axis with human value, all 28 renders, all votes")
S = defaultdict(lambda: defaultdict(list))
for line in (R / "judge_scores.jsonl").read_text().splitlines():
    d = json.loads(line)
    if d["judge"] == "claude":
        for a in AXES:
            S[d["clip"]][a].append(d[a])
vals = values(pairs, votes)
H = {c: v for b in vals for c, v in vals[b].items()}
clips = sorted(c for c in H if c in S)
for a in list(AXES) + ["sum"]:
    xs = [sum(statistics.mean(S[c][ax]) for ax in AXES) if a == "sum" else statistics.mean(S[c][a]) for c in clips]
    print(f"  {a:8s} r = {pearson(xs, [H[c] for c in clips]):+.2f}   n={len(clips)}")

print("\nSCORE RESOLUTION, Claude")
one = {c: sum(S[c][a][0] for a in AXES) for c in S}
mean = {c: sum(statistics.mean(S[c][a]) for a in AXES) for c in S}
print(f"  first call only:  {len(set(one.values()))} distinct totals across {len(one)} renders")
print(f"  20 calls averaged: {len(set(round(t, 6) for t in mean.values()))} distinct totals across {len(mean)} renders")
aug = values(pairs, [v for v in votes if pairs[v["pair_id"]]["shoot"] == "ads2-redo"])
for b, val in sorted(aug.items()):
    t = {c: mean[c] for c in val if c in mean}
    lo = min(t.values())
    groups = defaultdict(list)
    for c, x in t.items():
        groups[round(x, 6)].append(c.split("-")[-2])
    note = []
    for x, names in sorted(groups.items()):
        if len(names) > 1:
            where = "BOTTOM, the gate's end" if abs(x - lo) < 1e-9 else ("top" if x == max(groups) else "middle")
            note.append(f"{'/'.join(names)} tie at {x:.1f} ({where})")
    print(f"  {b:10s} {'; '.join(note) if note else 'no ties'}")

print("\nWINNING ENGINE per brief, Aug 24, human value vs the other three")
for b, val in sorted(aug.items()):
    order = sorted(val.items(), key=lambda kv: -kv[1])
    (w, wv), (r_, rv) = order[0], order[1]
    eng = lambda c: c.split("-")[-2]
    print(f"  {b:10s} {eng(w):10s} {100 * wv:.0f}%   runner-up {eng(r_):10s} {100 * rv:.0f}%   margin {100 * (wv - rv):.1f}")

print("\nPANEL, Claude and GPT axis means averaged per render, Aug 24")
pairs24, votes24, cc = load("aug24", "claude")
_, _, cg = load("aug24", "gpt")
panel = {}
for c in cc:
    if c in cg:
        m = {a: (statistics.mean(x[a] for x in cc[c]) + statistics.mean(x[a] for x in cg[c])) / 2 for a in AXES}
        panel[c] = [m]
Lp = lines(values(pairs24, votes24), panel)
Lc = lines(values(pairs24, votes24), cc)
gp = statistics.mean(x[1] for x in Lp.values())
pp = statistics.mean(x[2] for x in Lp.values())
gc = statistics.mean(x[1] for x in Lc.values())
pc = statistics.mean(x[2] for x in Lc.values())
print(f"  gate  claude alone {100 * gc:.1f}%   claude+gpt {100 * gp:.1f}%")
print(f"  pick  claude alone {100 * pc:.1f}%   claude+gpt {100 * pp:.1f}%")

print("\nPAIRWISE WORST, Aug 24, whether the lowest win rate also lost every head-to-head")
h2h = defaultdict(lambda: [0.0, 0])
for v in votes:
    p = pairs[v["pair_id"]]
    if p["shoot"] != "ads2-redo":
        continue
    a, c = clip(p, "a"), clip(p, "b")
    for x, y, e in ((a, c, p["a"]["engine"]), (c, a, p["b"]["engine"])):
        h2h[(x, y)][0] += 1 if v["winner"] == e else (0.5 if not v["winner"] else 0)
        h2h[(x, y)][1] += 1
for b, val in sorted(aug.items()):
    worst = min(val, key=val.get)
    lost = all(h2h[(worst, o)][0] < h2h[(worst, o)][1] / 2 for o in val if o != worst)
    dead = kill({c: cc[c] for c in val})
    line = f"  {b:10s} {eng(worst):10s} lowest win rate, {'lost every head-to-head' if lost else 'did NOT lose every head-to-head'}"
    if dead != worst:
        s, n = h2h[(dead, worst)]
        line += f", and the gate killed {eng(dead)}, which won {100 * s / n:.0f}% of their head-to-head votes against it"
    print(line)

print("\nCONSTANT BASELINE, pick the engine with the best mean human value on the other four briefs, Aug 24")
eng = lambda c: c.split("-")[-2]
tot = 0
picks = []
for b in sorted(aug):
    others = {bb: v for bb, v in aug.items() if bb != b}
    by_eng = defaultdict(list)
    for v in others.values():
        for c, x in v.items():
            by_eng[eng(c)].append(x)
    e = max(sorted(by_eng), key=lambda e: statistics.mean(by_eng[e]))
    picks.append(e)
    tot += next(x for c, x in aug[b].items() if eng(c) == e)
print(f"  folds picked {picks}, held-out human value {100 * tot / len(aug):.1f}%")

print("\nCOUNTS")
variants = {json.loads(l)["variant"] for l in (R / "rubric_variants.jsonl").read_text().splitlines()}
studies = {v["study"] for v in votes}
print(f"  rubric variants besides the baseline: {len(variants - {'V0_baseline'})}")
print(f"  Prolific studies: {len(studies)}, raters: {len({v['rater'] for v in votes})}, votes: {len(votes)}")

print("\nOTHER JUDGES, one call each")
for j in ("gpt", "gemini"):
    T = defaultdict(list)
    for line in (R / "judge_scores.jsonl").read_text().splitlines():
        d = json.loads(line)
        if d["judge"] == j:
            T[d["clip"]].append(sum(d[a] for a in AXES))
    tots = [statistics.mean(v) for v in T.values()]
    print(f"  {j:7s} {len(set(tots))} distinct totals across {len(tots)} renders, "
          f"{statistics.mean(len(v) for v in T.values()):.0f} call(s) per render")
