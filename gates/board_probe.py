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
                   (the doctrine's own example, 2026-08-29).
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
The four judgment rows (hook, realism, absurdity, logic) are printed as questions for the eye.
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
        checks = {"product_absent": product_absent, "escalation": escalation, "quirk_unspoken": quirk_unspoken,
                  "mouths_closed": closed, "crop_clause": crop, "cast": cast, "register": register,
                  "chain": chain_ok(sp, scenes), "slots": slots_ok(sp, scenes), "switches": switches_ok(sp)}
        bad = [k for k, v in checks.items() if not v]
        if bad: fails.append((ad, bad, sorted(shared)))
        rows.append((ad, checks, sorted(shared)))
    # --json was advertised in this file's own usage line for weeks and never parsed, so a
    # caller asking for it got the text report. The graph's board node reads this.
    if as_json:
        print(json.dumps({"verdict": "FAIL" if fails else "PASS",
                          "spots": {ad: {"checks": checks, "quirk_words_in_narration": shared}
                                    for ad, checks, shared in rows}}))
        return 1 if fails else 0
    for ad, checks, shared in rows:
        state = " ".join(("+" if v else "!") + k for k, v in checks.items())
        print(f"  {ad:12s} {state}" + (f"   quirk words in narration: {', '.join(shared)}" if shared else ""))
    print("\nJudgment rows, score each 0-3, all must reach 2 (the eye rules):")
    print("  hook       something is wrong in the first second and you cannot look away")
    print("  realism    the frame would pass as documentary footage with the sound off")
    print("  absurdity  the BEHAVIOR is impossible, played completely straight, never the rendering")
    print("  logic      the product closes the puzzle, obvious afterward and invisible before")
    print(f"\nBOARD PROBE {'FAIL' if fails else 'PASS'} ({len(rows)} spots)")
    return 1 if fails else 0

if __name__ == "__main__":
    sys.exit(main())
