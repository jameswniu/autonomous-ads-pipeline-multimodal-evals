# The ad doctrine

Three rules decide what an ad puts on screen and in what order.

1. Hit all neurons.
2. Front-load impact.
3. Start with the hook.

A spot is one short ad film, its board is the written plan for it, and the cut is the film the build makes from the board. The pipeline that shoots a spot, a state machine in [`graph.py`](graph.py) that takes it from board to delivery, reads every board against these rules on every run. A live run spends nothing on a board that fails one, so no brief has to carry them.

Together they set the shape of the film. The most arresting shot opens it, impact stays dense early, slow beauty rides deep in the cut, and the product lands last, just before the closer, where the narrator speaks the brand line.

## 1. Hit all neurons

All four judgment rows below land at once, so the film hooks, convinces, surprises and pays off.

- The board carries scores for the four rows below from whoever read it, a person or a model, and a live run spends nothing until all four reach 2.
- The cut goes to a person after delivery, who keeps it or withdraws it and sends it back to the step that fixes it.

## 2. Front-load impact

The strongest beats come first, and the product stays out of the story until the payoff.

- The board keeps the brand out of every scene before the last, which the `product_absent` check reads.
- The board makes the middle beat worse instead of resolving it, which the `escalation` check reads.
- The cut is timed when its board places the switching sound where the picture changes most, `"switches": "cuts"`, and [`frontload_gate.py`](../gates/frontload_gate.py) flags its first big change to the eye when it lands later than that file's `FRONTLOAD_MAX`.

## 3. Start with the hook

The most arresting shot is the first one the film plays.

- The board names that scene in `hook`, and the `hook_first` check fails unless the film opens on it.
- A spot with no `hook` fails, and the reason names the scene to put there.

A spot can list its scenes in `order`, the order the film plays them, or in `chain`, the order they are shot in, each from the last frame of the one before. It can also give each sentence of the narration its own shots in `slots`. The film's first shot is the first of these the spot has.

1. The first entry of `order`.
2. The first entry of `chain`.
3. The first shot of the first slot.
4. The first scene key.

The build reads neither `order` nor `chain` for the cut. It plays each slot's shots in turn, or with no slots the first three scene keys, one to each sentence. So `hook_first` also fails an `order` that lists the shots any other way, and a `chain` that opens on any other shot, since the film would not play as the board says.

## The four judgment rows

[`board_probe.py`](../gates/board_probe.py) prints these questions for whoever reads the board to score from 0 to 3, worded exactly as below.

```
hook       something is wrong in the first second and you cannot look away
realism    the frame would pass as documentary footage with the sound off
absurdity  the BEHAVIOR is impossible, played completely straight, never the rendering
logic      the product closes the puzzle, obvious afterward and invisible before
```

A spot carries the answers beside its hook, with `scored_by` naming who scored them.

```json
"hook": "a",
"scores": {"hook": 3, "realism": 2, "absurdity": 3, "logic": 2},
"scored_by": "whoever read the board"
```

- A live run refuses the board until every row is a whole number from 0 to 3 and at least 2, and `scored_by` names someone. The reason goes on the ledger, the run's append-only record, and nothing is rendered.
- A dry run spends nothing, so it records on the ledger what the scores still lack and walks on.
- The thirteen mechanical checks pass or fail on their own, and the scores never change the probe's verdict or its exit code.

## One line of direction, and a budget

A scene is one line of direction. How the character looks rides in with the picture the engine is sent, her reference or the frame before, so the line only has to say what happens.

- The `scene_length` check fails a scene over 80 words, naming the scene and its count. Every scene on a board kept in this repo runs 64 words or fewer.
- A failed take gets a calmer prompt, never a longer one. A rule added to the board after a failed take makes the motion stiffer and the next take likelier to fail.
- A cut stops at its budget. Before any scene is sent, [`live.py`](live.py) adds its price to the prices of every request already on the run's ledger, from every pass and every re-entry, and a scene that would take the total past `RUN_BUDGET_USD`, $5.00 unless a person sets it higher, is not sent. The run stops at the render with the reason on the ledger.
