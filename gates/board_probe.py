#!/usr/bin/env python3
"""board_probe.py <boards.json> [--json]: gate a board on the escalating-puzzle law before spending.

Mechanical half only. Checks, per spot:
  product_absent   the brand name appears in no scene description before the final beat
  escalation       the board declares how beat B makes it worse (an 'escalation' field, or beat B text
                   that does not resolve: no 'then', 'so', 'fixes', 'solves', 'calm' resolution words)
  quirk_unspoken   no distinctive word from the declared quirk appears in the narration
  mouths_closed    every scene pins mouths closed / nobody speaks
  crop_clause      the guard carries the middle-third composition clause
The four judgment rows (hook, realism, absurdity, logic) are printed as questions for the eye.
Exit 0 all pass, 1 any fail.
"""
import json, re, sys

RESOLVERS = ("solves", "fixes", "resolved", "explains", "reveals the product", "everything is fine")

def words(t):
    return set(re.findall(r"[a-z]{5,}", t.lower()))

def main():
    b = json.load(open(sys.argv[1]))
    spots = b.get("spots", {})
    guard = b.get("guard", "")
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
        checks = {"product_absent": product_absent, "escalation": escalation, "quirk_unspoken": quirk_unspoken,
                  "mouths_closed": closed, "crop_clause": crop}
        bad = [k for k, v in checks.items() if not v]
        if bad: fails.append((ad, bad, sorted(shared)))
        rows.append((ad, checks, sorted(shared)))
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
