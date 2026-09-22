"""The three lines: what a coin does, what the gate does, what a cheater does.

Uniform ships a random render. The gate kills the judge's lowest and ships a random one of
the rest. The oracle knows the human votes and kills the render humans liked least. Gap
closed is (gate - uniform) / (oracle - uniform), the same score the hellyeah allocator uses.

The human value of a render is its mean probability of beating each other render of the
same brief that raters actually saw it against, with a no-preference vote counting half.
When each brief's comparison graph is made of complete components, uniform is exactly 50%
under that definition, and both cohorts here qualify. That condition is sufficient, not
necessary; some incomplete graphs also land on 50%, and no claim is made about those.

Two intervals and one null, because five briefs is very few clusters:
  brief bootstrap    all 3125 resamples of the five briefs, enumerated, not sampled.
                     An interval on the lift, not a test.
  rater bootstrap    4000 resamples of the 90 raters, each rater's votes kept together.
                     Also an interval.
  fair-coin null     4000 draws where every vote's winner is replaced by a fair coin
                     between the two renders shown. This destroys quality signal, and
                     it also destroys no-preference votes and within-rater dependence,
                     so it is a simple null, not a permutation of the observed outcomes.
Percentile bounds use the floor(p * n) index into the sorted resamples.

The hit rate scores the same kills as hit or miss. A hit is a kill on the render humans
liked least, so the oracle hits every brief by definition and a coin hits one in k. A miss
is a false positive and a false negative at once, the wrong render dies and the worst ships.
It is scored only where every render met every other, since otherwise the lowest value can
belong to a render that never faced the rest. Its p is the exact chance that a coin gets at
least that many hits. The rater resamples also report how often the oracle's own kill stays
the worst, which is how reliable the label is, and how often the gate's kill is the worst.

A voted render the chosen judge never scored would drop out of the candidate set on both
sides of every line, so by default a partial judge run refuses to print metrics at all.
--allow-missing prints them with the gap named in a WARNING line first.

Usage:  python3 eval/run.py [--cohort aug24|all] [--judge claude|gpt|gemini] [--allow-missing]
"""
from __future__ import annotations

import argparse
import csv
import itertools
import json
import random
import statistics
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from gate import AXES, kill  # noqa: E402

RESULTS = ROOT / "results"
BRIEFS = ["harbor", "lantern", "orchard", "quiet", "slowroad"]


def load(cohort: str, judge: str):
    pairs = {p["pair_id"]: p for p in json.loads((RESULTS / "pairs.json").read_text())}
    votes = [v for v in csv.DictReader((RESULTS / "votes.csv").open())]
    if cohort == "aug24":
        votes = [v for v in votes if pairs[v["pair_id"]]["shoot"] == "ads2-redo"]
    calls = defaultdict(list)
    for line in (RESULTS / "judge_scores.jsonl").read_text().splitlines():
        d = json.loads(line)
        if d["judge"] == judge:
            calls[d["clip"]].append({a: d[a] for a in AXES})
    return pairs, votes, calls


def clip(p, side):
    return p[side]["url"].rsplit("/", 1)[-1][:-4]


def values(pairs, votes):
    """brief -> {clip: human value}, only for briefs where every clip has an opponent."""
    pw = defaultdict(lambda: [0.0, 0])
    seen = defaultdict(set)
    for v in votes:
        p = pairs[v["pair_id"]]
        b = p["brief"]
        a, c = clip(p, "a"), clip(p, "b")
        seen[b].update((a, c))
        for x, y, eng in ((a, c, p["a"]["engine"]), (c, a, p["b"]["engine"])):
            pw[(b, x, y)][0] += 1 if v["winner"] == eng else (0.5 if not v["winner"] else 0)
            pw[(b, x, y)][1] += 1
    out = {}
    for b, clips in seen.items():
        val = {}
        for c in clips:
            opp = [pw[(b, c, o)][0] / pw[(b, c, o)][1] for o in clips if o != c and pw[(b, c, o)][1]]
            if opp:
                val[c] = statistics.mean(opp)
        if len(val) >= 3:
            out[b] = val
    return out


def lines(vals, calls):
    """Per brief: (uniform, gate, pick, oracle) human values."""
    out = {}
    for b, val in vals.items():
        # Only renders the judge scored take part, on both sides. A render with human votes
        # but no score would otherwise sit among the survivors untouched by the gate.
        val = {c: v for c, v in val.items() if calls.get(c)}
        scores = {c: calls[c] for c in val}
        if len(scores) < 3:
            continue
        dead = kill(scores)
        totals = {c: statistics.mean(sum(x[a] for a in AXES) for x in calls[c]) for c in scores}
        top = max(sorted(totals), key=totals.get)
        uni = statistics.mean(val.values())
        gate = statistics.mean(v for c, v in val.items() if c != dead)
        orc = statistics.mean(v for c, v in val.items() if c != min(val, key=val.get))
        out[b] = (uni, gate, val[top], orc)
    return out


