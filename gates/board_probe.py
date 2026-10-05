#!/usr/bin/env python3
"""board_probe.py <boards.json> [--json]: gate a board on the escalating-puzzle law before spending.

Mechanical half only. Checks, per spot:
  product_absent   the brand name appears in no scene description before the final beat
  escalation       the board declares how beat B makes it worse (an 'escalation' field, or beat B text
                   that does not resolve: no 'then', 'so', 'fixes', 'solves', 'calm' resolution words)
  quirk_unspoken   no distinctive word from the declared quirk appears in the narration
  mouths_closed    every scene pins mouths closed / nobody speaks
  crop_clause      the guard carries the middle-third composition clause
  cast             every person in a scene is the story's character, written {character} where she
                   appears, so the render can hold her face from scene to scene. A person named any
                   other way ("a student", or "her" with no {character} in the scene) is drawn fresh
                   by the engine each time, and {presenter} never appears in a scene, since the
                   narrator is only in the closer.
  register         the narration talks to the viewer, never about the character: no he, she, his,
                   her, him or hers in it. "Your studio apartment is smaller than the problem you're
                   solving", never "Her studio apartment is smaller than the problem she's solving"
                   (the doctrine, this repo's own written rule for how a spot must be written,
                   gives this exact example, 2026-08-29).
  chain            a spot that shoots its scenes as a chain, each from the last frame of the one
                   before, names real scenes in its 'chain', each once, and a chained scene that
                   writes {character} has a 'character_noun' to name her by. A spot with no chain
                   passes.
  slots            a spot that gives a narration sentence more than one shot lists its 'slots', one
                   for each of the three sentences shoots/build-ad.sh cuts the narration into (it
                   merges any beyond three, and it cannot cut fewer), each holding the shots that
                   play under that sentence in order. Every scene is in exactly one slot, and a
                   chained scene plays in the chain's order. A spot with no slots passes, one scene
                   to a sentence as before.
  switches         where the build plays the switching sound, when a spot says: slots (under the
                   narration's sentence boundaries, the default), off, or cuts (where the picture
                   changes most). Any other value fails, since the build would refuse it after the
                   spend. A spot that does not say passes.
  props            what every shot has to hold from its first frame to its last, when a spot names
                   any: a list of lines, each a thing in plain words ("an open laptop on the desk"),
                   none blank and none twice. The render reads every shot back against them with
                   gates/continuity_gate.py, so a malformed list would be a question nobody can
                   answer, asked after the spend. A spot that names none passes.
  hook_first       the spot names its hook scene in a 'hook' field, and the film opens on it. The
                   first shot is the first entry of 'order' if the spot has one, else of 'chain',
                   else the first shot of the first slot, else the first scene key. shoots/build-ad.sh
                   reads neither 'order' nor 'chain' for the cut. It plays each slot's shots in turn,
                   or with no slots the first three scene keys, a, b and c, one to each sentence. So an
                   'order' that lists the shots any other way fails, and so does a 'chain' that opens
                   on any other shot: the film would not play as the board says. A spot with no 'hook'
                   fails, and the reason says what to add.
The four judgment rows (hook, realism, absurdity, logic) are printed as questions for the eye. A spot
can carry its answers as 'scores', a whole number from 0 to 3 for each row, with 'scored_by' naming
who scored them. They are reported beside the checks, with each row that is missing, not a whole
number from 0 to 3, or under 2 named as unmet, and scored_by when it names nobody. They never change
the verdict or the exit code. The graph decides what they hold back (pipeline/toolkit.py), and
pipeline/DOCTRINE.md states the rules behind the hook and the rows.
Exit 0 all pass, 1 any fail.
"""
import json, re, sys

RESOLVERS = ("solves", "fixes", "resolved", "explains", "reveals the product", "everything is fine")

PLACEHOLDER = "{character}"
NARRATOR = "{presenter}"
HUMAN_NOUNS = re.compile(r"\b(woman|women|man|men|girls?|boys?|students?|persons?|people|someone|somebody|"
                         r"child|children|kids?|customers?|friends?|workers?|guys?|lady|ladies|mothers?|"
                         r"fathers?|moms?|dads?)\b")
PRONOUNS = re.compile(r"\b(she|her|hers|he|him|his)\b")
THIRD_PERSON = re.compile(r"\b(she|her|hers|he|him|his)\b", re.IGNORECASE)
SENTENCE_END = re.compile(r"(?<=[.?!])\s+")   # the split shoots/build-ad.sh cuts the narration on
BUILDER_SLOTS = 3                               # and the three sentences it merges them down to

