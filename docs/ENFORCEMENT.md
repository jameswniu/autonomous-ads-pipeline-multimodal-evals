# Enforcement

**Plain version:** Rules were written telling the AI what not to do. Then whether it followed them was measured. It mostly did, but only because code was stopping it, not because the rules worked.

The code in [`../guards/`](../guards/) is what actually runs.

---

## The measurement

An unattended run calls a metered API. The prompt driving it carries numbered hard constraints, written in the strongest form available: capitalized, numbered, each with a dated story explaining what it cost last time it was violated.

Across 15 governed runs:

| | |
|---|---|
| Runs that ended with exactly one paid render | **14 of 15** |
| Runs that *attempted* exactly one paid render | **6 of 15** |
| Runs where a pre-call hook rejected the first attempt | **8** |
| Distinct runs the hook fired in | **9** |

The first number is what a dashboard shows. The second is what the model actually did. The gap between them is a piece of code.

Stated as a rate: prompt-level constraints held about 40% of the time; the runtime guard brought effective compliance to 93%.

## The natural experiment

One run carried four constraints written in identical form, to the same model, in the same context. Two held and two did not.

| constraint | mechanism behind it | held |
|---|---|---|
| refresh the pin allowlist before rendering | none, prompt only | yes |
| exactly one render call | prompt plus a pre-call hook | yes |
| at most two look generations | none, prompt only | **no, fired 3** |
| poll inline rather than yielding | none, prompt only | **no, turns rose** |

The two that held were not better written. The one that failed most expensively named the exact prior incident it was preventing.

What separates them is **failure visibility**. The render constraint had a hook, so a violation was blocked and loud. The pin-refresh constraint happened to be load-bearing for the very next call, so skipping it failed immediately and taught the model inside the same run. The other two fail silently and only cost money, so nothing forced compliance.

**The rule that falls out:** rank constraints by what happens when they are violated, not by how important they feel. A constraint whose violation is silent needs a mechanism. A constraint whose violation blocks the next step is comparatively safe to leave in prose.

---

## The guards, and what they do when their dependencies are gone

Four guards protect this pipeline. Each one was fed deliberately broken input to see what it would do.

| guard | file | blocks | on a missing dependency |
|---|---|---|---|
| identity pin | `block_unpinned_identity.sh` | any render whose voice or avatar id is not the pinned one | **fails open**, accidentally, when its pin file is absent and when `jq` is absent |
| pre-spend shim | `pre_render_sanity.sh` | nothing itself; locates and execs the prop gate before any paid render | **fails open, on purpose**, and says so in its own header |
| prop gate | `prop_gate.sh` | an implausible generated look, before credits burn | **fails open**, accidentally, on empty prompt, empty id, or a missing field |
| ship gate | `ship_gate.sh` | an output that fails the pre-ship checks | **fails closed**, exit 64 on unreadable input |

Three of the four approve everything when a single file goes missing. **Two of those three do not know they are doing it.**

That distinction is the finding, surfaced only by reading all four rather than counting them. The shim fails open as a deliberate trade: it is three lines, it owns no logic, and a host shim that started deciding things would become a second, divergent implementation of the gate. Two gates that disagree are worse than one gate that is sometimes absent, because you can no longer tell which one made a given call. That reasoning is written in the file, next to the behaviour it justifies, which is what makes it a decision rather than a bug.

The other two have no such note. They behave identically at runtime and differ only in whether anyone chose it.

The ship gate is the one exception, and only because of an incident: it once ran against paths that did not exist, and every check inside it defaulted to clean. It was rewritten to refuse. The other guards have not had their incident yet.

**A guard that fails open is not a guard, it is a log line.** The dangerous property is not that it fails, it is that it looks identical to passing. A deliberate fail-open with the reasoning attached is a design. An undocumented one is the same code with nobody accountable for it.

## Coverage is a separate question from correctness

The identity pin was correct: it read the right file, compared the right field, and refused the right values. It was also only enforced on one of two ways out.

It matched on the SDK tool name, so a raw HTTP call carrying the same id was never inspected. The voice pin scanned any payload and had full coverage; the avatar pin had one path. Same guard, same file, two different coverage levels, and nothing in the code said so.

The fix keys on the field in any payload aimed at the vendor host rather than on the tool name, and it is scoped to the `avatar_id` field specifically so that an unrelated 32-character id cannot trip it.

While testing the fix, **the guard blocked the test harness itself**, because the test string looked like a real call. That is worth more than the fix: a registered-but-inert hook cannot produce an unintended true positive. It only blocks what you aim at it. Firing on a payload nobody enumerated is the guard proving it is live.

---

## What this does not claim

The compliance numbers come from 15 runs. That is a tally, not a reliability estimate, and it should not be read as a rate that would hold at scale.

The fail-open findings come from synthetic payloads, not from production incidents. Three of the four guards have never actually lost their dependency in a real run. What is measured is what they *would* do.
