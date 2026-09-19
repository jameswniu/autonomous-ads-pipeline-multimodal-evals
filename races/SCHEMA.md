# Race ledger schema

`races.jsonl` is an append-only JSON Lines ledger. Each physical line is one
complete JSON object. Existing lines are evidence and must not be rewritten;
the backfill only appends identities that are not already present and refuses a
changed row under an existing identity.

A cohort whose races are all on the ledger is not rebuilt at all. The backfill
reads the ledger it is about to append to, and skips such a cohort whole,
recording one omission that says committed rows are evidence and not a build
target. This is what lets the ledger grow a second time. Rows written earlier
pin the hashes their sources had at their own commit, so rebuilding them from a
later tree would produce different content under the same identities, which the
append would then refuse. A cohort is built entirely or not at all, never in
part. A cohort is also skipped when the tree it is being built from no longer
carries the source it reads, which is how one checkout can rebuild an older
commit's rows and a newer commit's rows without the two colliding.

Every row has `schema_version`, currently `1`; `row_type`, either `render` or
`race`; and a stable `id`. `shoot` identifies the race cohort. `brief_id`
identifies the ad brief, `panel_type` selects a definition from `panels.json`,
and `panels_sha256` pins the exact panel catalog used by the backfill. `sources`
is a list of evidence references. Every recorded path is relative to this
repository's root. A repository reference has `path`, `line`, and the file's
SHA256 digest. An external source has only
`{"label": "external batch provenance, not tracked here"}`: no path, copied
excerpt, or personal identifiers are retained.

The backfill reads optional external batch evidence from
`RACE_BASELINE_PROVENANCE`, whose default is empty. When it is unset or the file
is unavailable, the backfill skips that source, keeps the same generic label,
and cites the public README for the batch cost. When configured, it extracts
only production quantities and the batch total; private prose and account
state are discarded. Existing ledger rows are never used as source evidence.

## Render rows

A render row records one engine's finished ad for one brief and race cohort.
Its identity is `render:<shoot>:<brief_id>:<engine>`. `render_shoot` names the
source shoot that produced the master when a race compares masters from two
shoot directories.

`audience` contains the board's audience text when that board has one, otherwise
it is null. `audience_source` cites that board or is null. `engine` is a stable
short identifier; `engine_name` is the recorded display name;
`engine_version` is the recorded version, or null when none was recorded; and
`engine_model` is the exact model route when the source records one.

`scene_count` counts story scenes, not the shared presenter closer. `scene_ids`
names them. `master` names the scored master when a master ledger records it.
`request_count` and `landed_scene_count` preserve available request and landing
facts. `media_duration_seconds`, when present, maps scene ids to output-media
durations. It is deliberately separate from `render_time_seconds`, which is
vendor latency and remains null when no latency was recorded.

`cost.amount` and `cost.unit` are reserved for a cost attributable to this
render. `cost.records` preserves broader evidence, such as a batch total, with
its `scope`, `basis`, and `source`; batch totals are not divided among briefs.

`probes` maps each panel probe id to a measurement. A measurement has `value`,
the numeric score or null; `file`, the probe implementation path; and `sha256`,
the SHA256 digest of that implementation at backfill time. Because the historical
execution did not record its code digest, `historical_execution_sha256` is
null and `hash_basis` says that the hash pins the repository snapshot instead.
`sources` cites the recorded numeric value. For saved probe output, that source
reference also pins the output file's SHA256 digest. `panel_score_value` retains the
hand transcription and `panel_score_agrees` says whether it equals the parsed
saved output; the parsed output is authoritative when both exist.

`notes` explains nulls, inheritance, and limitations rather than silently
inventing missing facts.

## The ads2-rescore cohort

`ads2-rescore` records the 2026-08-24 four-engine races scored again on
2026-09-19, from the masters as they shipped in the `media-2026-08` release. The
original `ads2-redo` cohort holds the same twenty renders and five races as they
were recorded at the time, four of them with no numeric scores at all, and those
rows are untouched evidence. The rescore is a separate identity for the same
comparison, measured rather than transcribed, so every race carries a computable
winner.

