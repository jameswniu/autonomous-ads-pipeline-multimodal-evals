# Race ledger schema

`races.jsonl` is an append-only JSON Lines ledger. Each physical line is one
complete JSON object. Existing lines are evidence and must not be rewritten;
the backfill only appends identities that are not already present and refuses a
changed row under an existing identity.

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

## Known limit of the reproduction checks

The reproduction checks rebuild the whole ledger from the single commit that last
wrote it. That is correct while every row was written by that commit, which is the
case today, and it is what lets ordinary edits to the README and other sources stop
breaking the build.

It does not survive a second append made after a source has changed. Rows added by
the earlier commit record the hashes the sources had then, so rebuilding them from
the later tree produces different hashes and the exact-backfill and probe-hash
checks fail. Regenerating the earlier rows to match is not a fix, because those rows
are immutable evidence.

The fix, when the ledger next grows, is to verify each row against the commit that
introduced it, rebuilding from that tree and comparing only the rows that commit
added. The append-only history check is unaffected and keeps working either way.
