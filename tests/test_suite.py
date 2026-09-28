#!/usr/bin/env python3
"""What a stranger can check without my vendor accounts.

Deliberately narrow. These are not unit tests of the measurements: the numbers
are pinned by evals/labels.csv and checked by evals/derive.py, which this suite
runs. What is tested here is the property the repo kept getting wrong, which is
that a thing can announce failure and still report success.

    python3 -m pytest tests/ -v
    python3 tests/test_suite.py          # same checks, no pytest needed
"""
import ast
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROBES = os.path.join(ROOT, "probes")


def probe_files():
    return sorted(f for f in os.listdir(PROBES) if f.endswith(".py"))


def run(args, timeout=90):
    return subprocess.run([sys.executable] + args, cwd=ROOT, capture_output=True,
                          text=True, timeout=timeout)


# --- the suite compiles ------------------------------------------------------

def test_every_probe_parses():
    """A probe that does not compile cannot be a gate, however good its docstring."""
    for name in probe_files():
        path = os.path.join(PROBES, name)
        with open(path) as fh:
            ast.parse(fh.read(), filename=path)


# --- no entrypoint may crash instead of explaining itself --------------------

def test_no_probe_tracebacks_on_bare_invocation():
    """README claims probes explain themselves with no arguments.

    Four of them used to raise IndexError instead. A traceback is not an
    explanation, so this asserts the absence of one rather than the presence of
    any particular wording.
    """
    broken = []
    for name in probe_files():
        r = run([os.path.join("probes", name)])
        blob = r.stdout + r.stderr
        if "Traceback (most recent call last)" in blob:
            broken.append(f"{name}: traceback on no args")
    assert not broken, "probes crash instead of printing usage: " + "; ".join(broken)


def test_bare_invocation_never_claims_success_while_failing():
    """The failure this repo keeps rediscovering: printing an error, exiting 0.

    A probe with no input has not measured anything. If it exits 0 a shell
    caller reads that as a pass, which is exactly how a missing file becomes a
    silent approval.
    """
    liars = []
    for name in probe_files():
        r = run([os.path.join("probes", name)])
        said_usage = re.search(r"usage[: ]", (r.stdout + r.stderr), re.I)
        if said_usage and r.returncode == 0:
            liars.append(f"{name}: printed usage but exited 0")
    assert not liars, "; ".join(liars)


# --- the derivation is the product ------------------------------------------

def test_derive_runs_clean():
    r = run([os.path.join("evals", "derive.py")])
    assert r.returncode == 0, (
        f"evals/derive.py exited {r.returncode}\n{r.stdout}\n{r.stderr}")


def derive_json():
    r = run([os.path.join("evals", "derive.py"), "--json"])
    return json.loads(r.stdout)


def test_derive_json_shape():
    data = derive_json()
    for key in ("gates", "reproduced", "derived", "authored", "refuted", "n_gating"):
        assert key in data, f"derive --json missing {key}"
    assert data["refuted"] == 0, (
        f"{data['refuted']} threshold(s) sit outside their own labelled interval")
    assert data["derived"] > 0, "no threshold is backed by a labelled pass/reject pair"
    assert data["reproduced"], "no labelled row ships pixels, so nothing is reproducible"
    for row in data["reproduced"]:
        assert row.get("ok"), f"{row['item']} did not reproduce"


WORDS = {1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 6: "six", 7: "seven",
         8: "eight", 9: "nine", 10: "ten", 11: "eleven", 12: "twelve", 13: "thirteen",
         14: "fourteen", 15: "fifteen", 16: "sixteen", 17: "seventeen", 18: "eighteen"}


def test_documented_counts_match_the_tool():
    """EVERY stated count in the docs must equal what derive.py prints.

    An earlier version of this test named six exact strings. That was not enough,
    and an adversarial pass proved it: move the real count, update only the six
    surfaces the test names, and the suite stays green while the README asserts
    five derived plus ten authored out of a total of fifteen that no longer adds
    up, and quotes a line derive.py no longer prints.

    So this scans instead of matching fixed needles. Any sentence anywhere in
    these files that states one of these counts is checked, including ones added
    after this test was written. A pattern with `required` also has to appear at
    least once, so deleting the sentence is not a way to pass.
    """
    data = derive_json()
    d, a, m = data["derived"], data["authored"], data["n_gating"]
    assert d + a == m, (
        f"derive.py is internally inconsistent: {d} derived + {a} authored != {m} gating")
    num = {v: k for k, v in WORDS.items()}

    def val(tok):
        tok = tok.strip().lower()
        return int(tok) if tok.isdigit() else num.get(tok)

    # (regex, tuple of expected values per capture group, required)
    checks = [
        (r"(\w+) of the (\w+) named gating thresholds", (d, m), True),
        (r"and (\d+) of (\d+) named gating thresholds derived", (d, m), True),
        (r"(\d+)%2F(\d+)_derived", (d, m), True),
        (r"(\d+) of (\d+) NAMED gating thresholds are DERIVED", (d, m), True),
        (r"\*\*(\w+) of (\w+)\.\*\*", (d, m), True),
        # Required only while some threshold is still authored; the sentence
        # has no sensible form at zero.
        (r"[Tt]he other (\w+) were typed by hand", (a,), a > 0),
        (r"(\d+) are AUTHORED", (a,), True),
        (r"is one of the (\w+):", (d,), False),
    ]
    problems = []
    for rel in ("README.md", "docs/EVALS.md"):
        text = open(os.path.join(ROOT, rel)).read()
        for pattern, expected, required in checks:
            found = re.findall(pattern, text)
            for hit in found:
                groups = hit if isinstance(hit, tuple) else (hit,)
                got = tuple(val(g) for g in groups)
                if got != expected:
                    problems.append(
                        f"{rel}: {pattern!r} says {got}, derive.py says {expected}")
            if required and not found and rel == "README.md":
                problems.append(f"README.md: no sentence matches {pattern!r}")
    assert not problems, (
        f"derive.py reports {d} derived / {a} authored / {m} gating. "
        + "; ".join(problems))



def test_no_retired_claim_survives_on_any_surface():
    """The landing page is more than README.md, and the rest is not text-diffable.

    Two claims were retired: that every threshold is derived, and that all four
    gates block. Both lived in FIVE places, including an SVG text node and its
    own aria-label twin. Fixing the visible pixels while leaving the accessible
    text is not fixing it.

    This used to matter more than a normal staleness check, because both SVGs
    were written by a generator that was NOT in this repository: regenerating
    from that private tree would have silently restored both claims with nothing
    to notice. tools/render_diagrams.py closes that hole. Both SVGs are
    generated here now and byte-checked in CI.

    This test stays, and not merely out of caution. A retired CLAIM is a
    sentence, not a number, so no count check can see one; and docs/ and
    README.md are written by hand and always will be. This is the check that
    reads the words.
    """
    # Regexes, not substrings. The first version used bare substrings and flagged
    # two correct sentences: "holds each derived constant inside the interval" and
    # a legend line defining which gates block. A staleness check that cries wolf
    # gets muted, so these match the retired CLAIM shapes only.
    retired = [
        (r"every threshold (?:in|comes|derived|is derived)",
         "the count is whatever derive.py prints, and is not all of them"),
        (r"never typed", "ten of the fifteen were typed by hand"),
        (r"each derived from", "not every probe threshold is derived from labels"),
        (r"probes,\s*each derived", "not every probe threshold is derived"),
        (r"(?:\d+|four)\s+blocking\s+(?:gates|guards)", "three of the four fail open"),
        (r"gates,\s*blocking\b", "three of the four fail open"),
    ]
    surfaces = []
    for sub in ("assets", "docs"):
        d = os.path.join(ROOT, sub)
        for f in sorted(os.listdir(d)):
            if f.endswith((".svg", ".html", ".md")):
                surfaces.append(os.path.join(sub, f))
    surfaces.append("README.md")

    hits = []
    for rel in surfaces:
        text = open(os.path.join(ROOT, rel), errors="ignore").read().lower()
        # The README narrates what it USED to say; that sentence is history, not a claim.
        text = text.replace("used to say every threshold was derived and none was", "")
        text = text.replace("this page used to say every threshold", "")
        for pattern, why in retired:
            m = re.search(pattern, text)
            if m:
                hits.append(f"{rel} still says {m.group(0)!r} ({why})")
    assert not hits, "retired claims are back: " + "; ".join(hits)


def test_labelled_pixels_exist():
    """A label pointing at a file that is not in the repo is a claim, not evidence."""
    import csv
    path = os.path.join(ROOT, "evals", "labels.csv")
    with open(path) as fh:
        body = [ln for ln in fh if not ln.lstrip().startswith("#")]
    missing = []
    for row in csv.DictReader(body):
        px = (row.get("pixels") or "").strip()
        if px and px != "withheld" and not os.path.exists(os.path.join(ROOT, px)):
            missing.append(px)
    assert not missing, "labels reference missing files: " + ", ".join(missing)


