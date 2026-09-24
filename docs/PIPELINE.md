# How the pipeline became a graph

## What ran in August

An agent ran the shoots. I wrote a dated doctrine file, about four hundred lines of rules and the rulings behind them, and a Claude Code agent read it and drove the scripts in this repository from it, the boards, prompts, engine calls, the voice, the closer, the build, the gates and delivery. The gates that could block a call were Claude Code hooks, `guards/prop_gate.sh`, `guards/block_unpinned_identity.sh` and `guards/ship_gate.sh`. The agent wrote the ledgers under `shoots/` by hand. I reviewed every delivered cut and sent back the ones that were wrong, which the ledgers record as withdrawals.

## What the compile changed

Once the runs converged on one path, that path became a LangGraph, [`pipeline/graph.py`](../pipeline/graph.py).

The step order and the gates are edges and plain functions now, so the order is kept by code instead of by an agent remembering it, and delivery is unreachable without a ship-gate pass. The judgements no metric makes are two interrupts. The eye rules before anything ships, on a mouth REVIEW, a lag worth a nudge, a prop the edge probe saw cut by the frame, a scene that runs the wrong way, or a replay. An answer the graph cannot act on is asked again, not guessed at. The review comes after delivery, because that is where the ledgers show I looked. Every loop has a ceiling. The ledger is written by code, [`pipeline/ledger.py`](../pipeline/ledger.py), in one schema, [`pipeline/SCHEMA.md`](../pipeline/SCHEMA.md), with real request ids, times to the millisecond, and identity ids replaced by a hash. A live run checkpoints every step to SQLite, so it can wait days for a person and resume where it stopped, or be re-entered just before a step that failed on a defect since fixed, without paying again for the steps before it.

## How I know it matches

[`pipeline/replay.py`](../pipeline/replay.py) reads the seven August ledgers against the graph and counts only the moves a row states. Every one has an edge. Where history and the graph disagree, the replay prints it. Three REVIEWs shipped with no eye verdict on the record, and eighteen deliveries in the ads7 batch have no ship-gate pass. Four loops ran past a bound the graph now enforces, one scene re-rolled twice with no reason recorded and three spots each sent back twice for what a scene showed, four of those six send-backs naming no one. It also lists what the August rows never recorded, board verdicts, voice takes, build parameters, real request ids, which is what the graph writes on every run. `make replay` prints the whole report, and `tests/test_replay.py` pins it.

## The first spot through the graph

Z.ai, from the ads8 board, shot live with three Omni scenes, a fresh narration drawn three times and matched to its script, and the closer take reused from August, since the HeyGen REST API bills a wallet of its own, apart from the web plan's credits. It stopped five times on defects since fixed, and each stop is on its [ledger](../shoots/graph-zai/ledger.jsonl). The crop assumed 1080p scenes and Omni now returns 720p, two path bugs broke the build, the gates were handed captions away from the segments they measure, and the replay probe was pointed at the ten-second closer instead of the master. After each fix the run was re-entered from the checkpoint before the failing step, and nothing was paid for twice. The gates then passed, captions on five cues, the closer placed at 0 ms, the mouth at correlation 0.43, loudness at -16.1 LUFS.

A review of the code then found two things the run had got past. The ship gate had waived a replay it found at 20 seconds with nobody reading it, and the render had never shown anyone the two scenes its edge probe flagged. Both now go to the eye, and the run was re-entered for them at no cost, since every scene, the narration and the closer were already held. It is waiting at the eye for a person to look at those two scenes. After that the ship gate runs on the rebuilt master, and a replay it finds there goes to the eye as well.

## What is mine and what the agent did

I wrote the doctrine, chose every gate and probe and the threshold each one enforces, and graded the exemplars those thresholds are derived from. The agent ran the August shoots from that doctrine, drafted the boards and prompts, and kept the ledgers. The code here was written with Claude Code, under my direction and my review, and each change went through an adversarial review before it landed.

## What stays out

Look generation stays out, because it drives a web endpoint through a signed-in browser. The doctrine stays out, because it names identities and private paths, and so do the private delivery channel and the identity pins. Every file the code calls that is not in the repository is listed with its reason in [`tests/test_references.py`](../tests/test_references.py), and the test fails if a new one appears.
