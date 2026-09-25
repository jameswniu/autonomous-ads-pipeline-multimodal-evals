#!/usr/bin/env python3
"""One text normaliser, shared by the two gates that compare words to words.

`script_match.sh` compares the STT read-back against the script. `caption_gate.py` compares each
burned caption against the words spoken under it. Both need the same thing: a spoken line and a
written line that mean the same must compare equal, and two that differ must not. This lived
inside a bash heredoc where only one of them could reach it, so the caption gate compared raw
letters, stripped every digit, and passed "Only $199" against spoken "$999" (2026-09-21).

What it does, in order: straightens quotes, turns $1,000 into 1000 dollars, turns 3:30 into 3 30,
drops punctuation, and folds spoken number words into digits, so "a thousand" and "1,000" and
"one thousand" all read 1000 while "one two" stays two separate numbers.

Two documents whose letters, digits and in-word apostrophes run the same in order, and whose
words differ only where punctuation splits one, also say the same thing: a script's "Z.ai" read
back as "ZAI", or "e-mail" as "email". The doctrine ruled that way from the start ("hyphen
tokenization diffs are fine"), and the Z.ai narration failed its read-back twice on nothing else
(2026-09-25). An apostrophe inside a word counts, so "we're" is not "were". A split made by a space
is a different reading, "now here" is not "nowhere", and a boundary between two digits is where one
number ends and the next begins, so "one two" read back as 12 still differs.

As a CLI it compares two documents:  python3 textnorm.py <a.json|txt> <b.json|txt>
  exit 0 they say the same thing, 1 they differ (the diff is printed), 3 nothing was compared.
"""
import json,re,sys
def load(p):
    raw=open(p,encoding="utf-8").read()
    if p.endswith(".json"):
        d=json.loads(raw)
        return d.get("text") or d.get("script") or raw
    return raw
UNITS={"zero":0,"one":1,"two":2,"three":3,"four":4,"five":5,"six":6,"seven":7,"eight":8,"nine":9,
"ten":10,"eleven":11,"twelve":12,"thirteen":13,"fourteen":14,"fifteen":15,"sixteen":16,
"seventeen":17,"eighteen":18,"nineteen":19,"twenty":20,"thirty":30,"forty":40,"fifty":50,
"sixty":60,"seventy":70,"eighty":80,"ninety":90}
SCALES={"hundred":100,"thousand":1000,"million":1000000}
# Punctuation inside a word, between two word characters with no space, as in "z.ai" or "e-mail",
# is marked with GLUE instead of a space, so a comparison can tell a split punctuation made from
# one a space made. The words norm returns are the same either way.
GLUE="\x00"

def norm(t):
    """The words of a text, normalised, the way both gates compare them."""
    return [tok for tok, _ in norm_marked(t)]

def norm_marked(t):
    """norm, with each word paired with whether punctuation rather than a space split it from the word before."""
    t=t.replace("’","'").replace("‘","'").replace("“",'"').replace("”",'"')
    t=t.replace("—"," ").replace("–"," ")
    t=t.lower()
    # currency: $1,000 / $1000 -> 1000 dollars
    t=re.sub(r"\$\s*([\d,]+)", lambda m: m.group(1).replace(",","")+" dollars", t)
    # clock times: 3:00 -> 3 ; 03:30 -> 3 30  pii-allow, documents the normaliser
    t=re.sub(r"\b(\d{1,2}):(\d{2})\b", lambda m: str(int(m.group(1)))+("" if m.group(2)=="00" else " "+str(int(m.group(2)))), t)
    t=re.sub(r"(\d),(\d{3})", r"\1\2", t)
    t=re.sub(r"(?<=[a-z0-9'])[^a-z0-9'\s]+(?=[a-z0-9'])",GLUE,t)
    t=re.sub(r"[^a-z0-9'\s"+GLUE+"]"," ",t)
    w=[]
    glued=[]
    for word in t.split():
        for k,piece in enumerate(x for x in word.split(GLUE) if x):
            w.append(piece)
            glued.append(k>0)
    # Number words to digits. One spoken number is parsed at a time, with scales applied properly
    # and a new number started whenever two bare units meet. The old loop added every adjacent
    # number word together, so "one thousand two hundred" became 100200 and "one two" became 3,
    # the same token as "three" (2026-09-21).
    out=[]
    i=0
    while i<len(w):
        tok=w[i]
        if tok in UNITS or tok in SCALES or (tok=="a" and i+1<len(w) and w[i+1] in SCALES):
            start=i
            if tok=="a":
                i+=1
            total=0
            cur=0
            prev=None
            while i<len(w):
                x=w[i]
                if x in SCALES:
                    if SCALES[x]==100:
                        cur=(cur or 1)*100
                    else:
                        total+=(cur or 1)*SCALES[x]
                        cur=0
                    prev="scale"
                elif x=="and" and prev in ("scale","ten") and i+1<len(w) and (w[i+1] in UNITS or w[i+1] in SCALES):
                    pass
                elif x in UNITS:
                    v=UNITS[x]
                    kind="ten" if v>=20 else ("teen" if v>=10 else "unit")
                    if prev in ("unit","teen") or (prev=="ten" and kind!="unit"):
                        break
                    cur+=v
                    prev=kind
                else:
                    break
                i+=1
            out.append((str(total+cur),glued[start]))
            continue
        out.append((tok,glued[i]))
        i+=1
    return out

def split_only(a, b):
    """True when two marked word lists, from norm_marked, differ only where punctuation splits a word.

    Each side's letters, digits and apostrophes inside a word are read in order, a quote mark
    around a word dropped, and the two must be the same string. Where one side has a word
    boundary the other lacks, that side's text must have had punctuation there and not a space,
    and the boundary must not fall between two digits, because there it separates two numbers."""
    def read(marked):
        joined, cuts = "", {}
        for k, (tok, glued) in enumerate(marked):
            if k:
                cuts[len(joined)] = cuts.get(len(joined), True) and glued
            joined += re.sub(r"[^a-z0-9']", "", tok.strip("'"))
        return joined, cuts

    ja, ca = read(a)
    jb, cb = read(b)
    if ja != jb:
        return False
    for c in set(ca) ^ set(cb):
        if not 0 < c < len(ja):
            continue
        if ja[c - 1].isdigit() and ja[c].isdigit():
            return False
        if not (ca if c in ca else cb)[c]:
            return False
    return True


def compare(p_a, p_b):
    """Exit code for two documents, and print the word diff when they differ."""
    try:
        ma = norm_marked(load(p_a))
        mb = norm_marked(load(p_b))
    except Exception as e:
        print(f"ERROR could not compare: {e}")
        return 3
    a = [tok for tok, _ in ma]
    b = [tok for tok, _ in mb]
    if a == b:
        print("MATCH")
        return 0
    import difflib
    if split_only(mb, ma):
        print("MATCH")
        for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(a=b, b=a, autojunk=False).get_opcodes():
            if tag != "equal":
                print(f"  same words, split differently: {' '.join(b[i1:i2])} / {' '.join(a[j1:j2])}")
        return 0
    print("MISMATCH")
    for d in difflib.unified_diff(b, a, lineterm="", n=1):
        if d.startswith(("+", "-")) and not d.startswith(("+++", "---")):
            print("  " + d)
    return 1


if __name__ == "__main__":
    sys.exit(compare(sys.argv[1], sys.argv[2]))
