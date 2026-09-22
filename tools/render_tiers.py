#!/usr/bin/env python3
"""Generate the README hero, assets/evals-three-tiers.svg, from the tier data.

    python3 tools/render_tiers.py --write    rewrite the committed file
    python3 tools/render_tiers.py --check    exit 1 if the committed file differs

WHY THIS EXISTS. The figure was drawn by a generator that lived outside this
repository, so regenerating it meant running a private tree, and a retired claim
could have come back with nothing here to notice. tests/test_suite.py already
claimed this file existed and byte-checked the SVG, which it did not, for weeks.

The aria-label is BUILT FROM THE SAME TIER TUPLES as the visible text, which is
the real point rather than a nicety. The accessible text and the pixels have
disagreed here before, and fixing the visible half while leaving the aria-label
is not fixing it. There is now no way to change one without the other.

GitHub renders this file as an <img>, so the alt on that tag is what a screen
reader actually reads and the aria-label inside the SVG never gets there. The
README alt is therefore the SAME sentence, printed by --alt and asserted equal
in tests. Two accessible texts for one figure is how one of them goes stale.
"""
import argparse
import html
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "assets", "evals-three-tiers.svg")

W, H = 1200, 460
FONT = "-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif"
INK, DIM, GOLD, CARD, EDGE, BG = "#e6e6ec", "#9a9ca3", "#c9a86a", "#202024", "#5f626a", "#18181c"

TITLE = "How do you craft evals?"
SUB = "Split the question in three. Each tier answers to its own source of truth."
FOOT = "label   then   derive   then   gate   then   render   then   relabel"

# label, the question it answers (two lines), its source of truth, how that source moves
TIERS = [
    ("PROCESS EVALS", ("Did every step run,", "and did its gate fire?"),
     "the pipeline graph", "fixed by the scripts"),
    ("OUTCOME EVALS", ("Is what shipped", "true to the facts?"),
     "the research pass", "re-derived per brief"),
    ("QUALITY EVALS", ("Does it meet the bar", "for this audience?"),
     "the golden set", "re-derived per audience"),
]


def text(x, y, s, size, fill, weight=None, spacing=None):
    # Escaped, because an unescaped & or < in a tier line produces a malformed SVG
    # that --check happily accepts: it compares this output against a committed copy
    # of the same broken output, so the two agree and CI stays green on a broken
    # asset. The escape is what makes the byte check mean anything.
    a = f'<text x="{x}" y="{y}" text-anchor="middle" font-family="{FONT}" font-size="{size}"'
    if weight:
        a += f' font-weight="{weight}"'
    if spacing:
        a += f' letter-spacing="{spacing}"'
    return f'{a} fill="{fill}">{html.escape(str(s), quote=False)}</text>'


def aria():
    """One sentence per tier, from the same tuples the cards are drawn from."""
    parts = [TITLE, SUB.replace(" Each tier answers to its own source of truth.", "")]
    for label, (q1, q2), truth, how in TIERS:
        name = label.title().replace("Evals", "evals")
        parts.append(f"{name}: {q1[0].lower() + q1[1:]} {q2} "
                     f"Source of truth, {truth}, {how}.")
    return " ".join(p.strip() for p in parts if p.strip())


def render():
    o = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
         f'viewBox="0 0 {W} {H}" role="img"',
         f' aria-label="{html.escape(aria(), quote=True)}">',
         "  <defs>",
         '    <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">',
         f'      <stop offset="0%" stop-color="{BG}"/><stop offset="55%" stop-color="{BG}"/>'
         f'<stop offset="100%" stop-color="{BG}"/>',
         "    </linearGradient>",
         "  </defs>",
         f'  <rect width="{W}" height="{H}" fill="url(#bg)"/>',
         f'  <rect x="0" y="0" width="{W}" height="3" fill="{GOLD}" opacity=".9"/>',
         "",
         "  " + text(W // 2, 76, TITLE, 50, INK, weight="700"),
         "  " + text(W // 2, 118, SUB, 27, DIM),
         ""]

    for i, (label, (q1, q2), truth, how) in enumerate(TIERS):
        x = 40 + i * 380
        mid = x + 182
        o += [f'  <rect x="{x}" y="150" width="360" height="242" rx="8" fill="{CARD}" '
              f'fill-opacity="1" stroke="{EDGE}"/>',
              f'  <rect x="{x}" y="150" width="7" height="242" rx="0" fill="{GOLD}"/>',
              "  " + text(mid, 192, label, 25, GOLD, weight="700", spacing="2"),
              "  " + text(mid, 234, q1, 25, INK, weight="700"),
              "  " + text(mid, 264, q2, 25, INK, weight="700"),
              "  " + text(mid, 306, "SOURCE OF TRUTH", 23, DIM, spacing="1.5"),
              "  " + text(mid, 338, truth, 27, INK, weight="700"),
              "  " + text(mid, 372, how, 24, GOLD),
              ""]

    o += ["  " + text(W // 2, 432, FOOT, 23, DIM), "</svg>"]
    return "\n".join(o) + "\n"


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--alt", action="store_true")
    a = ap.parse_args()
    if a.alt:
        print(aria())
        raise SystemExit(0)
    svg = render()
    rel = os.path.relpath(OUT, ROOT)
    if a.write:
        open(OUT, "w").write(svg)
        print("wrote", rel)
    elif a.check:
        cur = open(OUT).read() if os.path.exists(OUT) else ""
        if cur != svg:
            print(f"{rel} differs from its generator; run --write")
            sys.exit(1)
        print(f"{rel} matches its generator")
    else:
        sys.stdout.write(svg)
