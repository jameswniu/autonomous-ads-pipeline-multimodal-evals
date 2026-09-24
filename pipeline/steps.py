"""The seven steps of the pipeline, declared once.

Every surface that names or describes a step reads this list. `pipeline/graph.py`
builds its nodes from it, `tools/render_map.py` draws the system map from it, and
the tests hold the step table in docs/TIERS.md and the Mermaid diagram in the
README to it, word for word. Before this file existed those three surfaces were
only checked against each other, so all three could agree and all three could be
wrong about what the code did, which is what had happened: the table said the
ship gate checked loudness when nothing did.

This module imports nothing from langgraph, so the map generator and the tests
that only need the names do not need the orchestration dependency.
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


STEPS = (
    Step("board", "Board",
         "Five mechanical checks, free, before a cent is spent (the product absent before the "
         "payoff, the escalation declared, the quirk never spoken by the narration, mouths closed "
         "under narration, the centre-crop clause present). The four judgment rows it prints are "
         "scored when the board is written, before a run starts",
         "The board goes back",
         "five mechanical checks, four eye rows", "gates/board_probe.py", "process"),
    Step("render", "Render",
         "Every request and every landing appended to the ledger, the vendor's own rejection "
         "text included, and every scene read by the edge probe. The narration is drawn three "
         "times and has to say the script",
         "Recorded, each scene that failed to come back sent once more, and a request that may have been billed stops for a person",
         "every request and landing ledgered", "shoots/<batch>/*.jsonl", "process"),
    Step("closer", "Closer",
         "Identity pin on the voice and avatar ids before anything is paid for, the voice "
         "included, then the jaw measured on the raw render and refused over 0.17",
         "Stops the run, a new look is needed",
         "identity pin, jaw under 0.17", "guards/, gates/jaw_gate.py", "process"),
    Step("build", "Build",
         "The scenes cut to the narration's sentences, the closer and its captions placed after "
         "them, and the master normalised toward -16 LUFS",
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
