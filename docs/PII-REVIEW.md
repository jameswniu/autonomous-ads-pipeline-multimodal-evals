# Pre-publish PII review

This repository was assembled from a private working tree. Publication is irreversible, so it went through a two-layer gate before the first commit. This file is the record: what each layer found, what was changed, and which findings were dismissed and why.

The dismissals are the point of writing this down. A gate whose false alarms get silently waved through is not a gate, and "we ran a scanner" is not evidence of anything if nobody can see what the scanner said.

---

## The two layers

| | catches | how it fails |
|---|---|---|
| `tools/pii_scan.sh` | shapes: keys, hosts, hex ids, clock times, name tokens | cheap, deterministic, blind to anything without a shape |
| `tools/pii_llm_review.sh` | meaning: a third party in prose, a routine, a quoted private message | slow, costs a call, over-flags |

Both run in `.githooks/pre-commit`. Only the deterministic layer runs in CI, for the reason given in `.github/workflows/pii-scan.yml`.

**Requiring an armed scanner in CI is opt-in.** Arming it means putting `tools/pii_context.txt` and `tools/pii_names.txt` into this repository's Actions secrets, and those two hold real third-party names, so with a finding message quoting whatever it matched, one of those names ends up in a public workflow log sooner or later. Commit `tools/pii_ci_armed` and the armed context check turns on, so a publication branch with the secrets missing goes red exactly as before. Leave the marker out and that check reports skipped instead, and the run prints which classes did not run in CI and says that all seven are enforced locally by the pre-commit hook.

## What the deterministic layer found

125 findings on the first pass, 38 of them blocking. All were fixed or deliberately suppressed. It now exits 0 with 4 suppressions and **0 skipped checks**.

Two things worth recording:

**It had a bug that let real content through.** The owner-identity pattern is derived at runtime and was matched case-sensitively, so a comment shouting a name in capitals scored zero findings while the same name in ordinary case was caught on the adjacent line. Fixed by giving `run_rule` an optional flags argument and passing `-i` for that rule only. Case-insensitivity is wrong for the hex and key rules, so it is opt-in rather than global.

**A suppression hid a real finding.** Wall-clock times in the README were allowlisted on the reasoning that they described the system's schedule rather than a person's. That was true of most of them and false of the one that mattered: a sentence pairing a specific time with "while you are asleep", which is a presence claim. The judgement layer caught it after the deterministic gate had already gone green. The sentence was rewritten and the suppression narrowed, so any future clock time in the README fails again. <!-- pii-allow: this paragraph quotes the flagged phrase in order to document it; line-scoped and visible in the diff -->

## What the judgement layer found

**Pass 1: 11 of 11 chunks flagged.** Two classes were real and neither had a shape the deterministic layer could ever have matched:

- **Persona handles.** Two-letter identifiers for the generated character appeared throughout the guards and probes, alongside references to the private hook and lock files that manage her identity pins. The README states the character is generated and not a likeness; the code then linked her to a private toolchain by name. A two-character token cannot be matched by a generic rule without matching half the English language. Removed.
- **Private tooling filenames** referring to scripts that are not in this repository, which were both a layout disclosure and dead references for any reader. Parameterized or renamed.

Both classes were then written into the local rule file, so the cheap layer catches them for free from now on. That is the intended direction: the expensive reader finds a new class, the cheap matcher inherits it.

**Pass 2: 12 of 12 chunks flagged.** Two real items survived, both single lines:

- a reference to an issue-tracker hook from unrelated professional work, which is the one genuine workplace trace in the repo
- one uppercase pronoun the earlier rewrite missed, because that pass matched lowercase only

Both were fixed before the first commit, and the sleep-schedule phrase quoted above no longer appears anywhere in the tree (verified by the deterministic scan, which now fails on any README clock time).

Everything else on pass 2 was a false alarm, and the reviewer was clearly saturating.

## Dismissed, with reasons

Dismissed by hand, per the instruction in the reviewer's own output. Not by loosening its prompt.