def words(t):
    return set(re.findall(r"[a-z]{5,}", t.lower()))

def cast_ok(text):
    """True when the only person in a scene is the story's character, named by the placeholder."""
    if NARRATOR in text:
        return False
    rest = text.replace(PLACEHOLDER, " ").lower()
    if HUMAN_NOUNS.search(rest):
        return False
    return PLACEHOLDER in text or not PRONOUNS.search(rest)

def register_ok(narration):
    """True when the narration never talks about someone in the third person."""
    return not THIRD_PERSON.search(narration)

def chain_ok(sp, scenes):
    """True when the spot has no chain, or its chain lists its own scenes once each and can name her."""
    chain = sp.get("chain")
    if chain is None:
        return True
    if not isinstance(chain, list) or not chain or len(set(chain)) != len(chain) or any(k not in scenes for k in chain):
        return False
    return bool(sp.get("character_noun")) or not any(PLACEHOLDER in scenes[k] for k in chain)

def sentence_count(narration):
    """How many sentences shoots/build-ad.sh would cut a narration into: every one, merged down to three."""
    return min(len([x for x in SENTENCE_END.split(narration.strip()) if x.strip()]), BUILDER_SLOTS)

def slots_ok(sp, scenes):
    """True when the spot has no slots, or its slots hold its own scenes once each, one slot to each
    of the three sentences the builder cuts the narration into, and a chained scene plays in the
    chain's order. The builder reads three sentence windows, so a narration of fewer cannot hold slots."""
    slots = sp.get("slots")
    if slots is None:
        return True
    if not isinstance(slots, list) or not slots or any(not isinstance(s, list) or not s for s in slots):
        return False
    flat = [k for s in slots for k in s]
    if sorted(flat) != sorted(scenes):   # every scene, each exactly once
        return False
    if len(slots) != BUILDER_SLOTS or sentence_count(sp.get("narration", "")) != BUILDER_SLOTS:
        return False
    chain = sp.get("chain")
    return not isinstance(chain, list) or [k for k in flat if k in chain] == chain

# The modes shoots/switches.sh knows. pipeline/toolkit.py carries the same tuple, and a test holds
# the three together, since a gate that knew a mode the build does not would pass a board the build
# then refuses.
SWITCHES = ("slots", "off", "cuts")

def switches_ok(sp):
    """True when the spot leaves the switching sound at the build's default or names a mode it knows."""
    return "switches" not in sp or sp["switches"] in SWITCHES

def props_ok(sp):
    """True when the spot names no props, or names each one once as a line of plain words."""
    props = sp.get("props")
    if props is None:
        return True
    if not isinstance(props, list) or not props or any(not isinstance(p, str) or not p.strip() for p in props):
        return False
    return len({p.strip().lower() for p in props}) == len(props)

# Where a spot's first shot comes from, in the words a reason uses.
OPENED_BY = {"order": "the first entry of its order", "chain": "the first entry of its chain",
             "slots": "the first shot of its first slot", "scenes": "its first scene key"}

def listed(seq, scenes):
    """True when seq lists the spot's own scenes, at least one, each once."""
    return (isinstance(seq, list) and bool(seq) and all(isinstance(k, str) and k in scenes for k in seq)
            and len(set(seq)) == len(seq))

def first_slot_shot(sp, scenes):
    """The first shot of the spot's first slot, when that is one of its scenes."""
    slots = sp.get("slots")
    if isinstance(slots, list) and slots and isinstance(slots[0], list) and slots[0]:
        shot = slots[0][0]
        if isinstance(shot, str) and shot in scenes:
            return shot
    return None

def opener(sp, scenes):
    """(the shot the board opens the film on, where the board says so): the first entry of 'order' if the
    spot has one, else of 'chain', else the first shot of the first slot, else the first scene key. A chain
    whose first entry is not one of the spot's scenes is left to the chain check, and the next source answers."""
    for field in ("order", "chain"):
        seq = sp.get(field)
        if isinstance(seq, list) and seq and isinstance(seq[0], str) and seq[0] in scenes:
            return seq[0], field
    shot = first_slot_shot(sp, scenes)
    if shot:
        return shot, "slots"
    keys = sorted(scenes)
    return (keys[0], "scenes") if keys else (None, None)

