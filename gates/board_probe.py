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
                  "mouths_closed": closed, "crop_clause": crop, "cast": cast, "register": register}
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
