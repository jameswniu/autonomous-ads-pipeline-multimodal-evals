# Kill Gate

```
python3 test_gate.py                    # eleven guardrails, from ties-by-name to one JSON object per judge reply
python3 eval/run.py                     # headline: uniform, gate, pick, oracle on the Aug 24 cohort
python3 eval/run.py --cohort all        # sensitivity check with the 8 second-shoot renders added
python3 eval/run.py --judge gpt         # a second vendor as the judge, for contrast
python3 eval/facts.py                   # every other number quoted below, from results/
python3 judge.py path/to/render.mp4     # score one render, 20 lean calls, ready for gate.py
python3 gate.py < scores.json           # stdin scores in, kill and ship out (RUNSHEET.md has a one-liner)
```

## What I found
- **People barely agree.** Among raters who picked a side, two strangers shown the same two ads pick the same one 53% of the time. 450 votes, 90 raters, 34 pairs, two Prolific studies.
- **Pairwise judging is broken.** Shown A and B in one call, Claude and GPT each picked B on 28 of 34 pairs, 82%. Moving the rubric after the frames took Claude from 81% to 78% on the same 32 pairs. Scoring one render at a time removed it.
- **Picking the best does not beat a coin here.** The judge's top render ships at 47.9% human preference.
- **Killing the worst does.** Drop the judge's lowest and what ships wins 53.9%, up 3.9 points, positive on every one of five briefs.
- **Craft is the axis with signal.** Its score tracks human value at r = 0.28 across 28 renders. Message is 0.07, warmth 0.13. The three summed match or beat every subset on the gate.
- **Averaging in a second judge did not help here.** GPT and Gemini, one call per render, produce 7 and 4 distinct totals across 28 and 26 renders. An equal-weight average of Claude's twenty calls with GPT's one leaves the kill gate at 53.9%, unchanged, and moves pick from 47.9% to 48.9%. That is one averaging rule on five briefs, not a verdict on panels.
- **A second vendor shows the same shape.** With GPT as the judge, kill closes 58% of the gap and pick lands at 44.4%.

## The gate (`gate.py`, stdlib only)
1. Score each render alone, 8 frames, three axes, 20 calls averaged. `judge.py` is the only file on the scoring path that touches a model. It runs bare now and takes a reply only when the whole text is one JSON object. The saved scores predate both, and `results/PROVENANCE.md` says what produced them.
2. Sum the axes. One number per render.
3. Kill the lowest. Ship the rest in the order they came.

Stateless. Refuses fewer than three renders, because killing one of two is picking. Refuses a score outside 1 to 10, a boolean, or a render named twice, because a broken reply must not become a decision. Ties break on the name.

## Result

| Cohort | Gap closed | Lift over uniform | Gate minus pick | Fair-coin null |
|---|---|---|---|---|
| Aug 24, 4 renders a brief | 86% | +3.9 [+1.8, +6.1] | +6.1 | `p = 0.0005` |
| All, 4 to 6 a brief | 57% | +1.9 [+1.0, +2.9] | +0.2 | `p = 0.03` |

Gap closed is (gate minus uniform) over (oracle minus uniform), where the oracle kills the render humans liked least. A render's human value is its mean probability of beating each render it was actually shown against, ties counting half. On both cohorts every brief's comparison graph is made of complete components, so uniform is exactly 50%. Brackets are an interval from the exhaustive bootstrap over the five briefs, all 3,125 resamples. A rater bootstrap gives a second interval and the fair-coin null gives the p, all printed by `eval/run.py`.

## Caveats
Five briefs. The kill gate was chosen after the pick gate failed on the same votes, so this is a second look at one dataset, not a pre-registered test, and the intervals and the null are conditional on that choice; none of them accounts for having made it. What the numbers do say is that, given the rule, the lift is positive on every brief, both intervals exclude zero and the null rejects. A sixth brief run cold is the real test. The second row is a sensitivity check, not a replication. The eight added renders each met one opponent, not three, so their values are not the same measurement, and the effect shrinks there partly because one kill out of six removes less than one out of four. `results/outside-review.md` is a second vendor's review of the working directory that preceded this repo; it caught a clip-to-vote join bug that had produced three previously reported significance claims for a best-pick router which is, correctly joined, below uniform.

## Skipped
A pre-generation router. Three different engines win the five briefs, by 8 to 18 points of human value, and the judge's craft axis at r = 0.28 does not rank four renders. A constant rule learned inside each fold, always seedance2, scores 58.6%; `eval/facts.py` prints it. Six single-call rubric variants from the ad-effectiveness literature are in `results/rubric_variants.jsonl`; the working-session comparison against a rater split is not scripted here either. A three-judge panel.

## Next day
Run the gate cold on a brief it has never seen. Then brief features, so a router has something to route on.
