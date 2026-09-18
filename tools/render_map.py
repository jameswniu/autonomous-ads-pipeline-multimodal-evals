#!/usr/bin/env python3
"""Emit assets/system-map.svg from a declared layout, with a text-fit guard.

    python3 tools/render_map.py --write    regenerate the committed file
    python3 tools/render_map.py --check    exit 1 if the committed file differs

The figure is generated rather than drawn so a hand edit cannot drift from the
step list the README's process table carries, and every text run is measured
against its card before the file is written. Text that overflows a card is the
most common defect in a figure like this, and it is invisible until rendered.
"""
import argparse, html, os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "assets", "system-map.svg")
SANS = "-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif"
MONO = "ui-monospace,SFMono-Regular,Menlo,monospace"
PALE, DIM, EDGE, BRASS = "#e6e6ec", "#9a9ca3", "#5f626a", "#c9a86a"
# one accent on the page, so the tier that owns a card is carried by the stroke pattern of its bar
TIER_STYLE = {"process": (BRASS, ""), "outcome": (BRASS, "10 6"), "quality": (BRASS, "3 5")}
SHARED_DASH = "10 4 3 4"  # a gate two tiers own carries dash-dot


def style_of(tier):
    """A step names one tier, or a tuple of the tiers that share its gate."""
    if isinstance(tier, tuple):
        return BRASS, SHARED_DASH
    return TIER_STYLE[tier]
W, H = 1200, 920

STEPS = [
    ("Board", "five mechanical checks, four eye rows", "gates/board_probe.py", "process"),
    ("Render", "every request and landing ledgered", "shoots/<batch>/*.jsonl", "process"),
    ("Closer", "identity pin, prop gate, jaw measured", "guards/, gates/source_gate.py", "process"),
    ("Build", "closer placed within 40 ms", "shoots/build-ad.sh", "process"),
    ("Ad gates", "captions say what is spoken", "gates/ad_gates.sh", ("outcome", "quality")),
    ("Ship gate", "loudness, tail, fails closed", "guards/ship_gate.sh", "process"),
    ("Deliver", "withdrawn and replaced on record", "shoots/<batch>/landings.jsonl", "process"),
]
TIERS = [
    ("PROCESS", "process", ["board probe, pre-spend", "identity pin, prop gate", "closer drift, ship gate"]),
    ("OUTCOME", "outcome", ["captions vs spoken words", "script vs the voice", "claims vs the live page"]),
    ("QUALITY", "quality", ["five probes per audience", "thresholds from labels", "judge flags, eye rules"]),
]

def fits(text, size, box_w, pad=14, bold=False, mono=False):
    k = 0.62 if bold else (0.60 if mono else 0.55)
    need = len(text) * size * k
    if need > box_w - 2 * pad:
        raise SystemExit(f"text overflows its card by {need - (box_w - 2*pad):.0f} units: {text!r}")

def text(x, y, s, size, fill, bold=False, mono=False, anchor="start", spacing=None):
    fam = MONO if mono else SANS
    extra = f' letter-spacing="{spacing}"' if spacing else ""
    weight = ' font-weight="700"' if bold else ""
    return f'<text x="{x}" y="{y}" text-anchor="{anchor}" font-family="{fam}" font-size="{size}"{weight}{extra} fill="{fill}">{html.escape(s)}</text>'

def bar(x, y, h, color, dash):
    """The owner bar on a card: a 5-unit stroke, solid for process, dashed for outcome, dotted for quality, dash-dot when two tiers share it."""
    extra = f' stroke-dasharray="{dash}"' if dash else ""
    return f'<line x1="{x + 2.5}" y1="{y}" x2="{x + 2.5}" y2="{y + h}" stroke="{color}" stroke-width="5"{extra}/>'

