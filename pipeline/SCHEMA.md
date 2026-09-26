# The run ledger

One file per run, `ledger.jsonl` in the run's directory, one JSON object per line, append only. `pipeline/ledger.py` is the only thing that writes it. There is no update and no delete, so a correction is a new row.

The August ledgers under `shoots/<batch>/` were written by hand by the agent that ran those shoots, so their shape drifts from shoot to shoot. `pipeline/replay.py` reads them as they are. This schema is what the graph writes from now on.

## Every row

| Field | Meaning |
|---|---|
| `schema` | The schema version, `1` |
| `run` | The run's id, shared by every row it writes |
| `seq` | Position in the run, from 1, with no gaps |
| `ts` | UTC time the row was written, to the millisecond |
| `kind` | What happened, one of the kinds below |
| `step` | The graph node the row is about |

`Ledger.append` refuses any other field with one of these six names, since it would silently overwrite the row's own.

## Kinds

| Kind | Written by | Carries |
|---|---|---|
| `gate` | Board, the voice draw's checks inside render and closer, the check that holds the story's character apart from the narrator, the cast check on every scene, the closer's reused-take, identity, prop, jaw and cast checks, ad gates, and the ship gate | `spot`, and `pass` or `passed` for whether it held. The board also carries `board` (its file, relative to the repository), except when the probe's own output could not be read at all, when it carries `stderr` instead. It carries `reason` when the spot itself is not on the board, or `checks` and `failed` when a check ran. `checks` holds the checks the probe had when the run was made, so a run from before a check existed carries no entry for it, which is never a pass. The checks around a voice draw or a closer render name themselves in `check`, quote their guard or gate in `said`, and carry `voice` or `look` as a fingerprint. A closer check also carries `source`, naming where the render came from, and the jaw check adds `reading`, plus `unreadable` and `error` when it could not take one. A cast check carries `check: cast`, the scene it read when it ran in render, `against`, which face it was read against (`character`, or `presenter` for a spot with no character), and `reading`, the cast gate's line with the face similarity, the floor and, as `not`, the similarity to the narrator when it was read against her too (`-` when it was not, and readings written before that field existed carry none), plus `unreadable` when the gate gave no reading. The character check carries `check: distinct`, `reading`, the character's reference read against the narrator's, and `character_sha256` and `presenter_sha256`, the two faces it compared. It passes only under the floor, and a run whose character reads as the narrator stops before any scene is paid for. A spot with a character needs the narrator's face too, and stops before any spend without one. Ad gates carries `caption`, `drift`, `mouth`, `corr` and `lag_s`, plus `unreadable` when it could not take a reading. The ship gate carries `cause`, `loudness`, `slit`, `replay`, `replay_turn_s` and the `overrides` in force |
| `request` | Render and closer, for every scene, voice draw, read-back, upload or closer render sent to a vendor, and render in a dry run | `request_id`, `spot` and `engine`. A render also carries `scene`, `prompt`, `params`, `est_usd`, `why`, `prompt_reused` and `asked_by_person`, and `reference_sha256` when the scene shows the story's character and is sent her face. A scene in a chain carries `start_sha256` instead, the hash of the frame it started from, and `start_from`, which says in words what that frame was, `the character's still` or `the last frame of zai-a`. A chained take is kept only while that hash is the frame its scene would start from now. The face and the frame themselves never go on the ledger. A dry run's chained request carries `start_from` alone. A voice draw carries `voice` as a fingerprint, `draws` and `text`. A read-back or an upload carries `file`. A closer render carries `look` as a fingerprint and `params`. A dry run carries `dry: true`, since nothing is sent |
| `queued` | Render and closer, once a vendor accepts a request | `request_id` and `vendor_id`, plus `status_url` and `response_url` for a render |
| `landing` | Render, closer and build, for what a request or a local step came back with | `status`, one of OK, REUSED, REFUSED, UNCONFIRMED, REJECTED, FAILED, TIMEOUT or UNCOLLECTED, described below. Usually joined to its request by `request_id`, and named by `spot` instead when there is no live request behind it, a reused take or a build's own local step. Carries `file` and `sha256` on success, and depending on the case, `seconds`, `bytes`, `edge_clip`, `vendor_id`, `probe`, `text`, `log`, `source`, `note`, `http`, `during`, and the vendor's own `error` text. A build whose spot names `switches` also carries `switch_times`, the seconds into the cut where the switching sound was placed, the two sentence boundaries for `slots`, where the picture changes most for `cuts`, and none for `off`. A reused closer carries `identity: unrecorded`, since the take holds no record of the look and voice that made it and whoever set `CLOSER_FROM` vouches for it |
| `estimate` | Render, in a dry run | `spot`, `scenes`, `engine`, `est_usd` and `dry: true` |
| `build` | Build, before the build script runs | `spot`, `brand`, `tag`, `bed`, `closer_nudge`, `closer_autoalign`, `scene_px` (each scene's source size), `upscale` (how far the build enlarges the smallest scene to reach 1080), `script`, `master` (naming the mastering pass and its settings) and `version`, and `slots` when the spot gives a narration sentence more than one shot, the shots under each of the three sentences in the order they play, written before any of them is joined, and `switches` when the spot says where the switching sound plays, `off` or `cuts` or `slots`. The six build rows in `shoots/graph-zai` came before `scene_px` and `upscale` existed. Its three scenes measure 1280x720, so each was enlarged 1.5 times |
| `eye` | Eye | `spot`, and, repeated from the answer, `verdict`, `cause`, `who`, `asked_by` and `preset`, plus the whole answer again, nested under `answer` |
| `review` | Review | `spot`, and, repeated from the answer, `verdict`, `who` and `preset`, plus the whole answer again, nested under `answer` |
| `withdrawn` | Review, when the answer withdraws a delivered cut | `spot`, `master` (the delivered file, or the build's master when nothing was delivered), `reason` and `back_to` |
| `deliver` | Deliver | `spot`, `file`, `sha256`, `seconds` and `supersedes`, set when this delivery replaces an earlier cut |
| `waiting` | The run command, when a run stops for a person | `trail`, the run so far, ending at the eye or the review |
| `resumed` | The run command, when a run is re-entered from a checkpoint | `reason`, `trail` up to the checkpoint re-entered, `abandoned` (the kind of question the re-entry abandons, if one was pending), and `attempts_before` and `attempts_after`, the loop budgets at that point |
| `crashed` | The run command, when a step raises instead of returning | `error` and `trail`, ending at the step that raised, or `?` when no next step was known |
| `close` | Ledger | `spot`, `outcome`, `trail`, `because` (the verdict that ended the run) and `artifacts` |
| `redacted` | A person, by hand, never the graph | `seqs`, the seq numbers of the rows that changed, `what`, one sentence saying what was replaced with what, and `by`, who did it |
| `corrected` | A person, by hand, never the graph | `seqs`, the seq numbers of the rows it corrects, which stay as written, `what`, one sentence saying what they got wrong and what is true, and `by`, who did it |

### Landing statuses

| Status | Written when |
|---|---|
| `OK` | A voice take survived its draw, a read-back transcribed, the character's or the presenter's reference was cut, or the character's still was taken for a chain to start from, carrying `source` (a word, `take`, `still` or `closer take`, never a path), `source_sha256` (the hash of the file it was cut from, so a face or a still is taken again when its source changes) and `note`, a rendered scene downloaded, a closer's audio uploaded, a closer render finished, or a build produced its master |
| `REUSED` | This run already held the take, scene or closer render asked for, or an existing closer take was reused through `CLOSER_FROM`, so nothing was asked for again |
| `REFUSED` | The vendor declined the request itself, a render's queue or a closer's render call, before anything was produced |
| `REJECTED` | `fal` accepted a render as queued, then returned a 422 on the finished result |
| `FAILED` | A voice draw produced no take, a read-back or an audio upload came back with a non-2xx status, a render came back with no video, its finished result was gone at the vendor, or the vendor no longer had the job at all (`during: status`), a closer render was explicitly reported failed, or a build script, its mastering pass or the join of a sentence's shots (`during: join`) failed |
| `TIMEOUT` | Polling a render or a closer render never reached a finished state before the wait limit. The request is still owed, so the next pass polls it again instead of sending another |
| `UNCONFIRMED` | A scene or closer render was sent and the vendor never confirmed taking it, the POST failed on the network or came back with no id. It may have been billed, so it is never sent again on its own, the run stops, and a request with no queued row and no landing counts the same way. A person who re-enters the run after it has chosen to send again |
| `UNCOLLECTED` | A render or a closer render the vendor called finished, whose file could not be fetched or downloaded for now, behind a locked account, a rate limit or the vendor's own error. A locked account closes a job it never ran the same way, a second after it was sent, so the render may not exist. Owed the same way, collected on the next pass, and never sent again while the vendor still has the job. A render row written before this covered held-back results says FAILED with one of those codes beside it, and is owed the same way |

The eye and the review nest the person's whole answer under `answer`, scrubbed like everything else, because a key inside it, `spot` or `step` among them, could otherwise collide with the row's own fields. `preset` is true on both when the answer came from a preset rather than a person typing one in.

No written row is ever changed in place, with one sanctioned exception. A person may correct what an earlier row exposed, and records the correction as a `redacted` row of its own, appended like every other row, never an edit to the row it corrects. It was used once, in `shoots/graph-zai/ledger.jsonl`, to remove local paths a few rows had captured before that ledger's first commit.

A row that says something false is left as written, and a person appends a `corrected` row naming it and saying what is true. It was used once, in `shoots/graph-zai-cast/ledger.jsonl`, for a re-entry that said the vendor account had been topped up when it had not.

No identity id is ever written. A value under the keys `look`, `avatar`, `avatar_id`, `voice` or `voice_id`, at any depth in an answer or a verdict, is written as its fingerprint instead, `sha256:` plus twelve hex characters (`fingerprint` in `pipeline/ledger.py`). A fingerprint hides the id itself but still shows when two rows used the same one, which is fine because an id is useless without the account key it belongs to.

Any text a script prints, an error, what a gate or a guard said, passes through the toolkit's `clean()` before it reaches the ledger. It makes the run's own paths relative to the run directory and the repository's relative to the repository, replaces a temporary directory with `<tmp>/`, replaces the home directory with `~`, and, in a live run, replaces every identity the pin file holds with its fingerprint too. A file path recorded on its own, `file` on a landing or `master` on a build, is relative to the run directory the same way, since a kept run is committed. The board gate's `board` field is relative to the repository instead, where the board file lives.

A request and its landing share a `request_id`. That is the join the August ledgers could not make, because every one of their ids is the literal string `<request-id>`.