# --- constants must be live --------------------------------------------------

def test_no_dead_gating_constants():
    """A constant nobody reads still gets read by a human, who then believes it.

    spasm_probe carried FAIL_RATIO and WARN_RATIO long after the gate stopped
    using them, and its docstring described the verdicts they implied. This
    catches the next one mechanically.
    """
    dead = []
    for name in probe_files():
        path = os.path.join(PROBES, name)
        with open(path) as fh:
            tree = ast.parse(fh.read(), filename=path)
        assigned, loaded = {}, set()
        for node in ast.walk(tree):
            # Covers `X = 1` and the annotated `X: float = 1`, which a regex on
            # `^NAME\s*=` silently misses.
            targets = []
            if isinstance(node, ast.Assign):
                targets = [t for t in node.targets if isinstance(t, ast.Name)]
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                targets = [node.target]
            for t in targets:
                if t.id.isupper() and len(t.id) >= 2:
                    assigned.setdefault(t.id, node.lineno)
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
                loaded.add(node.id)
        for const, line in sorted(assigned.items()):
            # AST sees real reads only, so a name that survives merely by being
            # mentioned in a docstring or an f-string no longer counts as used.
            if const not in loaded:
                dead.append(f"{name}:{const}:{line}")
    assert not dead, "assigned but never read: " + ", ".join(dead)


def test_scanner_honours_per_rule_case_flags():
    """A project rule must be able to opt into case-insensitive matching.

    A name is not case-stable in prose. The same identity token gets written
    capitalised, lower, and SHOUTED in a comment, and every project rule ran
    case-SENSITIVE because apply_rule_table never passed the flags argument
    run_rule already accepted. So a rule spelling one capitalisation let the
    others through and reported clean. That is the exact failure this
    repository is about: a check announcing success on input it never examined.

    The negative half carries equal weight. A blanket -i would make the
    built-in identifier rules (tracker keys, chat object ids, both defined as
    uppercase shapes) start matching ordinary lowercase prose, so this asserts
    an unflagged rule stays case-sensitive.

    Line 4 is the word-boundary control. \\b is what keeps a rule from firing on
    every longer word that contains the token, and a scanner whose grep engine
    silently ignores \\b reports a clean audit of nothing.
    """
    script = os.path.join(ROOT, "tools", "pii_scan.sh")
    with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
        rules = os.path.join(tmp, "rules.txt")
        target = os.path.join(tmp, "target.txt")
        with open(rules, "w") as fh:
            # SEVERITY \t CLASS \t LABEL \t REGEX \t FLAGS; absent FLAGS means
            # case-sensitive, which is what every identifier rule relies on.
            fh.write("BLOCKER\tCLASS5-WORKPLACE\tname-any-case\t\\bzebra\\b\t-i\n")
            fh.write("BLOCKER\tCLASS5-WORKPLACE\tid-exact-case\t\\bZQ[0-9]{4}\\b\n")
        with open(target, "w") as fh:
            fh.write("ZEBRA shouted\nzebra lower\nZebra title\n"
                     "zebrafish is a longer word\nZQ1234 identifier\nzq1234 not one\n")
        env = dict(os.environ, PII_CONTEXT_FILE=rules, PII_SCAN_SOFT="1")
        r = subprocess.run(["bash", script, target], cwd=ROOT, env=env,
                           capture_output=True, text=True, timeout=90)
        out = r.stdout + r.stderr
        hits = {}
        for line in out.splitlines():
            parts = line.strip().split(":")
            if len(parts) >= 5 and parts[-1] in ("name-any-case", "id-exact-case"):
                if parts[1].isdigit():
                    hits.setdefault(parts[-1], set()).add(int(parts[1]))
        assert hits.get("name-any-case") == {1, 2, 3}, (
            "a rule carrying -i must match every capitalisation (lines 1, 2, 3) "
            "and must not match the longer word on line 4; got lines "
            f"{sorted(hits.get('name-any-case', []))}\n" + out)
        assert hits.get("id-exact-case") == {5}, (
            "a rule with no flags must stay case-sensitive, or the built-in "
            "uppercase identifier rules start firing on ordinary prose; "
            f"expected only line 5, got {sorted(hits.get('id-exact-case', []))}\n"
            + out)


def test_commit_message_hook_enforces_the_same_table_the_scanner_does():
    """The commit message hook had no test, which is why it failed in silence.

    The rule table grew an optional fifth column. This hook still read four
    fields, so every regex became pattern, tab, flag and matched nothing. It
    kept running and kept printing its banner while passing everything,
    including a message carrying a word the file scanner refuses to publish.
    A gate with no test cannot tell you it has stopped being a gate, and this
    one stayed down for hours before anyone ran it by hand.

    Both directions are asserted, because each has already been wrong once.
    A flagged rule must catch every capitalisation, or a shouted name walks
    through. An unflagged rule must NOT match the wrong case, or a brand name
    that doubles as an ordinary English word turns every honest sentence into
    a finding, and a gate that cries wolf gets bypassed rather than answered.
    """
    hook = os.path.join(ROOT, ".githooks", "commit-msg")
    assert os.access(hook, os.X_OK), "the hook is not executable, so git never runs it"

    with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
        subprocess.run(["git", "init", "-q", tmp], check=True, capture_output=True)
        os.makedirs(os.path.join(tmp, "tools"))
        with open(os.path.join(tmp, "tools", "pii_context.txt"), "w") as fh:
            # FIVE columns on the first rule, FOUR on the second. A hook that
            # reads the wrong number of fields fails one of these two.
            fh.write("BLOCKER\tCLASS5-WORKPLACE\tname-any-case\t\\bzebra\\b\t-i\n")
            fh.write("HIGH\tCLASS5-WORKPLACE\tbrand-exact-case\t\\bZebraCorp\\b\n")

        def run_hook(text):
            msg = os.path.join(tmp, "MSG")
            with open(msg, "w") as fh:
                fh.write(text)
            r = subprocess.run(["bash", hook, msg], cwd=tmp, capture_output=True,
                               text=True, timeout=30)
            return r.returncode, r.stdout + r.stderr

        rc, out = run_hook("Fix the ZEBRA handling in the renderer\n")
        assert rc != 0, ("a rule carrying -i must block every capitalisation; the "
                         "shouted spelling is the one that leaked\n" + out)
        assert "name-any-case" in out, "the finding must name its rule: " + out

        rc, out = run_hook("Fix the zebracorp handling\n")
        assert rc == 0, ("an unflagged rule must not match the wrong case, or an "
                         "ordinary word becomes a finding on every commit\n" + out)

        rc, out = run_hook("Rename a variable and tighten a docstring\n")
        assert rc == 0, "a clean message must pass: " + out

        rc, out = run_hook("Fix the ZEBRA handling\n")
        assert "ZEBRA" not in out, (
            "the hook printed the matched text. A gate that echoes the string "
            "into your terminal has moved it, not caught it:\n" + out)


def _main():
    fns = [(k, v) for k, v in sorted(globals().items())
           if k.startswith("test_") and callable(v)]
    failed = 0
    for name, fn in fns:
        try:
            fn()
            print(f"ok    {name}")
        except AssertionError as exc:
            failed += 1
            print(f"FAIL  {name}\n        {exc}")
        except Exception as exc:                      # noqa: BLE001
            failed += 1
            print(f"ERROR {name}\n        {type(exc).__name__}: {exc}")
    print(f"\n{len(fns) - failed} passed, {failed} failed")
    return 1 if failed else 0



def test_judge_calibration_set_matches_the_rubric():
    """The README quotes 42 scenes, 16 FAIL and 26 PASS, from the judge rubric. The set ships beside it."""
    import json
    rubric = json.load(open(os.path.join(ROOT, "evals", "judge-rubric.json")))
    calib = json.load(open(os.path.join(ROOT, "evals", "judge-calibration.json")))
    entries = [v for v in calib.values() if isinstance(v, list)][0]
    labels = [e["label"] for e in entries]
    assert (len(entries), labels.count("FAIL"), labels.count("PASS")) == (42, 16, 26), labels
    stated = rubric["groundedness"]["calibration"]["set"]
    assert "42" in stated and "16 FAIL" in stated and "26 PASS" in stated, stated



def test_system_map_matches_its_generator():
    """The system map is output, not a drawing. A hand edit to the SVG fails here."""
    r = run(["tools/render_map.py", "--check"])
    assert r.returncode == 0, r.stdout + r.stderr


