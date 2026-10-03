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
    return sum((a - mx) * (b - my) for a, b in zip(x, y, strict=True)) / (sx * sy)


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
# The tail run repeats the pairwise prompt with the rubric moved after the video frames instead of
# before them, which is what "rubric after frames" means in the lines printed below.
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
# Scores go through load(), which refuses a repeated, lost or stray call.
S = defaultdict(lambda: defaultdict(list))
for c, xs in load("all", "claude")[2].items():
    for x in xs:
        for a in AXES:
            S[c][a].append(x[a])
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
            # "The gate" is gate.py's kill(): it drops the render with the lowest total, so
            # the bottom is the end it reads, the only place a tie can change what it kills.
            where = "BOTTOM, the gate's end" if abs(x - lo) < 1e-9 else ("top" if x == max(groups) else "middle")
            note.append(f"{'/'.join(sorted(names))} tie at {x:.1f} ({where})")
    print(f"  {b:10s} {'; '.join(note) if note else 'no ties'}")

print("\nWINNING ENGINE per brief, Aug 24, human value vs the other three")
for b, val in sorted(aug.items()):
    order = sorted(val.items(), key=lambda kv: -kv[1])
    (w, wv), (r_, rv) = order[0], order[1]
    def eng(c):
        return c.split("-")[-2]

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

def eng(c):
    return c.split("-")[-2]


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

print(f"\nPICKS among the four finished ads against people's votes, Aug 24, {len(votes24)} votes, human value of the engine picked per brief")
# A pick chooses one engine's ad per brief after all four ads exist, so it is a selection among finished ads and not a choice a router
# could make before rendering. The race ledger, races/races.jsonl, keeps two picks for these renders. computed_winner is the engine
# picked by the probe panel, the per-brief rows of pixel and audio probe readings in races/panels.json that tools/score_race.py
# scores, and the README calls that panel the router. recorded_winner is my pick by eye, which predates the panel's scores.
# The ledger writes heygen where the render names write a0. Human value is defined by values() in run.py.
ledger = [json.loads(line) for line in (ROOT.parent / "races" / "races.jsonl").read_text().splitlines()]
races = [r for r in ledger if r.get("shoot") == "ads2-rescore" and r.get("row_type") == "race"]
assert sorted(r["brief_id"] for r in races) == sorted(aug), "the ledger needs exactly one race row for each brief"
raced = {r["brief_id"]: r for r in races}
# The votes name each ad by its file, and a race row names the renders it scored by ledger id, so this checks both mean the same four files.
files = {r["id"]: r["master"].removesuffix(".mp4") for r in ledger if r.get("shoot") == "ads2-rescore" and r.get("row_type") == "render"}
for b in aug:
    assert {files[i] for i in raced[b]["render_ids"]} == set(aug[b]), b
render_name = {"heygen": "a0"}
by_pick = defaultdict(list)
matched = []
for b in sorted(aug):
    picked = {"panel": raced[b]["computed_winner"], "eye": raced[b]["recorded_winner"]}
    picked = {who: render_name.get(e, e) for who, e in picked.items()}
    engine_value = {eng(c): x for c, x in aug[b].items()}
    best = max(engine_value, key=engine_value.get)
    if picked["panel"] == best:
        matched.append(b)
    for who, e in picked.items():
        by_pick[who].append(engine_value[e])
    by_pick["always seedance2"].append(engine_value["seedance2"])
    by_pick["coin, the mean of the four"].append(statistics.mean(engine_value.values()))
    by_pick["people's best"].append(engine_value[best])
    cells = [f"{who} {picked[who]:10s} {100 * engine_value[picked[who]]:.1f}%" for who in ("panel", "eye")]
    print(f"  {b:10s} {'   '.join(cells)}   people's best {best:10s} {100 * engine_value[best]:.1f}%")
for who, xs in by_pick.items():
    print(f"  mean over the five briefs, {who}: {100 * statistics.mean(xs):.1f}%")
print(f"  the panel picked the engine people liked best on: {', '.join(matched) if matched else 'no brief'}")

print("\nCOUNTS")
variants = {json.loads(row)["variant"] for row in (R / "rubric_variants.jsonl").read_text().splitlines()}
studies = {v["study"] for v in votes}
print(f"  rubric variants besides the baseline: {len(variants - {'V0_baseline'})}")
print(f"  Prolific studies: {len(studies)}, raters: {len({v['rater'] for v in votes})}, votes: {len(votes)}")

print("\nOTHER JUDGES, one call each")
for j in ("gpt", "gemini"):
    T = {c: [sum(x[a] for a in AXES) for x in xs] for c, xs in load("all", j)[2].items()}
    tots = [statistics.mean(v) for v in T.values()]
    print(f"  {j:7s} {len(set(tots))} distinct totals across {len(tots)} renders, "
          f"{statistics.mean(len(v) for v in T.values()):.0f} call(s) per render")