def played_first(sp, scenes):
    """(the shot the build plays first, how it picks it). shoots/build-ad.sh plays a sentence's shots in the
    slot's order, and with no slots it plays scenes a, b and c in turn, the first scene key."""
    shot = first_slot_shot(sp, scenes)
    if shot:
        return shot, "the first shot of the first slot"
    keys = sorted(scenes)
    return (keys[0] if keys else None), "the first scene key, since the spot has no slots"

def play_order(sp, scenes):
    """(every shot the build plays, in order, how it picks them), or (None, None) when the slots are too
    malformed to say, which the slots check reports. shoots/build-ad.sh cuts the narration into three
    sentences and reads neither 'order' nor 'chain' for the cut: it plays each slot's shots in turn, or with
    no slots one scene to each sentence, the first three scene keys, a, b and c."""
    slots = sp.get("slots")
    if not slots:
        return sorted(scenes)[:BUILDER_SLOTS], "the first three scene keys, one to each sentence"
    if isinstance(slots, list) and all(isinstance(s, list) and s and all(isinstance(k, str) and k in scenes for k in s)
                                       for s in slots):
        return [k for s in slots for k in s], "each slot's shots in turn"
    return None, None

def hook_first(sp, scenes):
    """(True, None) when the spot names its hook scene and the film opens on it, else (False, what to change).
    An 'order' is the board's word on how the film plays, and the build never reads it, so it has to be the
    order the build plays, every entry of it and not only the first. A 'chain' is the order the scenes are
    shot in, which the slots check holds to the order they play in when the spot has slots, so only its
    first entry is read here, as the shot the board opens on."""
    if "order" in sp:
        if not listed(sp["order"], scenes):
            return False, "order has to list this spot's own scenes, each once, in the order the film plays them"
        played, how = play_order(sp, scenes)
        if played is not None and sp["order"] != played:
            return False, (f"order lists {', '.join(sp['order'])}, but the build plays {', '.join(played)}, {how}. "
                           "List the shots in the order the build plays them")
    first, where = opener(sp, scenes)
    hook = sp.get("hook")
    if hook is None or (isinstance(hook, str) and not hook.strip()):
        if first is None:
            return False, 'add "hook", naming the scene that opens the film'
        return False, f'add "hook": "{first}", naming the scene that opens the film'
    if not isinstance(hook, str) or hook not in scenes:
        return False, f"hook names {hook!r}, which is not one of this spot's scenes ({', '.join(sorted(scenes))})"
    if hook != first:
        return False, (f"hook names scene {hook}, but the film opens on scene {first}, {OPENED_BY[where]}. "
                       "Open the film on the hook, or name the scene it opens on")
    built, how = played_first(sp, scenes)
    if built != first:
        return False, (f"the board opens the film on scene {first}, {OPENED_BY[where]}, but the build plays scene "
                       f"{built} first, {how}, so the film would not open on the hook. Make the two agree")
    return True, None

# The four judgment rows, as the eye reads them. pipeline/DOCTRINE.md quotes these lines word for word,
# and a test holds the two together.
JUDGMENT_ROWS = (
    ("hook", "something is wrong in the first second and you cannot look away"),
    ("realism", "the frame would pass as documentary footage with the sound off"),
    ("absurdity", "the BEHAVIOR is impossible, played completely straight, never the rendering"),
    ("logic", "the product closes the puzzle, obvious afterward and invisible before"),
)
SCORE_TOP = 3     # each row is scored 0 to 3
SCORE_PASS = 2    # and every row has to reach this

def scores_of(sp):
    """A spot's judgment rows as it scores them, who scored them, and what is still unmet: each row that is
    missing, not a whole number from 0 to 3, or under 2, and scored_by when it names nobody. Only a row
    that is a whole number from 0 to 3 is reported as scored. A true or false is not a number here."""
    given = sp.get("scores")
    given = given if isinstance(given, dict) else {}
    rows, unmet = {}, {}
    for name, _ in JUDGMENT_ROWS:
        value = given.get(name)
        if name not in given:
            unmet[name] = "missing"
        elif isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= SCORE_TOP:
            unmet[name] = f"not a whole number from 0 to {SCORE_TOP}"
        else:
            rows[name] = value
            if value < SCORE_PASS:
                unmet[name] = f"under {SCORE_PASS}"
    record = {"rows": rows}
    who = sp.get("scored_by")
    if isinstance(who, str) and who.strip():
        record["scored_by"] = who.strip()
    else:
        unmet["scored_by"] = "missing"
    record["unmet"] = unmet
    return record