def test_readme_process_cards_match_the_ledgers():
    """Each redo row on the page, keyed by ad and engine, is what the landings and requests say.

    The last gated master per ad in a batch is the one that shipped. Earlier rows
    are the rebuilds the page counts but does not score.
    """
    import json
    brands = {"orchard": "Orchard Hill Coffee", "lantern": "Lantern Street",
              "harbor": "Harbor Lane Realty", "slowroad": "Slow Road Travel"}
    labels = {"alibaba/wan-3.0/text-to-video": "Wan 3.0",
              "bytedance/seedance-2.0/text-to-video": "Seedance 2.0",
              "google/gemini-omni-flash": "Omni Flash"}
    omni_engine = "google/gemini-omni-flash"

    def rows(batch, name):
        out = []
        for line in open(os.path.join(ROOT, "shoots", batch, name)):
            if line.strip():
                out.append(json.loads(line))
        return out

    def shipped(batch):
        last = {}
        for row in rows(batch, "landings.jsonl"):
            if row.get("kind") == "gated master":
                last[row["ad"]] = row
        return last

    def reading(row):
        mouth = row["mouth"]
        status = mouth.split()[0]
        lag = mouth.split("lag ")[1].split(",")[0].split(";")[0].strip()
        lag = lag.replace("+0.00", "0.00").replace("-0.00", "0.00")
        eye = ", eye approved" if "eye approved" in mouth else ""
        return f"{status}, {lag} s{eye}"

    def version(row):
        return "v" + re.search(r"-final-v(\d+)\.mp4$", row["master"]).group(1)

    def renders(batches, ad, engine):
        return sum(1 for b in batches for r in rows(b, "requests.jsonl")
                   if r["scene"].startswith(ad + "-") and r.get("engine") == engine)

    def table(readme, first_cell):
        block = readme.split("\n| " + first_cell + " |")[1].split("\n\n")[0]
        lines = ("| " + first_cell + " |" + block).split("\n")
        return [[c.strip() for c in line.strip().strip("|").split("|")]
                for line in lines if line.startswith("|") and not line.startswith("|:")]

    winner, omni = shipped("ads5"), shipped("ads6-omni")
    assert sorted(winner) == sorted(omni) == sorted(brands), (sorted(winner), sorted(omni))
    for row in list(winner.values()) + list(omni.values()):
        assert row["captions"] == "PASS 5 cues" and row["drift_ms"] == 0, row
    # the engine behind each ad's winner leg is whatever the last round requested for it
    engines = {}
    for r in rows("ads5", "requests.jsonl"):
        engines[r["scene"].split("-")[0]] = r["engine"]
    rounds = ("ads3", "ads4", "ads5")

    readme = open(os.path.join(ROOT, "README.md")).read()
    orchard = {r[0]: r[1:] for r in table(readme, "Process record, Orchard Hill Coffee")}
    assert orchard["Process record, Orchard Hill Coffee"] == [labels[engines["orchard"]], "Omni Flash"]
    assert orchard["Scene renders in the ledger across the rounds, re-rolls included"] == [
        str(renders(rounds, "orchard", engines["orchard"])),
        str(renders(("ads6-omni",), "orchard", omni_engine))], orchard
    assert orchard["Caption gate on the shipped master"] == ["PASS, 5 cues"] * 2
    assert orchard["Closer video against its audio placement"] == ["0 ms"] * 2
    assert orchard["Mouth sync on the shared closer"] == [reading(winner["orchard"]), reading(omni["orchard"])]
    assert orchard["Master that shipped"] == [version(winner["orchard"]), version(omni["orchard"])]

    others = table(readme, "The other three spots")[1:]
    assert [c[0].split(", ")[0] for c in others] == ["Lantern Street", "Harbor Lane Realty", "Slow Road Travel"], others
    for cells in others:
        brand, engine_label = cells[0].split(", ")
        ad = {v: k for k, v in brands.items()}[brand]
        assert engine_label == labels[engines[ad]], cells
        counts = f"{renders(rounds, ad, engines[ad])} and {renders(('ads6-omni',), ad, omni_engine)}"
        assert cells[1] == counts or cells[1].startswith(counts + ","), (cells, counts)
        assert reading(winner[ad]) == reading(omni[ad]) == cells[2], (cells, winner[ad]["mouth"], omni[ad]["mouth"])
        assert cells[3] == f"{version(winner[ad])} and {version(omni[ad])}", cells


