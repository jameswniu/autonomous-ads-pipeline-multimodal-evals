#!/usr/bin/env bash
# prop_gate.sh - PRE-render sanity gate for the twin video pipeline.
#
# Lives WITH THE SKILL and is runtime-agnostic on purpose (2026-07-23): the gate is pipeline
# behavior, not Claude Code behavior. Copy the skill directory anywhere (Mac mini, a Telegram bot,
# a cron LLM orchestrator) and the gate ports with it. Any host hook must be a THIN SHIM that calls
# this file; never re-implement the logic in the host.
#
# WHY PRE, not post: a bad look only reveals itself after a 60s-13min render plus credits, then
# needs a regenerate AND a re-render. Gating before the call deletes that round trip, so this
# IMPROVES latency.
#
# ============================ HOW THE CLASS IS CAPTURED ============================
# The keyword prefilter below is NOT the rule. Enumerating bad props (sipping, mid-bite, typing...)
# is few-shot examples, and a list can never close the class (2026-07-23) - a lit candle, a
# mid-sneeze, wind-blown hair, a dog mid-leap, melting ice cream, balancing on one foot all slip
# through any list the model writes.
#
# So the class travels as a GENERATIVE PRINCIPLE plus a PROBE that the LLM running the pipeline
# must answer (`prop_gate.sh probe`). That is what makes it exhaustive and portable: any orchestrator,
# on any box, applies the principle to insanities nobody enumerated. The regex is only a free
# early-exit for the few cases it happens to know; passing it proves NOTHING.
# ==================================================================================
#
# Usage:
#   prop_gate.sh probe [--json]            -> print the class + adversarial probe for the LLM to answer
#   prop_gate.sh check-prompt "<text>"     -> CHEAP non-exhaustive prefilter; exit 2 on a known-bad phrasing
#   prop_gate.sh require-look <lookId>     -> exit 2 unless the look was probed + attested
#   prop_gate.sh attest <lookId> "<finding>" -> record the reasoned verdict (finding text REQUIRED)
#   prop_gate.sh scan-render <video.mp4>   -> STRICT dense+zoomed+motion-amplified post-render scan (steam/absurdity)
#   prop_gate.sh hook                      -> read PreToolUse-style JSON on stdin (host shim)
#   prop_gate.sh selftest                  -> run the built-in cases
#
# State dir is overridable so it works on any box: $TWIN_GATE_DIR (default $TMPDIR or /tmp).
set -uo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STATE="${TWIN_GATE_DIR:-${TMPDIR:-/tmp}}/twin-lookgate"
mkdir -p "$STATE" 2>/dev/null

# ---------------------------------------------------------------------------
# THE PROBE: the class as a principle, not a list. This is the real gate.
# ---------------------------------------------------------------------------
# HISTORY, deliberately OUTSIDE the printed probe (2026-07-28):
# NOTHING ABOUT HANDS, ARMS, OR POSTURE. (Restored 2026-07-28 to its original state.)
# 
# A HAND CLAUSE was added here and rewritten twice. It stayed live in this probe for five
# hours, meaning every look gated inside that window was judged against hand instructions, while the two clips
# I put in the golden set predate it and were made WITHOUT them (one of the two carried its own arms line in the
# look prompt, not here).
# 
# Five separate attempts to constrain hands have now failed: chest height, palm angled toward camera,
# asymmetric-with-nameable-contact, quiet-base-pose, and a bare no-crossed-arms prohibition. Each was
# written to cure the previous one's tic and became the next one. Do not add a sixth.
# 
# Judge the look on the classes this gate exists for (change-dependent props, background detail).
# Say nothing about what her hands are doing.