def render():
    o = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" role="img" aria-label="System map: one loop of seven steps, board, render, closer, build, ad gates, ship gate, deliver, and the three tiers of evals that own the gates at each step.">',
         '<defs><linearGradient id="bg" x1="0" y1="0" x2="1" y2="1"><stop offset="0%" stop-color="#18181c"/><stop offset="100%" stop-color="#18181c"/></linearGradient></defs>',
         f'<rect width="{W}" height="{H}" fill="url(#bg)"/>', f'<rect x="0" y="0" width="7" height="{H}" fill="{BRASS}"/>']
    o.append(text(60, 58, "SYSTEM MAP", 23, BRASS, bold=True, spacing=3))
    o.append(text(60, 104, "One loop, three tiers of gates", 42, PALE, bold=True))
    o.append(text(60, 140, "Each step hands on a verdict. Money moves only when the tier that owns it says yes.", 23, DIM))
    fits("Each step hands on a verdict. Money moves only when the tier that owns it says yes.", 23, W - 120, pad=0)
    # stat box
    o.append(f'<rect x="{W-480}" y="36" width="420" height="52" rx="8" fill="none" stroke="{EDGE}"/>')
    o.append(text(W - 270, 69, "7 steps  4 guards  10 probes", 23, PALE, anchor="middle"))
    fits("7 steps  4 guards  10 probes", 23, 420)
    # section 01
    o.append(text(60, 196, "01  THE LOOP", 23, BRASS, bold=True, spacing=2))
    o.append(text(282, 196, "left to right, the order it ran", 23, DIM))
    cw, ch, gap, x0 = 533, 100, 14, 60
    for i, (title, detail, foot, tier) in enumerate(STEPS):
        color, dash = style_of(tier)
        row, col = divmod(i, 2)
        x = x0 + col * (cw + gap)
        y = 216 + row * (ch + gap)
        for s, sz, b, m in ((title, 26, True, False), (detail, 24, False, False), (foot, 23, False, True)):
            fits(s, sz, cw, bold=b, mono=m)
        o.append(f'<rect x="{x}" y="{y}" width="{cw}" height="{ch}" rx="8" fill="#202024" fill-opacity="1" stroke="{EDGE}"/>')
        o.append(bar(x, y, ch, color, dash))
        o.append(text(x + 18, y + 34, title, 26, PALE, bold=True))
        o.append(text(x + 18, y + 62, detail, 24, DIM))
        o.append(text(x + 18, y + 88, foot, 23, color, mono=True))
    # section 02
    o.append(text(60, 706, "02  WHO OWNS THE GATE", 23, BRASS, bold=True, spacing=2))
    o.append(text(436, 706, "each tier answers to its own source of truth", 23, DIM))
    tw, th, tx0, ty = 352, 150, 60, 726
    for i, (name, tier, lines) in enumerate(TIERS):
        color, dash = TIER_STYLE[tier]
        x = tx0 + i * (tw + 14)
        o.append(f'<rect x="{x}" y="{ty}" width="{tw}" height="{th}" rx="8" fill="#202024" fill-opacity="1" stroke="{EDGE}"/>')
        o.append(bar(x, ty, th, color, dash))
        fits(name, 25, tw, bold=True)
        o.append(text(x + 18, ty + 36, name, 25, color, bold=True, spacing=2))
        for j, ln in enumerate(lines):
            fits(ln, 24, tw)
            o.append(text(x + 18, ty + 70 + j * 32, ln, 24, PALE))
    o.append(text(W / 2, H - 14, "python3 tools/render_map.py --check   regenerates and compares this figure in CI", 22, DIM, mono=True, anchor="middle"))
    o.append("</svg>")
    return "\n".join(o) + "\n"

if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--write", action="store_true"); ap.add_argument("--check", action="store_true")
    a = ap.parse_args(); svg = render()
    if a.write:
        open(OUT, "w").write(svg); print("wrote", os.path.relpath(OUT, ROOT))
    elif a.check:
        cur = open(OUT).read() if os.path.exists(OUT) else ""
        if cur != svg: print("assets/system-map.svg differs from its generator; run --write"); sys.exit(1)
        print("assets/system-map.svg matches its generator")
    else:
        sys.stdout.write(svg)