def test_system_map_steps_match_the_process_table():
    """The map and the process table name the same seven steps in the same order."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("render_map", os.path.join(ROOT, "tools", "render_map.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    drawn = [step[0] for step in mod.STEPS]
    readme = open(os.path.join(ROOT, "README.md")).read()
    table = readme.split("| Step | What it has to prove")[1].split("\n\n")[0].split("\n")[2:]
    written = [row.split("|")[1].strip() for row in table if row.startswith("|")]
    assert written == drawn, (written, drawn)



def test_loop_graph_steps_match_the_process_table():
    """The Mermaid loop graph names the same seven steps as the map and the process table, in order."""
    import importlib.util
    import re
    spec = importlib.util.spec_from_file_location("render_map", os.path.join(ROOT, "tools", "render_map.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    drawn = [step[0] for step in mod.STEPS]
    readme = open(os.path.join(ROOT, "README.md")).read()
    graph = readme.split("```mermaid")[1].split("```")[0]
    run = graph.split("subgraph RUN[")[1].split("\n    end")[0]
    title_of = {m.group(1): (m.group(2) or m.group(3)).split(" \u00b7 ")[0] for m in re.finditer(r'(\w+)(?:\["([^"]+)"\]|\{\{?"([^"]+)"\}\}?)', run)}
    # the spine is the one line that chains the steps with arrows, read its ids in order
    spine = max(run.splitlines(), key=lambda l: l.count("-->"))
    ids = re.findall(r'(?:^|-->)\s*(\w+)', spine.strip())
    graphed = [title_of[i] for i in ids]
    assert graphed == drawn, (graphed, drawn)



def test_loop_graph_ownership_matches_the_map():
    """Each step's stroke classes in the graph, and each row of the legend under it, name the tiers the map generator assigns."""
    import importlib.util
    import re
    spec = importlib.util.spec_from_file_location("render_map", os.path.join(ROOT, "tools", "render_map.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    readme = open(os.path.join(ROOT, "README.md")).read()
    graph, after = readme.split("```mermaid")[1].split("```", 1)
    run = graph.split("subgraph RUN[")[1].split("\n    end")[0]
    title_of = {m.group(1): (m.group(2) or m.group(3)).split(" \u00b7 ")[0] for m in re.finditer(r'(\w+)(?:\["([^"]+)"\]|\{\{?"([^"]+)"\}\}?)', run)}
    spine = max(run.splitlines(), key=lambda l: l.count("-->"))
    steps = set(re.findall(r'(?:^|-->)\s*(\w+)', spine.strip()))
    owner = {}
    for ids, tier in re.findall(r"^\s+class ([\w,]+) (process|outcome|quality)\s*$", graph, re.M):
        for node in ids.split(","):
            if node in steps:
                owner.setdefault(title_of[node], set()).add(tier)
    tiers = {title: set(tier) if isinstance(tier, tuple) else {tier} for title, _, _, tier in mod.STEPS}
    assert owner == tiers, (owner, tiers)
    # the stroke words in the legend must be the patterns the classDefs draw
    dash = {name: (m or "").strip() for name, m in re.findall(r"^\s+classDef (\w+) [^\n]*?(?:stroke-dasharray:([\d ]+))?,color", graph, re.M)}
    stroke_of = {"solid": dash["process"], "dashed": dash["outcome"], "dotted": dash["quality"], "dash-dot": dash["shared"]}
    assert stroke_of == {"solid": "", "dashed": "6 3", "dotted": "2 3", "dash-dot": "6 3 2 3"}, stroke_of
    # every legend row names exactly the steps its tier owns
    lines = after.strip().splitlines()
    table = [l for l in lines[: next(i for i, l in enumerate(lines + [""]) if l and not l.startswith("|"))] if l.startswith("|")]
    rows = [[c.strip() for c in l.strip("|").split("|")] for l in table[2:]]
    expected = {
        "1 Process": [t for t in tiers if tiers[t] == {"process"}],
        "2 Outcome": [t for t in tiers if "outcome" in tiers[t]],
        "3 Quality": [t for t in tiers if "quality" in tiers[t]],
        "shared": [t for t in tiers if len(tiers[t]) > 1],
    }
    seen = {}
    for stroke, tier, owns in rows:
        assert stroke.lower() in stroke_of, stroke
        seen[tier if tier[0].isdigit() else tier.lower()] = [t for t in tiers if t in owns]
    assert seen == expected, (seen, expected)
    assert [r[0].lower() for r in rows] == ["solid", "dashed", "dotted", "dash-dot"], rows
    # the edges are the page's own state machine, so their endpoints are pinned too
    edges = {tuple(e) for e in re.findall(r"^\s+(\w+) (?:-->|-\.->)(?:\|\"[^\"]*\"\|)? *(\w+)(?:\[.*\]|\{\{.*\}\})?\s*$", graph, re.M)}
    for pair in [("AG", "EYE"), ("EYE", "SG"), ("D", "L")]:
        assert pair in edges, (pair, sorted(edges))
    # the fail paths ride on the gate labels now, so no loop edge may sneak back in and bend the spine
    assert not {("AG", "R"), ("SG", "BU"), ("L", "B")} & edges, sorted(edges)
    # the invisible twin of the eye exists only to keep the spine straight, it must stay unclassed and unlabeled as a step
    assert re.search(r"^\s+class GH ghost\s*$", graph, re.M), "ghost class"
    assert "GH" not in steps


def _seed_staged_repo(tmp, staged_text, worktree_text, extra=None):
    """A git repo whose index and working tree deliberately disagree.

    The scanner resolves its own repo root from its own location, so the copy
    under test has to live inside the throwaway repo. That is the same shape
    the commit-message hook test uses.
    """
    tools = os.path.join(tmp, "tools")
    os.makedirs(os.path.join(tmp, "docs"))
    os.makedirs(tools)
    shutil.copy2(os.path.join(ROOT, "tools", "pii_scan.sh"),
                 os.path.join(tools, "pii_scan.sh"))

    def git(*args):
        return subprocess.run(["git", "-C", tmp] + list(args),
                              capture_output=True, text=True, check=True)

    subprocess.run(["git", "init", "-q", tmp], check=True, capture_output=True)
    # git does not validate this field, and an address-shaped literal here is
    # a BLOCKER under the scanner's own class 3 rule. Writing one and then
    # suppressing it would be a test file teaching the reader to wave the
    # finding through, so there is simply no address to suppress.
    git("config", "user.name", "zzqa")
    git("config", "user.email", "zzqa")
    git("commit", "-q", "--allow-empty", "-m", "seed")

    target = os.path.join(tmp, "docs", "note.txt")
    with open(target, "w") as fh:
        fh.write(staged_text)
    git("add", "docs/note.txt")
    # The commit is never made. What is staged is what a commit WOULD carry,
    # and the working tree is then moved away from it, which is the whole point.
    with open(target, "w") as fh:
        fh.write(worktree_text)

    for rel, blob in (extra or {}).items():
        path = os.path.join(tmp, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as fh:
            fh.write(blob)
        git("add", rel)
    return os.path.join(tools, "pii_scan.sh")


def _run_staged_scan(script, tmp):
    # The roster library and both local-only inputs are pointed at paths that
    # do not exist, so this test measures the built-in rule table and nothing
    # about the machine it runs on.
    env = dict(os.environ,
               PII_PATTERNS_LIB=os.path.join(tmp, "no-roster.sh"),
               PII_CONTEXT_FILE=os.path.join(tmp, "no-context.txt"),
               PII_NAMES_FILE=os.path.join(tmp, "no-names.txt"))
    return subprocess.run(["bash", script, "--staged"], cwd=tmp, env=env,
                          capture_output=True, text=True, timeout=90)


def test_staged_scan_reads_the_index_not_the_working_tree():
    """A secret staged and then cleaned from the file still has to be blocked.

    --staged took its file names from the index and then read its bytes from
    disk, which are two different things the moment they disagree. Stage a key,
    edit the key out of the file, commit: the gate scanned the cleaned-up tree,
    passed, and the commit carried the key anyway. Nothing exotic is needed to
    reach it. Staging a fix and then continuing to edit is ordinary work, and
    so is `git add -p`, which stages half a file by design.

    Three properties, because each one fails differently:
      1. the staged secret blocks even though the tree is clean
      2. the finding names the repository path, not the temporary snapshot the
         bytes were read from, or the output is unusable in a ticket
      3. a secret that is ONLY in the working tree does NOT block, which is
         what proves the index is being read rather than both
    """
    key = "AKIA" + "QQQQZZZZWWWW1111"

    with tempfile.TemporaryDirectory() as tmp:
        script = _seed_staged_repo(tmp,
                                   staged_text=f"aws_key = {key}\n",
                                   worktree_text="aws_key = redacted\n")
        r = _run_staged_scan(script, tmp)
        out = r.stdout + r.stderr
        assert r.returncode == 1, (
            "a key that is staged but no longer in the file must still block: "
            f"the commit carries the staged blob, not the tree\nexit={r.returncode}\n{out}")
        assert "cloud-access-key-id" in out, (
            "the staged blob was not scanned at all\n" + out)
        assert "docs/note.txt" in out, (
            "the finding must name the repository path\n" + out)
        assert "/staged/" not in out and "pii_scan." not in out.split("===")[-1], (
            "a temporary snapshot path leaked into the report\n" + out)

    with tempfile.TemporaryDirectory() as tmp:
        script = _seed_staged_repo(tmp,
                                   staged_text="aws_key = redacted\n",
                                   worktree_text=f"aws_key = {key}\n")
        r = _run_staged_scan(script, tmp)
        out = r.stdout + r.stderr
        assert r.returncode == 0, (
            "a secret that exists only in the working tree is not being "
            "committed, so --staged must pass. Failing here means the tree is "
            f"still being read.\nexit={r.returncode}\n{out}")


def test_staged_scan_materializes_media_blobs_too():
    """Class 7 reads bytes, so media has to come from the index as well.

    Half a fix is the dangerous kind. If only the text list were rebuilt from
    the index, a staged image would be looked for on disk, not found, and drop
    out of the scan in silence: the file count would say it was examined and
    the media count would say nothing was there. So this stages an image and
    then deletes it from the working tree, and asserts the scanner still has
    one media file to look at.
    """
    png = (b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR"
           + b"\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00"
           + b"\x1f\x15\xc4\x89" + b"\x00" * 64)
    with tempfile.TemporaryDirectory() as tmp:
        script = _seed_staged_repo(tmp,
                                   staged_text="nothing to see\n",
                                   worktree_text="nothing to see\n",
                                   extra={"docs/frame.png": png})
        os.remove(os.path.join(tmp, "docs", "frame.png"))
        r = _run_staged_scan(script, tmp)
        out = r.stdout + r.stderr
        header = [ln for ln in out.splitlines() if ln.startswith("mode=staged")]
        assert header, "the scanner printed no mode line\n" + out
        assert "media=1" in header[0], (
            "a staged image that is no longer on disk must still be read from "
            f"the index, or class 7 quietly examines nothing\n{header}\n{out}")


def test_staged_scan_does_not_skip_names_that_merely_start_with_dots():
    """A leading pair of dots is a filename, not a parent directory.

    Materializing the index needs a guard against a path escaping the snapshot
    root, and the first guard was the glob `..*`, which matches `..env` and
    `..secrets/token` as readily as `../etc`. Those are ordinary legal
    filenames, and a credential in one of them dropped out of the scan without
    a word. A guard that silently excludes real files is worse than no guard,
    because the report still says PASS.
    """
    key = "AKIA" + "QQQQZZZZWWWW1111"
    with tempfile.TemporaryDirectory() as tmp:
        script = _seed_staged_repo(
            tmp, staged_text="clean\n", worktree_text="clean\n",
            extra={"..env": f"aws_key = {key}\n".encode(),
                   "..secrets/token.txt": f"aws_key = {key}\n".encode()})
        r = _run_staged_scan(script, tmp)
        out = r.stdout + r.stderr
        assert r.returncode == 1, (
            "a key in a file whose name begins with dots must block like any "
            f"other\nexit={r.returncode}\n{out}")
        for name in ("..env", "..secrets/token.txt"):
            assert name in out, (
                f"{name} was excluded from the scan by the traversal guard\n" + out)


def test_staged_scan_fails_closed_when_a_blob_cannot_be_read():
    """A file that could not be read has not been scanned, and must not pass.

    Materializing the index introduced a way to lose a file quietly: a full
    disk or a damaged object makes the write fail, the path drops out of the
    list, and the scan happily reports PASS on the smaller set. Nothing
    downstream can tell that the set shrank. So an unreadable staged blob is
    exit 2, the scanner-could-not-run code, which the pre-commit hook already
    treats as a hard stop.

    The damage is real rather than simulated: the blob is staged and then its
    object is removed from the object store, so git genuinely cannot produce
    the bytes the index points at.
    """
    with tempfile.TemporaryDirectory() as tmp:
        script = _seed_staged_repo(tmp,
                                   staged_text="a line of nothing\n",
                                   worktree_text="a line of nothing\n")
        sha = subprocess.run(["git", "-C", tmp, "rev-parse", ":docs/note.txt"],
                             capture_output=True, text=True, check=True).stdout.strip()
        obj = os.path.join(tmp, ".git", "objects", sha[:2], sha[2:])
        assert os.path.exists(obj), "expected a loose object in a fresh repo"
        os.remove(obj)

        r = _run_staged_scan(script, tmp)
        out = r.stdout + r.stderr
        assert r.returncode == 2, (
            "an unreadable staged blob must fail the run rather than shrink "
            f"the set being scanned\nexit={r.returncode}\n{out}")
        assert "RESULT: PASS" not in out, (
            "the scan reported a pass on a set it could not fully read\n" + out)
        assert "docs/note.txt" in out, (
            "the run must name the file it could not read\n" + out)


_GATE_TREES = {}


def _gate_in_a_tree(marker):
    """A copy of the gate in a scratch tools/, with or without the opt-in marker.

    The CI requirement is opt-in and tools/pii_ci_armed is what opts in, so both
    states have to be reachable from a test. Writing the marker into the
    repository to reach the armed one is not an option: that would arm the real
    check as a side effect of running the suite, and the marker is supposed to
    be a decision somebody makes on purpose.

    The gate resolves the marker beside its own file rather than against the
    working directory, which is what makes a scratch tools/ enough. The runs
    below deliberately keep cwd on the repository, so a gate that went back to
    reading `tools/pii_ci_armed` relative to the caller would find the
    repository's own answer and every armed assertion here would break.

    Cached rather than cleaned up, so the whole suite creates at most two of
    these and neither outlives the temp directory it sits in.
    """
    key = bool(marker)
    if key not in _GATE_TREES:
        root = tempfile.mkdtemp(prefix="pii-gate-")
        tools = os.path.join(root, "tools")
        os.makedirs(tools)
        copy = os.path.join(tools, "ci_require_pii_secrets.sh")
        shutil.copy(os.path.join(ROOT, "tools", "ci_require_pii_secrets.sh"), copy)
        if key:
            with open(os.path.join(tools, "pii_ci_armed"), "w") as fh:
                fh.write("")
        _GATE_TREES[key] = copy
    return _GATE_TREES[key]


def _run_gate(script, **over):
    env = {k: v for k, v in os.environ.items()
           if k not in ("PII_CONTEXT", "PII_NAMES", "GITHUB_STEP_SUMMARY")}
    env.update({"IS_FORK": "false", "TARGET_BRANCH": "main",
                "PUBLICATION_BRANCH": "main"})
    env.update(over)
    r = subprocess.run(["bash", script], cwd=ROOT, env=env,
                       capture_output=True, text=True, timeout=30)
    return r.returncode, r.stdout + r.stderr


def test_ci_fails_rather_than_passes_when_the_scanner_secret_is_missing():
    """A green tick that means three of the seven classes never ran.

    The workflow printed "ABSENT ... will be SKIPPED" and exited 0, so a
    repository with no secrets configured showed a passing PII gate forever.
    A skipped check is not a passing check, and that sentence is printed by the
    scanner itself; CI was the one surface that did not act on it.

    All four branches are asserted, because three of them are the ways this
    could be fixed wrongly. Failing on a fork would hand a contributor a red
    check they have no way to clear, since a fork cannot read secrets at all.
    Failing on every working-branch push is how a gate gets routed around.
    Passing when the context is unknown is the original defect wearing a hat.

    Every branch here is about what a MISSING secret means, and since the CI
    requirement became opt-in that question only exists where the marker is. So
    these run against an armed scratch tree. Whether the requirement is on at
    all is the next test.
    """
    script = os.path.join(ROOT, "tools", "ci_require_pii_secrets.sh")
    assert os.path.exists(script), "the decision script is missing"
    armed = _gate_in_a_tree(marker=True)

    def run_gate(**over):
        return _run_gate(armed, **over)

    rc, out = run_gate()
    assert rc != 0, ("a missing secret on the publication branch must fail the "
                     "job, not warn and go green\n" + out)
    assert "FAIL" in out, "the failure must say what it is: " + out

    rc, out = run_gate(PII_CONTEXT="x")
    assert rc != 0, ("one secret present is not both; class 4 names still did "
                     "not run\n" + out)
    assert "PII_NAMES" in out, "the failure must name the missing secret: " + out

    # A real rule, in the shape apply_rule_table actually reads: four fields
    # separated by tabs. Anything looser is not a fixture, it is the bug.
    rule = "HIGH\tCLASS5-WORKPLACE\tproject-word\t\\bzebra\\b\n"
    rc, out = run_gate(PII_CONTEXT=rule, PII_NAMES="Jane Doe")
    assert rc == 0, "both secrets present and usable must pass: " + out
    assert "ARMED" in out, out

    # Present is not armed, in three different ways, each of which reported
    # armed at some point while the scanner activated nothing:
    #   comments only, the template pasted straight in
    #   a bare word, which is not a rule and loads as zero rules
    #   tabs flattened to spaces, which is what a paste through a web form does
    for label, ctx, names in (
        ("comments only", "# one rule per line\n", "# one First Last per line\n"),
        ("a bare fragment", "workplaceword\n", "Jane Doe"),
        ("tabs flattened to spaces",
         "HIGH CLASS5-WORKPLACE project-word \\bzebra\\b\n", "Jane Doe"),
        # Consecutive tabs collapse under the scanner's own IFS read, so the
        # regex field lands empty and the rule is skipped. An awk pass with a
        # tab field separator does not collapse them and called this armed.
        ("an empty middle field", "HIGH\tCLASS5-WORKPLACE\t\t\\bzebra\\b\n", "Jane Doe"),
        # The scanner discards grep's complaint about a bad pattern, so a rule
        # that can never fire looks exactly like one that never matched.
        ("a pattern the engine rejects",
         "HIGH\tCLASS5-WORKPLACE\tproject-word\t[unclosed\n", "Jane Doe"),
        ("a roster of nothing but spaces", rule, "   \n"),
        # The report loops over the four severities and counts them with a
        # literal grep, so a rule written `High` records a hit nothing ever
        # counts, displays, or fails on. An invisible finding is worse than no
        # rule: the operator believes the term is guarded.
        ("a severity in the wrong case",
         "High\tCLASS5-WORKPLACE\tproject-word\t\\bzebra\\b\n", "Jane Doe"),
        # Class and label ride in the colon-delimited output line. The scanner
        # already refuses a path carrying a colon for this reason.
        ("a colon in the label",
         "HIGH\tCLASS5-WORKPLACE\tproject:word\t\\bzebra\\b\n", "Jane Doe"),
        # grep takes these without complaint and each one strips the path and
        # line prefix run_rule reads the finding out of, so the rule matches
        # and reports nothing. Exit status alone called them valid.
        ("a flag that suppresses the output the report is parsed from",
         "HIGH\tCLASS5-WORKPLACE\tproject-word\t\\bzebra\\b\t-q\n", "Jane Doe"),
        # One good rule does not excuse a bad one. A malformed row used to be
        # skipped without being counted, so this pair reported ARMED while half
        # of it did nothing.
        ("one good rule beside one pasted with spaces",
         rule + "HIGH CLASS5-WORKPLACE other-word \\bquagga\\b\n", "Jane Doe"),
        # A roster is not armed because ONE name in it survived. An entry the
        # scanner throws away is a third party the operator believes is
        # guarded and is not, which is worse than never listing them.
        ("a roster entry carrying a digit", rule, "Jane Doe\nAgent 007\n"),
        # The killer. A tab-separated read COLLAPSES a run of tabs, so an empty
        # label shifts every field left: label becomes the regex, regex becomes
        # the flags. Severity, class, label and pattern all look valid, the
        # verdict is ARMED, and the scanner hunts for the string `-i` while the
        # term it was configured to guard walks out. Validating with the same
        # collapsing read the scanner uses cannot see this; only a parser that
        # preserves empty columns can.
        ("an empty label that shifts every field left",
         "HIGH\tCLASS5-WORKPLACE\t\t\\bzebra\\b\t-i\n", "Jane Doe"),
        ("a sixth column", rule.rstrip("\n") + "\t-i\textra\n", "Jane Doe"),
    ):
        rc, out = run_gate(PII_CONTEXT=ctx, PII_NAMES=names)
        assert rc != 0, (
            f"{label} arms nothing, so it must not report armed\n" + out)
        assert "NOTE:" in out, (
            "the operator has to be told the secret is set but useless, which "
            f"is a different repair from not set at all ({label})\n" + out)

    rc, out = run_gate(IS_FORK="true")
    assert rc == 0, ("a fork pull request cannot read secrets, so failing it "
                     "hands a contributor a check they cannot clear\n" + out)
    assert "SKIPPED" in out and "not as a pass" in out, (
        "the fork path must report a skip out loud, or it is the same false "
        "green in a different coat\n" + out)

    # A real roster holds O'Connor and Anne-Marie. Letters and spaces alone
    # dropped both without a word, so the scanner accepts hyphens and
    # apostrophes now and these must arm rather than be silently discarded.
    rc, out = run_gate(PII_CONTEXT=rule,
                       PII_NAMES="Sean O'Connor\nAnne-Marie Doe\n")
    assert rc == 0 and "ARMED" in out, (
        "a hyphen and an apostrophe belong in ordinary names, and refusing "
        "them leaves the person they identify unguarded\n" + out)
    scanner = os.path.join(ROOT, "tools", "pii_scan.sh")
    with open(scanner) as fh:
        assert "*[!A-Za-z\\ \\'-]*" in fh.read(), (
            "the scanner still refuses hyphens and apostrophes, so the gate "
            "would arm a roster the scanner then throws half of away")

    # CRLF is what a secret pasted from a Windows editor or a web form looks
    # like, and the stray carriage return lands in the last field on the line.
    # In the flags field grep rejects it outright, in the regex it can never
    # match, and either way the rule is dead while the scanner says nothing.
    # It is normalized away rather than rejected, in the gate and in the
    # workflow that writes the file, so both are reading the same bytes.
    crlf = "HIGH\tCLASS5-WORKPLACE\tproject-word\t\\bzebra\\b\t-i\r\n"
    rc, out = run_gate(PII_CONTEXT=crlf, PII_NAMES="Jane Doe\r\n")
    assert rc == 0 and "ARMED" in out, (
        "a CRLF secret carries usable rules once the carriage returns are "
        "stripped, and stripping them is the fix\n" + out)
    with open(os.path.join(ROOT, ".github", "workflows", "pii-scan.yml")) as fh:
        wf_text = fh.read()
    assert wf_text.count("| tr -d '\\r' > tools/pii_") == 2, (
        "the workflow writes the secret to disk without stripping carriage "
        "returns, so the scanner reads bytes this gate never validated")

    # The validator has to run the invocation the scanner runs, flags and all.
    # Validating the regex alone left the optional fifth field unexamined, so a
    # rule with unusable flags read as valid here and died silently there.
    with open(script) as fh:
        gate_text = fh.read()
    assert 'grep -a -E $flags -e "$re"' in gate_text, (
        "the gate validates a tidier grep call than run_rule actually makes, "
        "which is how an unusable flags field passes validation")

    rc, out = run_gate(TARGET_BRANCH="a-working-branch")
    assert rc == 0, ("a working branch is not the publication moment; a red "
                     "check on every push is how a gate gets bypassed\n" + out)
    assert "WARNING" in out, out

    rc, out = run_gate(TARGET_BRANCH="", PUBLICATION_BRANCH="")
    assert rc != 0, ("an unknown branch context must fail closed. An unknown "
                     "state is not a safe state.\n" + out)


def test_the_ci_requirement_is_opt_in_and_the_skip_says_what_did_not_run():
    """Three states, and the middle one is why any of this changed.

    Requiring the secrets on the publication branch put a red pii-gate on the
    front page of a public portfolio repository, and the only two ways out were
    both bad. Deleting the requirement is the false green this file spent three
    rewrites killing. Arming it means loading tools/pii_context.txt and
    tools/pii_names.txt into a public repository's Actions secrets, and those
    hold real third-party names, so a finding message quoting what it matched
    would print one into a public workflow log. That is the harm the scanner
    exists to prevent, which makes arming CI a trade rather than a free win.

    So the requirement is opt-in and tools/pii_ci_armed is what opts in. Three
    states, all asserted here, and two of them are the ways this could be fixed
    wrongly. A skip that prints ARMED is the old false green. A skip that says
    nothing about the classes it did not run leaves a reader assuming they ran.
    """
    armed = _gate_in_a_tree(marker=True)
    unarmed = _gate_in_a_tree(marker=False)
    rule = "HIGH\tCLASS5-WORKPLACE\tproject-word\t\\bzebra\\b\n"

    # 1. Opted in, secrets missing, publication branch. Unchanged, and it has to
    #    be: the marker turns the requirement on, it does not soften it.
    rc, out = _run_gate(armed)
    assert rc != 0, (
        "the marker is committed, so a missing secret on the publication "
        "branch must still fail\n" + out)
    assert "FAIL" in out, "the failure must say what it is: " + out

    # 2. Opted in, secrets usable. Passes, and says all seven classes ran.
    rc, out = _run_gate(armed, PII_CONTEXT=rule, PII_NAMES="Jane Doe")
    assert rc == 0 and "ARMED" in out, (
        "an armed scanner under a committed marker is the state the whole "
        "requirement exists to reach\n" + out)

    # 3. Not opted in, secrets missing, publication branch. This is the state
    #    both repositories are actually in, and it is a skip.
    rc, out = _run_gate(unarmed)
    assert rc == 0, (
        "a repository that has not opted in must not be handed a red "
        "publication branch it can only clear by publishing real names\n" + out)
    assert "SKIPPED" in out, (
        "the skip has to be said out loud, or an exit 0 is just the original "
        "false green with the reasoning deleted\n" + out)
    assert "ARMED" not in out, (
        "the skip claims the scanner is armed, which is the exact sentence "
        "this gate was written to stop being printed\n" + out)
    assert "FAIL" not in out, (
        "the skip is reported as a failure, so the red check never went "
        "away\n" + out)

    # And it has to name what did not run. An exit 0 with no inventory reads as
    # a pass to everyone who does not open the log, which is everyone.
    for owed in ("Class 4", "class 5 and 6", ".githooks/pre-commit"):
        assert owed in out, (
            f"the skip does not mention {owed!r}, so a reader cannot tell "
            "which classes were skipped or where they are actually "
            f"enforced\n{out}")

    # The marker governs what a MISSING secret means, not what a present one
    # does. Reordering the branch to answer the marker first would silence a
    # working armed scanner on any repository that had not committed the file.
    rc, out = _run_gate(unarmed, PII_CONTEXT=rule, PII_NAMES="Jane Doe")
    assert rc == 0 and "ARMED" in out, (
        "the secrets are set and usable, so all seven classes ran and the run "
        "must say so whether or not the marker is committed\n" + out)

    # THE OTHER HALF OF THAT SENTENCE, and the first cut of this change got it
    # wrong. A secret somebody SET, that parses to nothing usable, is a broken
    # rule and not an opt-out. The deterministic job materializes it and scans
    # with it whether or not the marker is committed, and the scanner throws
    # away grep's complaint about a pattern it cannot execute, so the rule
    # matches nothing and reports nothing. This gate is the only thing that
    # ever says so, and skipping it on the marker took that away: a stray
    # bracket would have read exactly like a repository that opted out.
    for label, ctx, names in (
        ("a pattern the engine rejects",
         "HIGH\tCLASS5-WORKPLACE\tproject-word\t[unclosed\n", "Jane Doe"),
        ("tabs flattened to spaces",
         "HIGH CLASS5-WORKPLACE project-word \\bzebra\\b\n", "Jane Doe"),
        ("the template pasted straight in", "# one rule per line\n", "Jane Doe"),
        # Half-arming is still somebody trying to arm CI, and one secret has
        # never been both.
        ("only one of the two supplied", rule, ""),
        # AND THE TWO LAYERS HAVE TO AGREE ON WHAT SUPPLIED MEANS. The workflow
        # runs this job when `secrets.PII_CONTEXT != ''`, which reads the value
        # as GitHub holds it, while the gate normalizes first and a command
        # substitution eats trailing newlines. Measure the same value in two
        # places and a secret holding one blank line is supplied up there and
        # absent down here, so the job runs, the gate takes the opt-out branch,
        # and the publication branch goes GREEN with nothing armed.
        ("a secret holding one blank line", "\n", ""),
        ("a secret holding a CRLF blank line", "\r\n", ""),
        ("a secret holding a single space", " ", ""),
    ):
        rc, out = _run_gate(unarmed, PII_CONTEXT=ctx, PII_NAMES=names)
        assert rc != 0, (
            f"{label} was supplied by hand and arms nothing, so the marker "
            "must not excuse it. Nothing supplied is an opt-out; something "
            f"supplied that parses to nothing is a typo nobody would see\n{out}")
        assert "FAIL" in out, (
            f"{label} is not reported as a failure, so the operator keeps "
            f"believing the rule is running\n{out}")

    # Same claim structurally, so a future edit cannot reintroduce the
    # disagreement by moving one line above the other.
    with open(os.path.join(ROOT, "tools", "ci_require_pii_secrets.sh")) as fh:
        supplied_src = fh.read()
    assert 'if [ -n "${PII_CONTEXT:-}" ] || [ -n "${PII_NAMES:-}" ]; then' in supplied_src, (
        "the supplied test reads the normalized values, which have been "
        "through a command substitution and lost their trailing newlines, so "
        "it disagrees with the workflow condition that decides whether this "
        "gate runs at all")

    # The marker question is asked before the branch questions, or a repository
    # that has not opted in would still get a red main and a warning on every
    # working branch, which is the state this change exists to end.
    rc, out = _run_gate(unarmed, TARGET_BRANCH="a-working-branch")
    assert rc == 0 and "SKIPPED" in out and "WARNING" not in out, (
        "an unarmed repository is warned about a requirement it never opted "
        "into. The word SKIPPED alone does not settle this, because the "
        "working-branch warning says the classes are skipped too, so the "
        "warning itself has to be absent\n" + out)

    # Fail-closed on an unknown branch context is a rule about the REQUIREMENT.
    # With the requirement off there is nothing to fail closed about, and
    # failing anyway puts the red check straight back.
    rc, out = _run_gate(unarmed, TARGET_BRANCH="", PUBLICATION_BRANCH="")
    assert rc == 0 and "SKIPPED" in out, (
        "an unknown branch context fails a repository that never asked for "
        "the requirement\n" + out)

    # Resolved beside the script, not against the caller. cwd is the repository
    # in every run above and the repository holds no marker, so a gate reading
    # the marker relative to the working directory would have called states 1
    # and 2 skipped and this whole test would be green for the wrong reason.
    with open(os.path.join(ROOT, "tools", "ci_require_pii_secrets.sh")) as fh:
        gate_text = fh.read()
    assert 'GATE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"' in gate_text, (
        "the marker is resolved against the working directory, so the answer "
        "changes with where the caller happened to stand")


def test_ci_secret_gate_is_actually_wired_into_the_workflow():
    """The script can be perfect and still never run.

    A gate with a test but no caller passes its test and guards nothing, which
    is the failure mode this repository has hit more than once. So the workflow
    is read: it must invoke the script, and it must carry the fork condition
    that turns a fork pull request into a skipped check rather than a green one.
    """
    wf = os.path.join(ROOT, ".github", "workflows", "pii-scan.yml")
    with open(wf) as fh:
        text = fh.read()
    assert "tools/ci_require_pii_secrets.sh" in text, (
        "the workflow does not call the secret gate, so the gate does not run")
    assert "PUBLICATION_BRANCH: ${{ github.event.repository.default_branch }}" in text, (
        "the publication branch is not passed, so the gate cannot tell the "
        "publication moment from an ordinary push")
    # The old wording promised a warning. It described a green check.
    assert "turns that into a visible warning rather than a silent pass" not in text, (
        "the header still describes the behaviour that was the defect")

    # The enforcement has to be its own JOB. A skipped STEP is a line in a log
    # nobody expands; a skipped JOB is a named check reporting SKIPPED in the
    # checks list, which is the only form of "did not run" a human scanning a
    # pull request and a branch rule can both see.
    try:
        import yaml
    except ImportError:
        return
    doc = yaml.safe_load(text)
    assert "armed-context" in doc["jobs"], (
        "the armed check is not a job, so on a fork it is a buried skipped "
        "step inside a green job rather than a check that says it did not run")
    job = doc["jobs"]["armed-context"]
    assert "head.repo.full_name == github.repository" in job.get("if", ""), (
        "the fork condition is gone from the job, so a fork pull request would "
        "run a credentialed check it cannot possibly satisfy")
    runs = " ".join(s.get("run", "") for s in job["steps"])
    assert "ci_require_pii_secrets.sh" in runs, (
        "the armed-context job does not call the gate, so it guards nothing")


def test_an_unarmed_repository_skips_the_job_rather_than_running_a_green_one():
    """Gray, not green, and the difference is a job boundary.

    The script's marker branch exits 0, and an exit 0 inside a job that RUNS is
    a green tick in the checks list. Green reads as "the scan was fine" to
    every visitor who does not open the log, which is the false green this
    whole file is a monument to. A job that does not run reads as "did not
    run", because that is what GitHub draws.

    So the skip has to happen at the job boundary. A job `if:` cannot read the
    tree, because it is evaluated before any checkout and hashFiles() would see
    an empty workspace on every repository, so the answer comes from a small
    job that checks out, looks for the marker, and hands it down as an output.
    """
    wf = os.path.join(ROOT, ".github", "workflows", "pii-scan.yml")
    with open(wf) as fh:
        text = fh.read()
    try:
        import yaml
    except ImportError:
        return
    doc = yaml.safe_load(text)

    gate = doc["jobs"]["armed-context"]
    needs = gate.get("needs")
    needs = [needs] if isinstance(needs, str) else list(needs or [])
    assert needs, (
        "the armed-context job depends on nothing, so it runs on every push "
        "and an unarmed repository is red again")
    arming = needs[0]
    assert f"needs.{arming}.outputs.required" in gate.get("if", ""), (
        "the armed-context job does not gate on the marker, so the skip has "
        "to come from a step exiting 0, which renders green rather than gray")

    # The condition can name an output nothing ever sets. That is not a skip,
    # it is a job that never runs on any repository, armed or not.
    detector = doc["jobs"][arming]
    assert detector.get("outputs", {}).get("required"), (
        f"{arming} declares no required output, so the condition above reads "
        "an empty string and the gate can never run")
    steps = detector["steps"]
    assert any(s.get("uses", "").startswith("actions/checkout") for s in steps), (
        f"{arming} never checks out, so it cannot see whether the marker is "
        "in the tree")
    run_text = "\n".join(s.get("run", "") for s in steps)
    assert "tools/pii_ci_armed" in run_text, (
        f"{arming} decides the arming question without reading the marker")
    assert "required=true" in run_text and "required=false" in run_text, (
        f"{arming} sets only one of the two answers, so one state falls "
        "through to an empty output and the gate silently never runs")

    # A SUPPLIED SECRET HAS TO SWITCH THE CHECK ON TOO. The deterministic job
    # materializes whatever secret exists and scans with it whether or not the
    # marker is committed, and the scanner discards grep's complaint about a
    # pattern it cannot execute, so a rule with a stray bracket in it activates
    # nothing and says nothing. This gate is the only thing that ever notices.
    # Gate it on the marker alone and somebody who sets the secrets and makes a
    # typo reads a gray tick as an opt-out they never made.
    env = "\n".join(str(s.get("env", "")) for s in steps)
    assert "secrets.PII_CONTEXT" in env and "secrets.PII_NAMES" in env, (
        f"{arming} decides on the marker alone, so a secret that is set and "
        "parses to nothing is never checked and the gate that would have "
        "caught it is skipped")
    assert "SECRETS_SUPPLIED" in run_text, (
        f"{arming} reads the secrets into its environment and then ignores "
        "them when it answers")

    # A skipped job draws no log of its own, so the sentence about what did not
    # run has to be printed by the job that DID run. Without it the honest gray
    # check is indistinguishable from a check nobody bothered to configure.
    for owed in ("class 4", "class 5", "class 6", ".githooks/pre-commit"):
        assert owed in run_text, (
            f"{arming} never mentions {owed!r}, so the one job that runs on an "
            "unarmed repository does not say which classes were skipped or "
            "where they are actually enforced")
    assert "skip, not a pass" in run_text, (
        f"{arming} does not say the skip is not a pass, which is the sentence "
        "the deterministic scanner has printed since the beginning and the "
        "one CI keeps forgetting to repeat")

    # A DETECTOR THAT DIES DISARMS THE GATE, and it does it in the gray that is
    # supposed to mean "deliberately not armed". A plain `needs:` skips this job
    # whenever the job it depends on does not succeed, GitHub counts a skipped
    # required check as satisfied, and an opted-in repository would then merge
    # with classes 4, 5 and 6 unexamined and a checks list that looks exactly
    # like an honest opt-out. Cheap to hit too, since it takes a checkout
    # failure or a runner hiccup rather than any particular interleaving.
    cond = gate.get("if", "")
    assert "cancelled()" in cond or "always()" in cond, (
        "the condition still carries the default 'all needs succeeded' rule, "
        f"so it can never run when {arming} fails no matter what else it says")

    # ONLY A LITERAL 'false' MAY TURN THE GATE OFF. Written as `== 'true'` the
    # condition treats an ABSENT answer the same as a no, and absent is what a
    # failed detector, a redacted output and a half-finished edit all produce.
    # A gray tick then means either "deliberately not armed" or "the check
    # broke", and nobody looking at the checks list can tell which.
    assert f"needs.{arming}.outputs.required != 'false'" in cond, (
        "the gate skips on anything that is not a yes, so an empty or missing "
        "arming answer disarms it and renders as the same gray tick an honest "
        "opt-out renders as")
    assert f"needs.{arming}.outputs.required == 'true'" not in cond, (
        "the condition tests for a yes rather than for an explicit no, which "
        "puts every unexpected value on the skip side")

    undecided = [s for s in gate["steps"]
                 if f"needs.{arming}.result != 'success'" in s.get("if", "")]
    assert undecided, (
        "the gate runs on an undecided arming answer and then behaves as if "
        "the answer were no, which is the same false green one job further out")
    assert any(f"needs.{arming}.outputs.required != 'true'" in s.get("if", "")
               for s in undecided), (
        "the refusal covers a detector that DIED but not one that succeeded "
        "and answered nothing, and the second one reaches the gate script, "
        "which then decides on the marker alone as though that were the "
        "question that was asked")
    assert any("exit 1" in s.get("run", "") for s in undecided), (
        "the undecided branch does not fail, so an arming job that died still "
        "produces a green armed context check")

    # The same rule one level in. The detector reads its own input the same
    # way, so a redacted or empty SECRETS_SUPPLIED lands on the side that runs
    # the check rather than the side that silently switches it off.
    assert 'SECRETS_SUPPLIED" != "false"' in run_text, (
        f"{arming} tests its input for a yes, so an empty or redacted value "
        "reads as 'no secrets supplied' and the check it should have switched "
        "on is skipped")


def test_ship_gate_finds_the_replay_probe_and_fails_closed_without_it():
    """The replay check has to be found, and has to fail closed when it cannot decide.

    The sibling repository resolved this probe against the gate's own
    directory, guards/, while the probe has always lived in probes/, so the
    path never existed and the `[ -f "$MP" ]` guard read that as "no probe
    here, carry on". The replay check was skipped in silence on every run and a
    replaying clip passed. This repository had the path right and no test, which
    is the same distance from safe.

    Three properties. The probe is resolved where it actually lives, a missing
    probe fails closed with exit 64 like unreadable input, and a probe that RAN
    without reaching a verdict fails closed too.
    """
    gate = os.path.join(ROOT, "guards", "ship_gate.sh")
    with open(gate) as fh:
        text = fh.read()

    assert 'MP="$SKILL/mirror_probe.py"' in text, (
        "the gate is not looking in the probes directory, so the replay check "
        "resolves to a path that does not exist and is skipped in silence")
    assert os.path.exists(os.path.join(PROBES, "mirror_probe.py")), (
        "the probe the gate resolves to is not there")
    assert 'if [ -f "$MP" ] && [ -z "$ARROWOK" ]' not in text, (
        "a missing probe is being treated as a reason to skip the check, which "
        "is how it disappeared for months")
    # Every other failing path in this gate drops the receipt first. A HOLD that
    # leaves yesterday's approval standing is not a hold: the clip still looks
    # signed off while nothing has been checked.
    missing_branch = text[text.index("mirror_probe.py not found"):]
    assert 'rm -f "$MARK"' in missing_branch[:missing_branch.index("exit 64")], (
        "the missing-probe HOLD leaves an existing receipt in place")
    # All three exits below the probe drop the receipt: probe missing, probe
    # inconclusive, and replay detected. The last is the one that matters most
    # and the one that was unreachable until the probe path was fixed, so it is
    # the one nobody had ever exercised.
    replay_branch = text[text.index("the scene replays itself"):]
    assert 'rm -f "$MARK"' in replay_branch[:replay_branch.index("exit 3")], (
        "a clip the probe just REJECTED keeps its approval receipt")

    # The four outcomes are EXECUTED, not read. Driving the whole gate cannot
    # reach this section without real video: the geometry check reads the file
    # with ffprobe and exits 64 first, so a test that feeds it a text file named
    # clip.mp4 and asserts "nonzero" is only proving the gate rejects a text
    # file. That was the previous version of this test, and deleting the branch
    # under test would have left it green.
    #
    # So the section is lifted out by its own anchors and run with the probe
    # stubbed to each exit code it can return. If the anchors ever move, the
    # extraction raises and this test fails loudly, which is the correct signal.
    block = text[text.index('MP="$SKILL/mirror_probe.py"'):]
    block = block[:block.index('if [ -n "$DIRECTIONAL" ]')]

    def run_replay(probe_exit, replayok="", says=None):
        """probe_exit None means no probe file at all.

        `says` is what the probe prints. The default carries the MIRROR verdict
        line a real probe always prints; passing something else stands in for a
        probe that crashed, which python reports with the same exit 1 the probe
        uses for a detected replay.
        """
        with tempfile.TemporaryDirectory() as tmp:
            skill = os.path.join(tmp, "probes")
            os.makedirs(skill)
            if probe_exit is not None:
                with open(os.path.join(skill, "mirror_probe.py"), "w") as fh:
                    line = says if says is not None else (
                        "MIRROR REPLAYS: stub" if probe_exit == 1 else "MIRROR FORWARD: stub")
                    fh.write(f"import sys\nprint({line!r})\nsys.exit({probe_exit})\n")
            mark = os.path.join(tmp, "receipt")
            with open(mark, "w") as fh:
                fh.write("a receipt from a previous pass\n")
            prelude = ('set -uo pipefail\n'
                       'SKILL="$T_SKILL"\nMARK="$T_MARK"\nF="$T_MARK"\n'
                       'ARROWOK=""\nREPLAYOK="$T_REPLAYOK"\n')
            r = subprocess.run(
                ["bash", "-c", prelude + block + "\nexit 0\n"],
                env=dict(os.environ, T_SKILL=skill, T_MARK=mark,
                         T_REPLAYOK=replayok),
                capture_output=True, text=True, timeout=60)
            return r.returncode, r.stdout + r.stderr, os.path.exists(mark)

    rc, out, receipt = run_replay(None)
    assert rc == 64, f"a missing probe must fail closed with 64, got {rc}\n{out}"
    assert "mirror_probe.py not found" in out, out
    assert not receipt, "the missing-probe HOLD left an existing receipt standing"

    for code in (3, 64):
        rc, out, receipt = run_replay(code)
        assert rc == 64, (
            f"a probe that ran and returned {code} reached no verdict, which must "
            f"fail closed like a missing probe; got {rc}\n{out}")
        assert "no verdict" in out, out
        assert not receipt, (
            f"an inconclusive probe (exit {code}) left an existing receipt standing")

    rc, out, receipt = run_replay(1)
    assert rc == 3, f"a detected replay must hold with 3, got {rc}\n{out}"
    assert "replays itself" in out, out
    assert not receipt, (
        "the clip the probe just REJECTED kept its approval receipt, which is "
        "the worst case of all: it still looks signed off")

    rc, out, receipt = run_replay(1, replayok="the scene is time symmetric")
    assert rc == 0, f"a declared REPLAYOK override must pass, got {rc}\n{out}"
    assert "REPLAY OVERRIDE" in out, out
    assert receipt, "an override is a pass, so the receipt must survive"

    rc, out, receipt = run_replay(0)
    assert rc == 0, f"a clean probe must pass, got {rc}\n{out}"
    assert receipt, "a clean probe must not remove the receipt"

    # A crashed probe exits 1, and so does a detected replay. Only the verdict
    # line tells them apart, and with REPLAYOK set the crash used to walk into
    # the override branch and ship the clip with a receipt and no replay check
    # behind it. Both the bare crash and the crash under an override must hold.
    crashes = (
        ("a bare crash", "", "Traceback: ImportError"),
        ("a crash under an override", "declared symmetric", "Traceback: ImportError"),
        # The nastiest one, and it was live until an adversary reproduced it. A
        # SyntaxError makes python quote the offending SOURCE LINE back at you,
        # and the offending line in this probe is the one that prints the
        # verdict, so the traceback contains the word MIRROR. stderr is folded
        # into the gate's capture, so a loose substring test read that crash as
        # a decision and shipped the clip.
        ("a traceback quoting the verdict line", "declared symmetric",
         '    print(f"MIRROR {out[chr(39)+chr(39)]}: ...  SyntaxError'),
    )
    for label, ok, says in crashes:
        rc, out, receipt = run_replay(1, replayok=ok, says=says)
        assert rc == 64, (
            f"{label} exits 1 exactly like a real replay verdict, so without an "
            f"anchored verdict line it must fail closed; got {rc}\n{out}")
        assert "no verdict matching its exit code" in out, out
        assert not receipt, f"{label} left an approval receipt standing"

    # The verdict must also AGREE with the exit code, or a probe half-rewritten
    # between the two could report forward motion while exiting on a replay.
    rc, out, receipt = run_replay(1, says="MIRROR FORWARD: stub")
    assert rc == 64, f"a FORWARD verdict with a replay exit must hold; got {rc}\n{out}"
    assert not receipt, "a contradictory verdict left an approval receipt standing"

    # A probe that RAN and reached no verdict is the same silent skip wearing
    # different clothes, and it only became reachable here once the probe
    # started running at all. The probe answers 64 for footage it cannot read
    # and 3 for too little visual signal; both used to fall through to the
    # directional check and, with no directional argument, on to a PASS.
    assert 'case "$MPRC" in' in text, (
        "only the replay verdict is handled, so an inconclusive or failed probe "
        "falls through and the clip ships unexamined")
    for code in ("0|1)", "exit 64 ;;"):
        assert code in text, f"the probe status handling is missing {code}"


if __name__ == "__main__":
    sys.exit(_main())