| flagged as | actual | verdict |
|---|---|---|
| "internal project codename `avatar_iii` / `avatar_iv`" | published vendor engine version strings | dismissed |
| "internal tool name `ship_gate`" | a file in this repository, visible to the reader | dismissed |
| "internal project name: twin video pipeline" | this repository's own subject | dismissed |
| "hardware inventory: Apple Silicon, specific GPU architecture, display device" | product categories, not an inventory of owned hardware | dismissed |
| "scene and take names: smooth-beach, human-bakery, calm wave" | labels for generated video content, not real venues | dismissed |
| "reference to a specific female subject" | the generated character, disclosed as generated in the README | dismissed |
| "author's full name" | the byline on a portfolio repository, deliberate | dismissed |
| "verbatim quotation of private feedback" | self-quoted words, in the author's own repository | dismissed |
| "personal account usage and cost" | the author's own vendor spend, published deliberately as round dollars and a credit usage count in the cost table, with no account identifiers, plan names or remaining balances | dismissed |
| "internal incident history" | the documented reasoning behind each threshold, which is the artifact | dismissed |
| "reference to an unnamed second private repository" (raised twice, once per companion project) | both are credited on purpose and named nowhere; the withheld name is the published decision, so there is no identifier present to leak | dismissed |
| "describes a consent-gate workflow requiring a two-minute training video of a real person" | describes the gate and the footage it requires, and identifies nobody; documenting that the gate exists, and that no agent may clear it, is the entire point of mentioning it | dismissed |

The last one is the interesting dismissal. A reviewer tuned for confidentiality reads "here is the incident that produced this number" as a leak. In a repository whose entire claim is that thresholds were derived rather than typed, deleting the derivations would leave the numbers unfalsifiable. The incidents stay.

## The redesign, same day

The saturating reviewer described above was rebuilt rather than demoted, and the rebuild was calibrated before it was trusted. The full ablation is preserved because most of it is a record of being wrong in public:

| change | recall on a seeded corpus of known-real classes |
|---|---|
| original chunk-verdict tool | caught everything, buried in ~90% noise |
| per-finding redesign, dismissed classes listed in the prompt | **1 of 7, exit 0: would have published a named attorney** |
| dismissals removed from prompt, recall mandate added | still 1 of 7 |
| same prompt, stronger reviewer | still 1 |
| **parser bug fixed** | **7 of 7, exit 1, two high/high blocks** |

The failures were never the models. A `head -1` in the extraction code kept each reviewer's first finding and silently discarded the rest, which made three different models all appear to return exactly one finding, and produced a confident and entirely wrong paragraph about model tiers. The lesson this repo keeps re-learning: count what the system actually did, not what the summary shows.

Two rules survived the ablation and are now written into the tool:

- **Recall lives in the prompt, precision lives in the post-filter.** Listing human-dismissed classes in the prompt taught the reviewer to ignore adjacent real findings. The ledger (`tools/pii_review_ledger.txt`, tracked, reasoned, tab-separated) is applied only after the model answers and is never shown to it.
- **A per-call-billed privacy gate prices itself out of use.** The reviewer seat runs on the operator's flat-rate subscription (`tools/reviewers/claude_cli.sh`), because a gate with a marginal cost per run is a gate you learn to skip.

Calibrated result on this tree: 14 chunks, 0 blockers, 5 low-severity advisories, 3 findings absorbed by the ledger, 0 unavailable. The gate blocks only on a high-severity, high-confidence finding that survives the ledger, and the first thing the calibrated reviewer caught was this repo's own tooling: the gitignored roster of third-party names sat one `.gitignore` line away from publication, with nothing asserting that line held. The deterministic scanner now blocks if that wall ever falls.

## Honest limits

At sufficient caution every specific technical detail reads as internal, so the reviewer still over-reads at the advisory tier; advisories are deliberately cheap to emit and cost one line of human reading each. The blocking tier is the calibrated one.

The deterministic layer is the gate. It is the one wired to block a commit, and the one that must stay at zero.

**The media branch is scanned by hand.** The spots on the README live on the `archive-media` branch, which carries no hooks and no CI. Every file there was written with its container metadata stripped and then checked with the same tag list the deterministic scanner uses, and the check printed nothing, before it was committed.

**What none of this covers:** the roster used for third-party name matching only contains names that were enrolled in it. Anyone unenrolled has no coverage from that check at all, which is why the judgement layer exists and why the highest-risk source files were excluded from this repository entirely rather than redacted. Redaction assumes you can enumerate what to remove.
