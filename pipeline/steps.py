"""The seven steps of the pipeline, declared once.

The pipeline shoots one spot, a short ad film, by running it through these seven steps in order, and each
step has a gate, a pass or fail check, that has to hold before the next step starts. A gate belongs to one
of the three tiers of evals the README names. Process asks whether every step ran and its gate fired,
outcome asks whether what shipped is true to the brief and its facts, and quality asks whether it meets
the bar for its audience.

`pipeline/graph.py` builds its nodes from this list, `pipeline/replay.py` reads the
ledgers against it, and tests/test_gates.py holds the numbers each step says it
enforces to the gate files that set them. The system map is still drawn from its own
list in `tools/render_map.py`, and the README's step table and diagram are checked
against that list, so the two lists are not yet checked against each other.

This module imports nothing from langgraph, so the tests that only need the names
do not need the orchestration dependency.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Step:
    node: str        # the graph node that runs this step
    title: str       # the name every surface uses
    proves: str      # the step table's middle column, what must hold before the next step
    fails: str       # the step table's last column, what happens when it does not
    card: str        # the one line the system map prints on the step's card
    footer: str      # the code path the system map prints under it
    tier: object     # the tier that owns the step's gate, or a tuple of the tiers that share it
                     # (process, outcome or quality, as the module docstring explains them)


# Words the step texts below use. A board is the written plan for one spot, a boards.json file with its
# scenes, narration, props and rules. A scene is one generated video clip, and the narration is the
# spoken voice-over. The closer is the last shot of every spot, where the narrator, an AI avatar
# presenter, speaks the brand line to the camera. The story's character is the one person written into
# the scenes, and she is never the narrator. A look is the generated still image of the narrator in one
# outfit and setting, which a closer render starts from. The master is the finished video after loudness
# mastering. The ledger is the append-only log of every vendor request and what came back. The eye is the
# pause where the run waits for a person to watch the cut and approve it or send it back, and the eye rows
# are the board's four judgment questions (hook, realism, absurdity and logic), which a person scores
# 0 to 3 by eye rather than by a mechanical check. A REVIEW is the mouth check's middle verdict, neither
# pass nor fail, and it goes to the eye. The hook scene is the one the board names to open the film, and
# pipeline/DOCTRINE.md states the three rules a board is held to.
STEPS = (
    Step("board", "Board",
         "Twelve mechanical checks, free, before a cent is spent (the product absent before the "
         "payoff, the escalation declared, the quirk never spoken by the narration, mouths closed "
         "under narration, the centre-crop clause present, every person in a scene written as the "
         "story's character, the narration spoken to the viewer, a chain naming the spot's own "
         "scenes once each, slots giving each of the three sentences its own shots, every "
         "scene once, the switching sound placed where the build knows how, any props every shot must "
         "hold named one to a line, and the hook scene the board names opening the film). The four "
         "judgment rows it prints are scored when the board is written, and a live run spends nothing "
         "until each is 2 or more and the board names who scored them",
         "The board goes back",
         "12 mechanical checks, 4 eye rows", "gates/board_probe.py", "process"),
    Step("render", "Render",
         "Every request and every landing appended to the ledger, the vendor's own rejection "
         "text included, and every scene read by the edge probe (it flags a story prop cut off by the "
         "frame's edge). A scene that shows the story's "
         "character is rendered from her face, held apart from the narrator's first, and every "
         "scene is read back against it and refused under 0.3 face similarity, or when it reads at "
         "least as close to the narrator, who appears only in the closer. Every scene is read again for "
         "continuity by a judge that holds each prop the board names from the first frame to the last and the "
         "background to what the scene's own line describes. A chained spot shoots "
         "its scenes in order, each from a frame, her still for the first and the last frame of "
         "the scene before for the rest, and reads each back before the next is sent. The "
         "narration is drawn three times and has to say the script",
         "Recorded, each scene that failed to come back, came back as someone else or broke its continuity sent once more, "
         "and a request that may have been billed stops for a person",
         "every request and landing ledgered", "shoots/<batch>/*.jsonl", "process"),
    Step("closer", "Closer",
         "Identity pin on the voice and avatar ids before anything is paid for, the voice "
         "included, then the jaw measured on the raw render and refused over 0.17, and the render refused when "
         "a patch behind the narrator moves over 600 px between two frames or sits 1500 px off the clip's median",
         "Stops the run, a new look is needed",
         "identity pin, jaw under 0.17", "guards/, gates/jaw_gate.py", "process"),
    Step("build", "Build",
         "The scenes cut to the narration's sentences, a sentence that holds more than one shot "
         "getting them joined in order first, the closer and its captions placed after them, and "
         "the master normalised toward -16 LUFS",
         "Stops the run",
         "cut to the words, then mastered", "shoots/build-ad.sh, master.sh", "process"),
    Step("ad_gates", "Ad gates",
         "Every burned cue says what is spoken, within 0.5 s before or 0.3 s after its first "
         "word. The closer's video starts within 40 ms of its audio, and its mouth moves with it",
         "A REVIEW, a lag or a prop the edge probe saw cut goes to the eye. A caption or "
         "placement fault stops for a person, and so does a mouth that does not track",
         "captions say what is spoken", "gates/ad_gates.sh", ("outcome", "quality")),
    Step("ship_gate", "Ship gate",
         "Loudness within a decibel of -16 LUFS and true peak under -1.5 dB, and the frame "
         "fills its height. A directional scene or a replay goes to the eye to read. Exit 64 "
         "on unreadable input",
         "Fails closed and stops the run",
         "loudness, peak, fails closed", "guards/ship_gate.sh", "process"),
    Step("deliver", "Deliver",
         "Reached only after the ship gate passes. The delivery, and any later withdrawal with "
         "its reason, goes on the record",
         "Reviewed after, and a withdrawal goes back to the step that fixes it",
         "withdrawn and replaced on record", "shoots/<batch>/landings.jsonl", "process"),
)

BY_NODE = {s.node: s for s in STEPS}
TITLES = [s.title for s in STEPS]