def summary(pairs, votes, calls):
    L = lines(values(pairs, votes), calls)
    if not L:
        return None
    return tuple(statistics.mean(x[i] for x in L.values()) for i in range(4)), L


def met(pairs, votes):
    """brief -> the set of render pairs raters were actually shown."""
    out = defaultdict(set)
    for v in votes:
        p = pairs[v["pair_id"]]
        out[p["brief"]].add(frozenset((clip(p, "a"), clip(p, "b"))))
    return out


def kill_hits(vals, calls, meetings):
    """Per brief: (the kill landed on the render humans liked least, a coin's chance of that,
    the kill's rank from the bottom), or None where the scored renders did not all meet.

    Without a round robin the lowest value can belong to a render that never faced the rest,
    so "the render humans liked least" has no single answer there and no hit is scored.
    """
    out = {}
    for b, val in vals.items():
        val = {c: v for c, v in val.items() if calls.get(c)}
        if len(val) < 3:
            continue
        if any(frozenset(pr) not in meetings[b] for pr in itertools.combinations(val, 2)):
            out[b] = None
            continue
        dead = kill({c: calls[c] for c in val})
        lo = min(val.values())
        bottom = sum(1 for x in val.values() if x == lo)
        rank = 1 + sum(1 for x in val.values() if x < val[dead])
        out[b] = (val[dead] == lo, bottom / len(val), rank)
    return out


def at_least(ps, h):
    """Exact P(at least h successes) when trial i succeeds with probability ps[i]."""
    dist = [1.0]
    for p in ps:
        dist = [a * (1 - p) + b * p for a, b in zip(dist + [0.0], [0.0] + dist)]
    return sum(dist[h:])


