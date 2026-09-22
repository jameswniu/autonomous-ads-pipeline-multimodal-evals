# Run sheet

Run these yourself, cold, in a fresh terminal, before the call. `cd ~/ad-creative-pipeline-multimodal-evals` first. Nothing here calls a model; the judge scores are on disk in `results/`. The write-up GitHub shows on this branch is `.github/README.md`. The root `README.md` is the pipeline's own, byte-identical to main, because the pipeline's tests read their claims from it.

| # | Command | What its output proves |
|---|---|---|
| 1 | `python3 test_gate.py` | Eleven guardrails hold. Eleven `ok test_...` lines, nothing else |
| 2 | `python3 eval/run.py` | The headline. Header says `20 of 20 voted renders scored`, then `gate 53.9%`, `gap closed +86%`, `pick 47.9%` below a coin, and `gate minus pick +6.1`, then `hit rate` with the gate at 3 of 5 against a coin's 25% and the oracle's 100%, `P(coin gets at least 3) = 0.10`, and both misses on the second-worst |
| 3 | `python3 eval/run.py --cohort all` | The sensitivity check with the second shoot's eight renders added. `gate 51.9%`, `gap closed +57%`, every brief still positive. The hit rate reads `not reported`, since four of its briefs are not a round robin |
| 4 | `python3 eval/run.py --judge gemini` | A partial judge run refuses. A `WARNING` line names the two renders Gemini never scored, then `refusing to report metrics`, exit 1. Add `--allow-missing` and the same warning is followed by the lines, with `uniform` at 50.5% because those two are left out |
| 5 | `python3 eval/facts.py` | Every number the README quotes that command 2 does not print. Agreement 53.1%, position bias 28/34 for both vendors, craft r = +0.28, 7 then 23 distinct totals, the five winning engines with their margins, the Claude+GPT panel at the same 53.9%, the pairwise check that every brief's lowest win rate lost each head-to-head with the two misses at 53% and 61% against it, and the constant baseline at 58.6% |
| 6 | `echo '{"a":[{"craft":6,"message":5,"warmth":4}],"b":[{"craft":3,"message":3,"warmth":3}],"c":[{"craft":5,"message":5,"warmth":5}]}' \| python3 gate.py` | The protocol. Prints `{"kill": "b", "ship": ["a", "c"]}` |
| 7 | Same as 6 with `"craft":NaN` in render b | It refuses a broken reply. Prints `{"error": "score out of range 1.0 to 10.0: [nan]"}` and exits 1 |

To run one test on its own, `python3 test_gate.py tie` (substring match on the test name; a name that matches nothing exits 1). Command 2 takes about a minute; the 3,125 brief resamples are enumerated, and the rater bootstrap and the fair-coin null are 4,000 draws each.

## Break list

Do each one yourself, then undo it with `git checkout <file>`. Delete `__pycache__` between breaks; a stale cache once made command 1 fail on a correct source file.

| What to break | Where | What should happen |
|---|---|---|
| An expected value in a test | `test_gate.py:81`, change `== 13.0` to `== 14.0` | `test_more_calls_change_the_mean_not_the_rule` raises AssertionError, the eight tests before it still print `ok`, and the two after it never run because the runner stops at the first failure |
| The axes | `gate.py:40`, change to `AXES = ("craft",)` | `test_missing_axis_fails_loud` fails, because it asks for warmth and warmth is no longer an axis; the four before it pass. Measured: gate falls from 53.9% to 52.8%, gap closed +86% to +60%. Craft alone is the strongest axis and still loses to the three summed |
| The safety floor | `gate.py:44`, change `MIN_CLIPS = 3` to `1` | `test_refuses_fewer_than_three_renders` raises AssertionError with `accepted 1 renders`. The eval does not move, every brief has four, so the floor is there for the day one brief comes back with two |
| The twenty calls | Not a code edit. Filter `results/judge_scores.jsonl` to `"rep": 1` for Claude and run command 2 | Gate falls to 51.8%, gap closed +39%, and goes negative on harbor and quiet. Pick rises to 56.7%. No tie is behind that. On one call every brief has a single top score, and the one-call pick lands on a different render on two of five briefs, quiet and slowroad, both times on seedance2, which humans preferred there. Those two briefs are the whole rise, 8.9 points from the unrounded values (the printed 56.7 and 47.9 give 8.8). Two picks from one integer sample each is not a case for one call, and the same sample moves the gate down on two briefs. The constant is 20 for the gate, the rule this repo ships |
| A stated assumption | The brief's premise, nothing to edit | "What if you took the top of the same scores instead of the bottom?" Answer out loud in two sentences. Command 2 already prints it on the `pick` line, 47.9%, below the coin. Same scores, same judge, one selection rule swapped for the other, and the low end is the one that carries signal on this data |