def main():
    args = [a for a in sys.argv[1:] if a != "--json"]
    as_json = "--json" in sys.argv[1:]
    b = json.load(open(args[0]))
    spots = b.get("spots", {})
    guard = b.get("guard", "")
    # An empty board printed PASS (0 spots). Nothing inspected is not a pass.
    if not spots:
        if as_json:
            print(json.dumps({"verdict": "FAIL", "reason": "0 spots: nothing to inspect", "spots": {}}))
        else:
            print("BOARD PROBE FAIL (0 spots: nothing to inspect)")
        return 1
    fails = []
    rows = []
    for ad, sp in spots.items():
        brand = sp.get("brand", ad)
        scenes = sp.get("scenes", sp.get("new_scenes", {}))
        keys = sorted(scenes)
        early = " ".join(scenes[k] for k in keys[:-1]).lower()
        product_absent = brand.lower() not in early
        beat_b = scenes.get(keys[1], "").lower() if len(keys) > 1 else ""
        escalation = bool(sp.get("escalation")) or not any(r in beat_b for r in RESOLVERS)
        quirk = sp.get("quirk", "")
        narration = sp.get("narration", "")
        shared = words(quirk) & words(narration)
        shared -= {"still", "again", "behind", "front", "never", "every", "their", "there", "which", "while"}
        quirk_unspoken = not shared
        closed = all(("mouth" in s.lower() and "closed" in s.lower()) or "nobody speaks" in s.lower() for s in scenes.values())
        crop = "middle third" in guard.lower()
        cast = all(cast_ok(s) for s in scenes.values())
        register = register_ok(narration)
        hooked, hook_why = hook_first(sp, scenes)
        checks = {"product_absent": product_absent, "escalation": escalation, "quirk_unspoken": quirk_unspoken,
                  "mouths_closed": closed, "crop_clause": crop, "cast": cast, "register": register,
                  "chain": chain_ok(sp, scenes), "slots": slots_ok(sp, scenes), "switches": switches_ok(sp),
                  "props": props_ok(sp), "hook_first": hooked}
        # What to change, for a failed check that can say. The scores ride beside the checks and never
        # decide this verdict.
        why = {"hook_first": hook_why} if hook_why else {}
        bad = [k for k, v in checks.items() if not v]
        if bad: fails.append((ad, bad, sorted(shared)))
        rows.append({"spot": ad, "checks": checks, "shared": sorted(shared), "why": why, "scores": scores_of(sp)})
    # --json was advertised in this file's own usage line for weeks and never parsed, so a
    # caller asking for it got the text report. The graph (the LangGraph state machine that
    # runs the whole pipeline) has a board node that reads this.
    if as_json:
        print(json.dumps({"verdict": "FAIL" if fails else "PASS",
                          "spots": {r["spot"]: {"checks": r["checks"], "quirk_words_in_narration": r["shared"],
                                                "why": r["why"], "scores": r["scores"]} for r in rows}}))
        return 1 if fails else 0
    for r in rows:
        state = " ".join(("+" if v else "!") + k for k, v in r["checks"].items())
        print(f"  {r['spot']:12s} {state}" + (f"   quirk words in narration: {', '.join(r['shared'])}" if r["shared"] else ""))
        for check, text in r["why"].items():
            print(f"  {'':12s} {check}: {text}")
    print(f"\nJudgment rows, score each 0-{SCORE_TOP}, all must reach {SCORE_PASS} (the eye rules):")
    for name, text in JUDGMENT_ROWS:
        print(f"  {name:10s} {text}")
    print("\nThe scores each spot carries for them, which a live run needs before it spends:")
    for r in rows:
        s = r["scores"]
        given = ", ".join(f"{k} {v}" for k, v in s["rows"].items()) or "none"
        unmet = "; unmet: " + ", ".join(f"{k} {v}" for k, v in s["unmet"].items()) if s["unmet"] else ""
        by = f", by {s['scored_by']}" if s.get("scored_by") else ""
        print(f"  {r['spot']:12s} {given}{by}{unmet}")
    print(f"\nBOARD PROBE {'FAIL' if fails else 'PASS'} ({len(rows)} spots)")
    return 1 if fails else 0

if __name__ == "__main__":
    sys.exit(main())