ORDINAL = {2: "second", 3: "third", 4: "fourth", 5: "fifth", 6: "sixth"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cohort", default="aug24", choices=["aug24", "all"])
    ap.add_argument("--judge", default="claude")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--allow-missing", action="store_true",
                    help="print metrics even when a voted render has no score from this judge")
    a = ap.parse_args()
    random.seed(a.seed)
    pairs, votes, calls = load(a.cohort, a.judge)
    (uni, gate, pick, orc), per = summary(pairs, votes, calls)
    voted = {clip(pairs[v["pair_id"]], s) for v in votes for s in "ab"}
    unscored = sorted(voted - set(calls))
    # Calls are counted on this cohort's voted renders only; the file also holds calls on
    # renders outside the cohort, and those are not evidence for these lines.
    print(f"cohort {a.cohort}, judge {a.judge}: {len(votes)} votes, {len(per)} briefs, "
          f"{sum(len(calls[c]) for c in voted if c in calls)} judge calls on its renders, "
          f"{len(voted) - len(unscored)} of {len(voted)} voted renders scored")
    if unscored:
        print(f"  WARNING {len(unscored)} voted render(s) have no score from this judge and are "
              f"left out of every line below: {', '.join(unscored)}")
        if not a.allow_missing:
            # A partial run changes the candidate pool, and a metric on a changed pool can look
            # like the headline while measuring something else. Refuse unless asked.
            print("  refusing to report metrics on a partial judge run; pass --allow-missing to see them")
            sys.exit(1)
    print(f"  uniform {100 * uni:5.1f}%   what a coin ships")
    print(f"  gate    {100 * gate:5.1f}%   kill the judge's lowest, ship the rest    "
          f"gap closed {100 * (gate - uni) / (orc - uni):+.0f}%")
    print(f"  pick    {100 * pick:5.1f}%   ship the judge's highest, for contrast    "
          f"gap closed {100 * (pick - uni) / (orc - uni):+.0f}%")
    print(f"  oracle  {100 * orc:5.1f}%   kill the render humans liked least")
    print(f"  gate minus pick {100 * (gate - pick):+.1f} points, from the unrounded values")
    print("  per brief, gate minus uniform: " + " ".join(
        f"{b[:2]}{100 * (per[b][1] - per[b][0]):+.1f}" for b in BRIEFS if b in per))

    # Hit rate. The same kills scored hit or miss, so the oracle reads 100% by definition and a
    # coin one in k. A miss is a false positive and a false negative at once, the wrong render
    # dies and the worst one ships.
    vals0 = values(pairs, votes)
    H = kill_hits(vals0, calls, met(pairs, votes))
    rr = {b: h for b, h in H.items() if h is not None}
    if len(rr) < len(H):
        print(f"  hit rate         not reported, {len(H) - len(rr)} of {len(H)} briefs are not a round robin, "
              "so the render humans liked least there never met every other render")
    else:
        n_hit = sum(h[0] for h in rr.values())
        coin = [h[1] for h in rr.values()]
        print(f"  hit rate         gate {n_hit} of {len(rr)} = {100 * n_hit / len(rr):.0f}%   "
              f"coin {100 * statistics.mean(coin):.0f}%   oracle 100%   "
              f"P(coin gets at least {n_hit}) = {at_least(coin, n_hit):.2f}")
        misses = [f"{b} killed the {ORDINAL.get(h[2], str(h[2]))}-worst" for b, h in sorted(rr.items()) if not h[0]]
        print("  misses           " + (", ".join(misses) if misses else "none"))

    # Brief bootstrap: exhaustive. With five clusters there are 3125 resamples; enumerate.
    lift = {b: per[b][1] - per[b][0] for b in per}
    bs = sorted(statistics.mean(lift[b] for b in s) for s in itertools.product(list(per), repeat=len(per)))
    lo, hi = bs[int(0.025 * len(bs))], bs[int(0.975 * len(bs))]
    print(f"  brief bootstrap  ({len(bs)} resamples, exhaustive, interval)  lift {100 * statistics.mean(bs):+.1f}  "
          f"95% [{100 * lo:+.1f}, {100 * hi:+.1f}]  P(lift<=0) {sum(1 for x in bs if x <= 0) / len(bs):.4f}")

    # Rater bootstrap: each rater's votes travel together.
    byr = defaultdict(list)
    for v in votes:
        byr[v["rater"]].append(v)
    keys = list(byr)
    # The same resamples also ask how stable "the render humans liked least" is. The oracle's
    # kill is fixed from all the votes, so its share is the label's own reliability, and the
    # gate's share is its hit rate against resampled raters. Round-robin cohorts only.
    ref = {}
    if rr and len(rr) == len(H):
        for b in rr:
            val = {c: v for c, v in vals0[b].items() if calls.get(c)}
            ref[b] = (min(val, key=val.get), kill({c: calls[c] for c in val}), set(val))
    stab = defaultdict(lambda: [0, 0, 0])
    rs = []
    for _ in range(4000):
        samp = [v for k in (random.choice(keys) for _ in keys) for v in byr[k]]
        vb = values(pairs, samp)
        L = lines(vb, calls)
        if L:
            rs.append(statistics.mean(x[1] for x in L.values()) - statistics.mean(x[0] for x in L.values()))
        for b, (orc_kill, gate_kill, clips) in ref.items():
            vv = vb.get(b, {})
            if not clips <= set(vv):
                continue
            lo = min(vv[c] for c in clips)
            stab[b][0] += 1
            stab[b][1] += vv[orc_kill] == lo
            stab[b][2] += vv[gate_kill] == lo
    rs.sort()
    print(f"  rater bootstrap  (4000 resamples, {len(keys)} raters, interval)  lift {100 * statistics.mean(rs):+.1f}  "
          f"95% [{100 * rs[int(0.025 * len(rs))]:+.1f}, {100 * rs[int(0.975 * len(rs))]:+.1f}]  "
          f"P(lift<=0) {sum(1 for x in rs if x <= 0) / len(rs):.4f}")
    seen = [b for b in ref if stab[b][0]]
    if seen:
        o = statistics.mean(stab[b][1] / stab[b][0] for b in seen)
        g = statistics.mean(stab[b][2] / stab[b][0] for b in seen)
        print(f"  hit stability    (same resamples)  the oracle's kill is still the worst {100 * o:.1f}% of the time, "
              f"the gate's kill {100 * g:.1f}%")

    # The fair-coin null. Every winner is replaced by a coin between the two renders shown.
    base = gate - uni
    hits = 0
    for _ in range(4000):
        perm = [{**v, "winner": random.choice([pairs[v["pair_id"]]["a"]["engine"],
                                               pairs[v["pair_id"]]["b"]["engine"]])} for v in votes]
        s = summary(pairs, perm, calls)
        if s and s[0][1] - s[0][0] >= base:
            hits += 1
    print(f"  fair-coin null   (4000 draws)  p = {(hits + 1) / 4001:.4f}")


if __name__ == "__main__":
    main()