`master` on a rescore render row names the released file, `shoot-20260824-<tag>-<brief>.mp4`,
where the baseline's tag is its column name `a0` and the other three are their
engine ids. Its five probe outputs live in
[`shoots/ads2-redo/probe-outputs/`](../shoots/ads2-redo/probe-outputs/), one file
per probe per master, named after the master. Each measurement cites that file
and its SHA256 digest, and its `value` is parsed from it. There is no hand
transcription behind a rescore reading, so `panel_score_value` and
`panel_score_agrees` are absent rather than null, since a row cannot report
agreement with a number nobody wrote down.

`cost.records` is empty and `cost.amount` and `cost.unit` are null. These renders
were paid for once, in the original cohort, and a rescore of an existing file
buys nothing. Batch costs stay where they were recorded instead of being copied
onto a second row and counted twice.

`recorded_winner` is the hand call, read from the "Eye at the time" column of the
winners table in README.md, which is the source file that holds it. The WINNER
column beside it is the panel's answer, and `computed_winner` reproduces that
from the probe values. They agree on Orchard and Quiet and disagree on Lantern,
Harbor and Slow Road, where `agrees` is false and `disagreement_reason` states
both calls and the row wins behind the numeric one.

## Race rows

A race row records one brief-level comparison. Its identity is
`race:<shoot>:<brief_id>`. `render_ids` names its competitors.
`panel_snapshot` is the fully resolved panel, including any brief-specific row
override, and `scorer_sha256` pins the scorer implementation.

`computed_winner` is the stable engine id returned by `tools/score_race.py`.
`recorded_winner` is the hand-recorded engine id. `agrees` is true or false when
both exist and null when comparison is impossible. `recorded_reason` preserves
the hand explanation. A false agreement has a factual `disagreement_reason`;
the scorer is never adjusted to force agreement.

`score` is the scorer audit object: `winner`, a row-win count per engine in
`row_wins`, all best engines per probe in `row_winners`, any count-tied leaders,
the gate winners considered, and `decided_by`. Equal best values award the row
to every tied engine. A row-count tie is decided by the panel's gate row. If the
gate is also exactly tied, the result is deliberately unresolved rather than
using an undocumented tertiary rule.

`missing_scores` maps engines to absent probes. `status` is `row_count`, `gate`,
`unresolved_gate_tie`, or `missing_scores`. Incomplete historical races remain
visible with null computed results instead of being guessed.

## Panel catalog

`panels.json` contains `panels`, the three reusable panel types, and `briefs`,
the brief-to-panel mapping. Each panel row names a probe, display label,
direction (`up` or `down`), optional numeric bar, and source-citing notes. A
panel names exactly one `gate`. Brief `row_overrides` preserve explicitly
recorded changes such as Harbor's background richness and Slow Road's
background busy-ness without multiplying the three audience panel types.

Bars are recorded context. The historical winner rule is row direction, then
row count, then the gate row; a bar does not eliminate an engine.

## How the reproduction checks work, and the limit they used to have

The reproduction check verifies each commit against its own tree. For every commit
reachable from HEAD that changed `races.jsonl`, the check extracts that commit's
tree, seeds a scratch ledger with the parent commit's bytes, runs the current
backfill against that tree, and requires the bytes it appends to be exactly the
bytes that commit added. Nothing is compared against a tree it was not built from,
and the concatenation of every commit's verified additions is the committed ledger.

It used to rebuild the whole ledger from the single commit that last wrote it. That
was correct only while every row had been written by that one commit, and it was
what let ordinary edits to the README stop breaking the build. It could not survive a
second append made after a source had changed. Rows added by the earlier commit
record the hashes their sources had then, so rebuilding them from the later tree
produced different hashes and the exact-backfill and probe-hash checks failed.
Regenerating the earlier rows to match was never a fix, because those rows are
immutable evidence.

That limit closed when the ledger first grew a second time, in the 2026-09-19
rescore, which is also when cohort skipping arrived. The two are one mechanism seen
from both ends. The backfill refuses to rebuild a cohort it already has, and the
check asks each commit only about the rows it actually added. The append-only
history check is unaffected and keeps working either way, and it remains the only
one of these that can catch a rewrite, because a rewrite carries its own pin.
