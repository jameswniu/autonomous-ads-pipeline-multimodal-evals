#!/usr/bin/env python3
"""frontload_gate.py: does a "cuts" build's first big picture change open the film soon enough.

The author's standing rule for a spot: hit all neurons, front-load impact, start with the hook.
The most arresting moment has to open the film, not arrive after it. A "cuts" build already
measures where the picture changes most, shoots/switch_times.py's switch_times, sorted earliest
first, so the first entry is the first big change the build placed a whoosh on, whatever scene
made it.

FRONTLOAD_MAX is 1.75 seconds. Four builds carry a verdict on this: the Grok hook cut the author
picked opened on 0.0, the Perplexity cut approved the night this was written opened on 1.14, the
Z.ai cut the author picked opened on 1.22, and the Grok cut sent back the same night for a slow
open measured 2.3. FRONTLOAD_MAX sits strictly between the slowest of those three passes (1.22)
and the one reject (2.3), roughly centred rather than hugging either edge. No pixels ship behind
these four rows in evals/labels.csv: the shoots that produced them were still being shot when
this was written and their ledgers are not committed to this repository, so each row is attested
from notes, the way most of this suite's labelled rows already are, and evals/derive.py still
counts a threshold DERIVED on that basis, same as it does for the majority of the other nine
gating thresholds in probes/ and gates/.

This only flags, never refuses. A slow open is a board problem: the fix is a different board
next time, not a re-roll of a spot that already rendered and was paid for. So flag() names the
measured time and the limit for a person to read at the eye (a person's review of the cut), and the pipeline decides nothing
from it beyond showing it.

Only a "cuts" build's first switch time means "first big picture change". A "slots" build's
switch_times are narration sentence boundaries and an "off" build has none, so the caller only
asks this of a "cuts" build's own first entry. This file does not know about boards or modes,
only about one number.
"""

FRONTLOAD_MAX = 1.75  # seconds, strictly between the slowest labelled pass (1.22) and the reject (2.3)


def flag(first_switch_s):
    """The eye's flag for a "cuts" build's first placed switch time, in seconds, or None when it
    lands in time or was never measured.

    `first_switch_s` is the earliest entry of a "cuts" build's switch_times. Anything that is
    not a real number, including None (nothing measured) and NaN, never flags: unmeasured is not
    late."""
    try:
        first = float(first_switch_s)
    except (TypeError, ValueError):
        return None
    if first != first:  # NaN
        return None
    if first <= FRONTLOAD_MAX:
        return None
    return f"FRONTLOAD: the first big change lands at {first:.2f}s, later than the {FRONTLOAD_MAX:.2f}s limit. Look before shipping."