probe_text() {
cat <<'EOF'
PRE-RENDER SANITY PROBE  (answer this about the look image BEFORE spending a render)

THE SETUP
This still image is about to be animated into a 10-30 second talking video by an engine that
animates ONLY the person: face, mouth, head, hair, a little body. EVERYTHING else in the frame is
a FROZEN PHOTOGRAPH for the entire clip, and the person never changes pose, never moves through
space, never completes any action.


Wording the prompt differently has failed three times. The check is here instead, and it is binary:
THE RULE: PAIRWISE COHERENCE IN 4D (2026-07-24/25). This is the whole gate, and it runs HERE,
BEFORE HeyGen, always. Not after the render, not as a pixel measurement.

Every pair is checked TWICE, on two different axes:
  1. as a SNAPSHOT (3D) - frozen at any single instant, does the pair make sense?
  2. along the 4TH DIMENSION: TIME FLOWING FORWARD (2026-07-25). Frames move forward by
     default, so every process in them must read as moving forward WITH time. This is not the time
     OF a frame (time-of-day, a coordinate, a snapshot fact) - it is the time BETWEEN frames, which
     only ever runs forward. A clip can be accurate in every snapshot and false on this axis: steam
     that appears then tapers away is a plausible mug in every frame and a process running BACKWARD;
     a woman drifting rearward with no gait is a fine photo in every frame and motion that undoes
     itself, a rewind playing inside a forward clip. Both shipped failures (the steaming mug, the
     back-pacing) broke the forward arrow while passing every snapshot check - the human eye caught
     the arrow, the frame-sampling instruments could not. Judge this axis only by watching the flow
     or by a trajectory trace over time (a scale/position series), never by sampling frames.

Do not ask whether the scene is odd. Take HER and each surrounding element in turn, one pair at a
time, and ask whether that PAIR still makes sense when nothing in it ever changes:

    her  <->  the mug        her  <->  the backdrop      her  <->  the other person
    her  <->  the candle     her  <->  the ground        her  <->  the phone
    her  <->  THE TIME       (the pair that is never visible in the frame, so it is the easiest to skip)

her <-> THE TIME deserves its own line because it is the only pair with no object in it, and it must
not be confused with the 4th dimension above: THIS pair is a SNAPSHOT check (which moment is it?),
while the forward arrow is the AXIS every pair gets checked along. Time itself is just the coordinate
her world runs on, so it can never disagree with her; a specific MOMENT can. Three
things have to name the same moment: the LIGHT in the still, the WORDS she speaks, and WHEN the clip is
actually delivered. Golden hour on screen while she says "almost midnight" breaks it. So does "Friday
just past six" over a night street, and so does a dawn look sent at 2am. Check it against the clock at
render time, not against the clock when the script was written - a clip drafted at 6pm and shipped at
midnight has silently broken this pair without a single pixel changing.

A pair fails when the element makes a CLAIM ABOUT HER that her body never delivers. The element is
almost never the problem by itself; the broken relationship is. So the fix is never to strip the
element out, it is to make the pair cohere:
  - steam rising means the drink is hot, which claims she is holding something scalding and will
    react. She never reacts. FIX: an empty dry mug, or constant steam she is plausibly at ease with.
    NOT: delete the mug.
  - a backdrop that slides claims she travelled through space. Her body has no gait, so she cannot
    pay that claim. FIX: make the travel read as the CAMERA moving rather than her walking, so she
    is a stationary subject and nothing is claimed about her. NOT: delete all motion.
Deleting the element passes the gate and loses the shot. Overfixing is a failure of this probe too.

THE PAIRS THAT TYPICALLY BREAK (illustrative; derive the rest, do not match a list)
Anything whose plausibility DEPENDS ON CHANGE will break, because change never comes. Ask what in
this scene is only believable if it evolves over the next 30 seconds. That covers, and is not
limited to:
  - thermal / physical states that must resolve: something scalding held bare-handed, ice melting,
    a candle or cigarette burning down, food that must be chewed
  - motion that must continue: a mid-stride walk, a raised foot, a thrown or falling object,
    pouring liquid, splashing water, a swinging door, OR A BACKDROP THAT SLIDES as though the
    camera travelled - on a subject with no gait, travel is a claim she can never pay
  - biology that cannot hold: a sneeze, a yawn, a held breath, a strained or unbalanced pose,
    an arm held up long enough to ache, standing on one leg
  - other agents who must act: another person mid-gesture or mid-word, a pet mid-leap, someone
    walking behind her, a face that must react to what she says
  - demands on HER she never answers: a ringing phone, a person addressing her, a timer going off,
    something falling she would have to catch
  - continuity that must advance: a screen mid-animation, traffic that must flow, steam that must
    rise and dissipate
The list above is ILLUSTRATIVE. Judge by the principle: does believing this frame require time to
pass? Then it fails.

WHAT IS FINE (do NOT sterilize the scene)
Frozen props and frozen backgrounds are normal and good. A mug at rest on a table, plants,
furniture, a parked car, a blurred street, a closed laptop, a cushion: all completely fine. Their
stillness costs nothing because nothing about them implies change. Scenes should stay alive and
furnished. Flagging a scene merely for containing objects is a FAILURE of this probe, not a pass.

HOW TO ASK IT (adversarial; default to REFUTE)
Do NOT ask "is this plausible?" That is a confirmation question and you can always rescue any
scene by inventing an excuse ("maybe it is not that hot", "maybe she has thick skin", "maybe it
just started"). Attack it instead, and ask what the scene DOES TO HER across the full clip:

    "Frozen exactly like this for 30 seconds, what becomes false, harmful, or impossible?"

Name the concrete consequence: what burns, what aches, what must land, what must be answered, who
is left waiting mid-gesture. If you find yourself constructing a reason the scene is OK, THAT
EXCUSE IS THE FINDING - fail it.

Then run the PAIRWISE SWEEP before answering. List every element in the frame, pair each with HER,
and for each pair write down what it claims about her and whether she can deliver it. A pair you
did not name is a pair you did not check, and the two failures that actually shipped (the steam mug,
the pacing backdrop) were both pairs nobody wrote down. Where a pair fails, propose the fix that
KEEPS the element and repairs the relationship; only if no such fix exists may you remove it, and
say so explicitly so the loss is a decision rather than an accident.

RENDER-TIME NOTE (held beverages, 2026-07-23): DEFAULT to NO steam - I prefer no smoke. For
any held drink, prompt a plain COOL/EMPTY mug ("completely empty, dry mug, no liquid, no drink, no steam,
no vapor, clear air") - an EMPTY mug is the surest zero-steam look. Add steam ONLY on explicit request;
then it must be a LITTLE ALL THE WAY (constant every frame), NEVER intermittent (steam appearing only
mid-clip is the incoherent bug). Get constant steam with a PROMINENT steam-plume prompt (a faint one
renders flickery); never post-process steam (it looks fake) - use HeyGen-native.

STRICT ENFORCEMENT (2026-07-23, after a "no steam" mug SHIPPED with an intermittent plume that
tapered off at the end): the render animates a faint steam layer even when the still look-preview reads
clean, and a SPARSE DOWNSCALED contact sheet HID it. So the no-steam default is enforced by a MANDATORY
strict scan, not an eyeball of a couple frames, and this generalizes to the whole change-dependent
absurdity class:
  1. Look preview: dense ZOOMED still-scan of the mug + the air above it at FULL res (never a thumbnail).
     Any wisp of vapor -> re-roll the look BEFORE spending a render.
  2. After the render: `prop_gate.sh scan-render <video>` (dense raw + motion-amplified diff sheets) and
     default-REJECT on ANY rising vapor across the WHOLE timeline. Re-roll/re-render until clean; never
     ship steam or any other change-dependent absurdity.

RENDER-TIME NOTE (backdrop travel = fake walking, I 2026-07-24). Same bug as the steam, different
prop: avatar_iii sometimes bakes a synthetic camera dolly into the render, sliding the frozen backdrop
out and then back as though she walked away and returned. The frame claims travel and her body never
pays it, because a photo avatar has no gait. This is roadmap item 5 (true locomotion) arriving
UNREQUESTED - the photo-avatar walk was already dropped as uncanny, and the engine now does it uninvited.

THE PAIR IS her <-> the backdrop, and the claim is TRAVEL. Repair the relationship, do not delete the
motion. I want the stroll: "the walking forward is great... the walk back is not natural", and
"pacing is great, just not out of sanity pacing". So:
  COHERENT   - travel that reads as the CAMERA moving. One way for the whole clip, and she scales with
               the scene, so she is simply a stationary subject and nothing is claimed about her body.
  INCOHERENT - travel that reads as HER moving: out and back, or the scene sliding while her apparent
               size stays pinned. That claims a gait she does not have.
Exactly the steam rule: a little all the way is fine, intermittent is the bug.

WEAKEST LEVER LAST. Flattening the scene (a wall or railing close behind her at one depth) does kill
the motion, measured 51px -> 14px on the same shot, but it kills the STROLL WITH IT and that is
overfixing - my note: "the cup fix should remove incoherence between the surrounding context and the
subject, not the whole thing". Reach for it only when nothing else is available, and say out loud that
the stroll is being traded away.

OPEN, do not pretend otherwise: on avatar_iii there is no known way to command the travel to run ONE
WAY. It takes no motionPrompt and no expressiveness, its motion is deterministic per look, and every
clip measured so far reverses (7, 2/4, 5/3, 4/4, 1/5, 3/5). Amplitude tracks depth in the lower corners;
what governs DIRECTION is not known. avatar_iv is the only engine that accepts a direction, at ~9 credits.

NEVER fix it in post. Six attempts all measured WORSE than the original (ECC affine, template similarity,
phase-correlation least squares, running-max zoom, per-zone, native 16:9), because the motion is LAYERED
(near plane ~23px while the far plane holds under 2px), so no single global warp fits it and every warp
displaces frame EDGES most - exactly where the ground sits.

MEASURE THE DELIVERED GEOMETRY, never a proxy. aspectRatio 1:1 without fit="cover" letterboxes a
landscape look: 484 flat white rows top and bottom of 1080, real content only y=242..837. Corner checks
then sample PADDING, which is static by construction, and return a confident false CLEAN - the same way
the sparse downscaled contact sheet hid the steam. Inspect the exact geometry being shipped.

VERDICT
  fail  - you can name a concrete thing that breaks, hurts, or must resolve and never does.
  pass  - you attacked it and found nothing that requires time to pass. Frozen-but-inert is a pass.
Default is FAIL: pass only on failure to find a violation, never on a plausible story.
EOF
  # LEARNED RULES (the loop's read-back leg): failures measured by scan-arrow/scan-render are
  # written by `learn` and printed here, so the pre-layer gets strictly smarter and the same
  # mistake never costs a second render.
  if [ -f "$DIR/learned_rules.md" ]; then
    echo
    echo "=============== LEARNED FROM ACTUAL FAILURES (read before answering) ==============="
    sed -n '/^## Learned/,$p' "$DIR/learned_rules.md"
  fi
}

# CHEAP, NON-EXHAUSTIVE prefilter. Never the definition of the class; a pass here means nothing.
MIDACTION='(sipping|drinking|taking a sip|raising [a-z ]*to (her )?lips|mid-bite|mid bite|biting|eating|chewing|pouring|mid-pour|typing on|scrolling|dialing|answering (the )?phone|holding [a-z ]*(steaming|piping hot|scalding|lit|burning))'
MIDSTRIDE='(mid-stride|mid stride|walking toward|walking down|striding|mid-air|leaping|jumping|running)'

check_prompt() {
  local p; p=$(printf '%s' "${1:-}" | tr '[:upper:]' '[:lower:]')
  [ -z "$p" ] && return 0
  if printf '%s' "$p" | grep -qE "$MIDACTION"; then
    cat >&2 <<'EOF'
BLOCKED (prop_gate prefilter): this look prompt puts her MID-INTERACTION with a prop.
The engine animates only the person, so the prop freezes and the interaction reads as nonsense.
Rephrase to an AT-REST state (the mug rests on the table; hands empty, resting, or out of frame).
NOTE: this prefilter is not the rule. Run `prop_gate.sh probe` and apply the class properly.
EOF
    return 2
  fi
  if printf '%s' "$p" | grep -qE "$MIDSTRIDE"; then
    cat >&2 <<'EOF'
BLOCKED (prop_gate prefilter): motion that must continue (mid-stride/leap/run). A photo avatar has
no gait, so the step never lands and it reads floaty (2026-07-23). Use an at-rest pose.
NOTE: this prefilter is not the rule. Run `prop_gate.sh probe` and apply the class properly.
EOF
    return 2
  fi
  return 0
}

require_look() {
  local id="${1:-}"
  [ -z "$id" ] && return 0
  if [ ! -f "$STATE/$id" ]; then
    cat >&2 <<EOF
BLOCKED (prop_gate): look $id has not been probed before this render.
A render costs 60s-13min plus credits, so the check runs BEFORE the spend, not after.
Do this first:
  1. bash "$DIR/prop_gate.sh" probe      # prints the class + adversarial probe
  2. fetch the look preview image and LOOK at it, then answer the probe honestly
  3. if it survives:  bash "$DIR/prop_gate.sh" attest $id "<what you attacked and found nothing on>"
Then retry the render. A finding is required: attesting without reasoning defeats the gate.
EOF
    return 2
  fi
  # LEARNED PRE-SPEND BLOCK (the loop's write-back leg, I 2026-07-25). A look with a MEASURED
  # arrow failure on record hard-blocks the render until I have seen the prediction and said go.
  # This exists because vid-1 that night spent a credit on a still whose failure was predicted by
  # five prior measurements, with the prediction buried in an attest log I never saw.
  # Entries: "<lookId>|<evidence>" lines. Clear a line only when I decide the look is usable.
  # One-render override AFTER I say go: OWNER_OK=1 on the render attempt.
  # ENGINE-QUALIFIED (fixed 2026-07-25, my catch): the dance is per (look, ENGINE), not per
  # look - the coastal look retreats on avatar_iii yet PASSED on avatar_iv the same night. Entries:
  #   <lookId>|<engine>|<evidence>     e.g.  <lookId>...|avatar_iii|early shrink 0.95x at t=2, 3x
  #   <lookId>|any|<evidence>          blocks every engine (use only when measured on 2+ engines)
  local rejf="${ARROW_REJECTS_FILE:-$DIR/arrow_rejects.txt}"
  local eng="${2:-any}"
  if [ -f "$rejf" ] && [ "${OWNER_OK:-0}" != "1" ]; then
    local hit
    hit=$(grep -E "^$id\|($eng|any)\|" "$rejf" 2>/dev/null | head -1)
    # legacy 2-field entries (lookId|evidence) still block everything rather than silently passing
    [ -z "$hit" ] && hit=$(grep -F "$id|" "$rejf" 2>/dev/null | grep -vE "^$id\|[a-z_]+\|" | head -1)
    if [ -n "$hit" ]; then
      cat >&2 <<EOF
BLOCKED (prop_gate arrow history): this (look, engine) has a MEASURED arrow failure on record:
  $hit
Re-rendering the same pair reproduces the same dance (deterministic per look+audio+engine).
The SAME look may be clean on a DIFFERENT engine (coastal: iii retreats, iv passed) - the block
is engine-qualified for exactly that reason.
ASK ME with that evidence BEFORE spending. If I say go: OWNER_OK=1 on the render call.
EOF
      return 2
    fi
  fi
  return 0
}

# scan-arrow: the loop's MEASUREMENT leg, post-render. Runs the calibrated body-trace verdict
# (arrow_probe.py). On FAIL/REVIEW prints the exact loop I specced 2026-07-24: ping me WITH
# the bad clip (observability), regen (capped at 2 automatic re-rolls, then ask), and learn the
# finding into the pre-layer so the same mistake never costs a second credit.
arrow_scan() {
  local vid="${1:-}"
  [ -z "$vid" ] && { echo "usage: prop_gate.sh scan-arrow <video.mp4> [lookId]" >&2; return 64; }
  [ -f "$vid" ] || { echo "scan-arrow: not found: $vid" >&2; return 64; }
  command -v python3 >/dev/null 2>&1 || { echo "scan-arrow: python3 required" >&2; return 69; }
  if [ ! -f "$DIR/arrow_probe.py" ]; then
    echo "scan-arrow needs $DIR/arrow_probe.py, and it is missing." >&2
    return 64
  fi
  python3 "$DIR/arrow_probe.py" "$vid"
  local rc=$?
  local look="${2:-<lookId>}"
  local sess="${CLAUDE_SESSION_NAME:-heygen}"
  if [ "$rc" -eq 1 ]; then
    cat <<EOF

THE LOOP (2026-07-24), all three steps, in this order:
  1. PING ME NOW with the BAD CLIP ATTACHED (observability), before regenerating:
     "[$sess] Arrow gate caught a rewind on this render, holding it back. <which second, which
      direction, from the trace above>. Re-rolling (~7 min: new still ~90s, render ~5 min)."
  2. REGEN: fix the INPUT (stance clause / funded motionPrompt), never edit the video.
     Cap automatic re-rolls at 2, then ask me before spending more.
  3. LEARN so the pre-layer carries it (no credit to re-learn):
     bash "$DIR/prop_gate.sh" learn "<what failed + measurement>"
     and add the look to the pre-spend block:  echo "$look|<evidence>" >> "$DIR/arrow_rejects.txt"
EOF
  elif [ "$rc" -eq 2 ]; then
    cat <<EOF

REVIEW verdict: do NOT ship and do NOT auto-reject. Send the clip to me with the trace line
that triggered review, and let my eye decide (walk B's 1.16->0.97 ease-back was ACCEPTED).
EOF
  fi
  return $rc
}

# verify: the POST-render 4D coherence sweep - the artifact-side twin of `probe` (2026-07-25).
# probe judges the INPUT before the spend; verify judges the OUTPUT before the ship. Same pairs,
# same two axes, asked about what actually rendered, because the engine sometimes violates its
# inputs (the "no steam" mug that shipped a plume; the unprompted walk-back).
verify_text() {
cat <<'EOF'
POST-RENDER 4D COHERENCE SWEEP  (run on the FINISHED clip, before it ships anywhere)

The pre-render probe judged the still. The engine then invented everything between the frames,
so re-ask the PAIRS about the ARTIFACT. Watch the clip - actually watch it - then:

1. MEASURED ARMS (run both, they are cheap and they catch what eyes skim past):
     scan-arrow <clip> [lookId]   -> her body's trajectory: FAIL = rewind, REVIEW = my eye
     scan-render <clip>           -> steam/prop flow: default-reject ANY rising vapor
2. PAIRWISE SWEEP ON THE OUTPUT (the engine can ADD elements the still never had):
     her <-> motion    did any move go unfunded? gestures to NOBODY (greeting the air), a lean
                       with no target, travel with no gait - walk A failed exactly this way
     her <-> props     did anything appear mid-clip that the still did not contain?
     her <-> agents    does she address, look at, or react to someone who never exists on screen?
     her <-> TIME      THE 4TH DIMENSION, on EVERYTHING in frame, not just what the instruments
                       measure: time between frames only runs forward, so no process may undo
                       itself. Her body returning, steam retracting, light reverting, hair
                       resetting, a shadow un-moving - a rewind ANYWHERE fails the clip even if
                       scan-arrow and scan-render both pass, because they only watch her body and
                       the vapor. This line is why you WATCH the clip instead of trusting the arms.
     her <-> THE TIME  the DELIVERY leg (a snapshot check, distinct from the axis above): light +
                       words + the clock AT SEND TIME still agree? (a clip drafted at 6pm and
                       shipped at midnight breaks this with no pixel changing - check the clock
                       when it SHIPS, not when it was cut)
3. VERDICTS: any measured FAIL -> the loop (ping me WITH the clip, regen, learn). Any REVIEW
   or judgment-call pair -> I see it BEFORE it ships, with the flagged second named. All
   clean -> ship, and say what was checked, not just "done".

Snapshot instruments cannot see the 4th dimension; frame grids lie reassuringly. Watch the flow.
EOF
}

# learn: append a rule the PRE-render probe prints from now on. The write-back leg.
learn_rule() {
  local rule="${1:-}"
  # LEARNED_RULES_FILE is overridable so the selftest cannot pollute the real, append-only record.
  local f="${LEARNED_RULES_FILE:-$DIR/learned_rules.md}"
  [ -z "$rule" ] && { echo "usage: prop_gate.sh learn \"<rule>\"" >&2; return 64; }
  [ -f "$f" ] || printf '# learned_rules.md\n\n## Learned\n' > "$f"
  printf -- '- %s\n' "$rule" >> "$f"
  echo "learned (the pre-render probe now carries this):"
  printf '  %s\n' "$rule"
  return 0
}

# ---------------------------------------------------------------------------
# scan-render: STRICT post-render steam / change-absurdity scan (2026-07-23).
# WHY: a SPARSE, DOWNSCALED contact sheet MISSED intermittent steam on a "no steam"
# mug and the clip shipped; I caught the rising plume that tapered off at the end.
# So the post-render check is now DENSE + ZOOMED + MOTION-AMPLIFIED, and MANDATORY
# before delivery for BOTH twins. Two sheets on the held-prop + the air above it:
#   raw  zoom: dense frames (~2.4/s), tiles kept large (no heavy downscale) so faint
#              translucent vapor stays visible.
#   diff zoom: consecutive-frame difference, contrast-amplified, so RISING vapor lights
#              up as bright vertical wisps against an otherwise black (static) field -
#              unmissable even when faint. Distinguish steam (a translucent column that
#              STARTS AT THE MUG RIM and moves UP) from hair sway (lateral, at the sides)
#              and mouth articulation (top of band); the band is cropped BELOW the chin.
# Verdict is the LLM's: open BOTH sheets, scan EVERY tile across the WHOLE timeline, and
# default-REJECT on any rising vapor/steam/smoke (or any other change-dependent absurdity).
# Never ship on a sparse or downscaled sheet again.
# ---------------------------------------------------------------------------
steam_scan() {
  local vid="${1:-}"
  [ -z "$vid" ] && { echo "usage: prop_gate.sh scan-render <video.mp4>" >&2; return 64; }
  [ -f "$vid" ] || { echo "scan-render: not found: $vid" >&2; return 64; }
  command -v ffmpeg >/dev/null 2>&1 || { echo "scan-render: ffmpeg required (portable check needs it)" >&2; return 69; }
  local base outdir W H DUR
  base="$(basename "$vid")"; base="${base%.*}"
  outdir="$STATE/scan-$base"; mkdir -p "$outdir"
  W=$(ffprobe -v error -select_streams v:0 -show_entries stream=width  -of default=nk=1:nw=1 "$vid" 2>/dev/null)
  H=$(ffprobe -v error -select_streams v:0 -show_entries stream=height -of default=nk=1:nw=1 "$vid" 2>/dev/null)
  DUR=$(ffprobe -v error -show_entries format=duration -of default=nk=1:nw=1 "$vid" 2>/dev/null)
  [ -z "$W" ] && { echo "scan-render: could not read video dims" >&2; return 69; }
  # held-prop + air-above band: center-x 0.24..0.76, y 0.44..0.96 (mug + its rising column, BELOW the chin)
  local cw ch cx cy
  cw=$(( W*52/100 )); ch=$(( H*52/100 )); cx=$(( W*24/100 )); cy=$(( H*44/100 ))
  local raw="$outdir/scan-raw-zoom.png" diff="$outdir/scan-diff-zoom.png"
  ffmpeg -v error -y -i "$vid" -vf "crop=$cw:$ch:$cx:$cy,fps=12/5,scale=320:-1,tile=6x5" -frames:v 1 "$raw" 2>/dev/null
  ffmpeg -v error -y -i "$vid" -vf "crop=$cw:$ch:$cx:$cy,format=gray,tblend=all_mode=difference,lutyuv=y=val*8,fps=12/5,scale=320:-1,tile=6x5,format=gray" -frames:v 1 "$diff" 2>/dev/null
  echo "scan-render: $base  ${W}x${H}  ${DUR}s"
  echo "  raw  zoom sheet: $raw"
  echo "  diff zoom sheet: $diff   (rising bright vertical wisps from the mug rim = steam)"
  echo "  STRICT VERDICT (LLM): open BOTH sheets; default-REJECT on ANY rising vapor across the timeline."
  echo "  If rejected: re-roll the look (strict dense STILL-scan, zero vapor) and/or re-render; never ship steam."
  return 0
}

case "${1:-}" in
  probe)
    if [ "${2:-}" = "--json" ]; then
      probe_text | python3 -c 'import json,sys; print(json.dumps({"probe": sys.stdin.read()}))'
    else
      probe_text
    fi
    exit 0 ;;
  check-prompt) check_prompt "${2:-}"; exit $? ;;
  require-look) require_look "${2:-}" "${3:-}"; exit $? ;;
  scan-render) steam_scan "${2:-}"; exit $? ;;
  scan-arrow)  arrow_scan "${2:-}" "${3:-}"; exit $? ;;
  verify)      verify_text; exit 0 ;;
  learn)       learn_rule "${2:-}"; exit $? ;;
  attest)
    [ -z "${2:-}" ] && { echo "usage: prop_gate.sh attest <lookId> \"<finding>\"" >&2; exit 64; }
    if [ -z "${3:-}" ]; then
      echo "REFUSED: attest requires a finding - what did you attack, and what survived?" >&2
      echo "A bare attestation turns the gate into a rubber stamp. Run 'prop_gate.sh probe' first." >&2
      exit 64
    fi
    printf '%s\n' "$3" > "$STATE/$2"
    echo "attested: $2"; exit 0 ;;
  hook)
    IN=$(cat)
    TOOL=$(printf '%s' "$IN" | jq -r '.tool_name // empty' 2>/dev/null)
    case "$TOOL" in
      *create_prompt_avatar)
        check_prompt "$(printf '%s' "$IN" | jq -r '.tool_input.prompt // empty')"; exit $? ;;
      *create_video_from_avatar)
        require_look "$(printf '%s' "$IN" | jq -r '.tool_input.avatarId // empty')" \
                     "$(printf '%s' "$IN" | jq -r '.tool_input.engine.type // "any"' 2>/dev/null)" || exit 2
        # LETTERBOX GUARD (2026-07-25, second shipped regression of this class): an explicit
        # aspectRatio without fit=cover letterboxes a landscape look into flat white borders,
        # AND silently relocates every fixed-fraction probe band into static padding (the r6
        # episode flipped rest verdicts 0.014<->0.132). Prose warned; prose regressed; now the
        # SPEND is blocked at the call, exactly like the un-attested-look rule above.
        AR=$(printf '%s' "$IN" | jq -r '.tool_input.aspectRatio // empty')
        FIT=$(printf '%s' "$IN" | jq -r '.tool_input.fit // empty')
        if [ -n "$AR" ] && [ "$AR" != "auto" ] && [ "$FIT" != "cover" ]; then
          TOKEN="${TMPDIR:-/tmp}/.twin-allow-letterbox"
          NOW=$(date +%s); TM=$(stat -f%m "$TOKEN" 2>/dev/null || stat -c%Y "$TOKEN" 2>/dev/null || echo 0)
          if [ -f "$TOKEN" ] && [ $((NOW - TM)) -lt 120 ]; then
            rm -f "$TOKEN"   # deliberate letterbox: single-use, then the default denies again
          else
            echo "BLOCKED (letterbox_gate): aspectRatio=$AR without fit=\"cover\" letterboxes a landscape"
            echo "look (white borders shipped twice; probe bands land in padding and lie). Add fit: \"cover\","
            echo "or for a DELIBERATE letterbox: touch $TOKEN and retry within 120s (single use)."
            exit 2
          fi
        fi
        MP=$(printf '%s' "$IN" | jq -r '.tool_input.motionPrompt // empty' | tr '[:upper:]' '[:lower:]')
        if [ -n "$MP" ] && printf '%s' "$MP" | grep -q 'hand'; then
          echo "Advisory: motionPrompt mentions hands. On a talking-head that made avatar_iv animate visible"
          echo "hands oddly (2026-07-23). Prefer head/face/hair only, or framing where hands are truly out of frame."
        fi
        exit 0 ;;
    esac
    exit 0 ;;
  selftest)
    fails=0
    # capture-then-match, never `probe_text | grep -q`: with pipefail, grep -q's early exit
    # SIGPIPEs probe_text and reports a false FAIL (bitten 3x, 2026-07-24/25)
    _pt="$(probe_text)"
    case "$_pt" in *"what becomes false, harmful, or impossible"*) : ;; *) echo "FAIL: probe text missing"; fails=1 ;; esac
    case "$_pt" in *"LEARNED FROM ACTUAL FAILURES"*) : ;; *) echo "FAIL: learned rules not reaching the probe"; fails=1 ;; esac
    check_prompt "woman holding a steaming hot mug near her face" 2>/dev/null; [ $? -eq 2 ] || { echo "FAIL: steaming mug not caught"; fails=1; }
    check_prompt "woman by a window, hands resting in her lap, a mug sits on the table" 2>/dev/null; [ $? -eq 0 ] || { echo "FAIL: at-rest scene wrongly blocked"; fails=1; }
    check_prompt "full body mid-stride walking down a city sidewalk" 2>/dev/null; [ $? -eq 2 ] || { echo "FAIL: mid-stride not caught"; fails=1; }
    require_look "definitely-not-attested-$$" 2>/dev/null; [ $? -eq 2 ] || { echo "FAIL: unprobed look allowed"; fails=1; }
    bash "$0" attest "selftest-$$" 2>/dev/null; [ $? -eq 64 ] || { echo "FAIL: bare attest (no finding) accepted"; fails=1; }
    bash "$0" attest "selftest-$$" "attacked thermal/motion/biology, nothing requires time to pass" >/dev/null
    require_look "selftest-$$" 2>/dev/null; [ $? -eq 0 ] || { echo "FAIL: attested look blocked"; fails=1; }
    steam_scan "" 2>/dev/null; [ $? -eq 64 ] || { echo "FAIL: scan-render missing-arg not caught"; fails=1; }
    # letterbox guard: explicit ratio without fit=cover blocks; with cover passes; token overrides once
    _lb() { printf '{"tool_name":"mcp__heygen__create_video_from_avatar","tool_input":{"avatarId":"selftest-%s","aspectRatio":"1:1"%s}}' "$$" "$1" | bash "$0" hook >/dev/null 2>&1; }
    _lb ""; [ $? -eq 2 ] || { echo "FAIL: 1:1 without fit=cover not blocked"; fails=1; }
    _lb ',"fit":"cover"'; [ $? -eq 0 ] || { echo "FAIL: 1:1 with fit=cover wrongly blocked"; fails=1; }
    touch "${TMPDIR:-/tmp}/.twin-allow-letterbox"
    _lb ""; [ $? -eq 0 ] || { echo "FAIL: letterbox override token not honored"; fails=1; }
    _lb ""; [ $? -eq 2 ] || { echo "FAIL: letterbox token not single-use"; fails=1; }
    [ $fails -eq 0 ] && echo "prop_gate selftest: all passed" || echo "prop_gate selftest: FAILURES above"
    exit $fails ;;
  *)
    grep '^#' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
esac
