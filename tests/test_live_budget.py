"""A live run sends no scene that would take it past its budget, counted across every pass and re-entry.

A run is one cut, and its ledger is the append-only log of every vendor request it made, kept in the
run's own directory. Before a scene request is sent, pipeline/live.py adds its price to the prices of
every request already on that ledger, and a scene that would take the total past RUN_BUDGET_USD is not
sent. The refusal goes on the ledger, nothing more is sent in that pass, the narration is not drawn,
and the graph (pipeline/graph.py, the LangGraph state machine that runs a spot from its board to
delivery) stops the run at the render for a person, who can set the budget higher and re-enter. These
tests run that toolkit with every vendor call and repo script replaced by a fake.

Words used below. A spot is one short ad film and its board is the written plan for it, a boards.json
file. A scene is one generated video clip in a spot, a take is one render attempt of it, and a re-roll
sends a scene that came back broken once more. A spot can shoot its scenes as a chain, each from the
last frame of the one before.

The fakes and the live fixture are the ones tests/test_live.py uses for the rest of the toolkit that
spends, imported from there rather than copied.
"""
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

from test_live import (  # noqa: E402
    Vendor,
    calls_to,
    chain_state,
    closer_take,
    graph,
    scripts,
    takes_and_frames,
)

# A pytest fixture, imported under its own name so pytest finds it in this module too.
from test_live import live as live  # noqa: E402

from pipeline import live as L  # noqa: E402

# the budget: what one run may spend on its scenes, across every pass and every re-entry. Each scene on these
# boards costs $0.64.

def under_budget(monkeypatch, state, usd, tk):
    """The run in `state` entered again under RUN_BUDGET_USD=usd, the way a person re-enters it."""
    monkeypatch.setenv("RUN_BUDGET_USD", usd)
    return L.LiveToolkit(state["run_dir"], tk.ledger.run_id)


def test_the_budget_keeps_back_the_one_scene_that_would_cross_it_and_the_run_stops(live, monkeypatch):
    """Under a $1.50 budget the first two scenes fit and the third would bring the run to $1.92. It is not sent,
    the refusal goes on the ledger with what the run had spent, its price and the budget, the narration is not
    drawn, and the graph stops the run at the render for a person. Each request that went carries the budget it
    went under, and with RUN_BUDGET_USD unset the budget is the default."""
    tk, state = live
    assert tk.budget == L.BUDGET_USD == 5.00
    vendor = Vendor()
    monkeypatch.setattr(L, "http", vendor)
    run = scripts()
    monkeypatch.setattr(L.LiveToolkit, "script", run)
    tk = under_budget(monkeypatch, state, "1.50", tk)
    v = tk.render(state)
    assert v["over_budget"] == ["c"] and v["failed"] == [] and v["fresh"] == ["a", "b"], v
    assert len(vendor.posts()) == 2, vendor.posts()
    assert v["why"]["c"] == ("not sent, since the scenes this run has asked for come to $1.28 and this one, at $0.64, "
                             "would bring them to $1.92, past the run's $1.50 budget. A person who means to spend more "
                             "sets RUN_BUDGET_USD higher and re-enters the run"), v["why"]
    rows = tk.ledger.rows()
    refused = [r for r in rows if r.get("check") == "budget"]
    assert [(r["scene"], r["passed"], r["spent_usd"], r["price_usd"], r["budget_usd"]) for r in refused] == [
        ("zai-c", False, 1.28, 0.64, 1.5)], refused
    assert refused[0]["reason"] == v["why"]["c"], refused
    requests = [r for r in rows if r["kind"] == "request"]
    assert [(r["scene"], r["budget_usd"]) for r in requests] == [("zai-a", 1.5), ("zai-b", 1.5)], requests
    assert not calls_to(run, "gates/voice_take.sh"), "the narration was paid for after the budget stopped the run"
    G = graph()
    assert G.after_render({"verdict": {"render": v}}) == G.STOP, "a run past its budget went on"


def test_a_person_who_raises_the_budget_and_re_enters_sends_the_scene_it_kept_back(live, monkeypatch):
    """Raising the budget is a person setting RUN_BUDGET_USD again and re-entering the run. The takes it already
    holds are kept, the scene the budget kept back goes under the new one, landing the run on it to the cent,
    and the narration is drawn."""
    tk, state = live
    vendor = Vendor()
    monkeypatch.setattr(L, "http", vendor)
    run = scripts()
    monkeypatch.setattr(L.LiveToolkit, "script", run)
    assert under_budget(monkeypatch, state, "1.50", tk).render(state)["over_budget"] == ["c"]
    v = under_budget(monkeypatch, state, "1.92", tk).render(state)
    assert v["over_budget"] == [] and v["failed"] == [] and v["fresh"] == ["c"] and len(vendor.posts()) == 3, v
    assert [r["budget_usd"] for r in tk.ledger.rows() if r["kind"] == "request" and r.get("scene")] == [1.5, 1.5, 1.92]
    assert len(calls_to(run, "gates/voice_take.sh")) == 1, "the narration was not drawn once the run could go on"


def test_the_budget_counts_what_every_earlier_pass_of_the_run_asked_for(live, monkeypatch):
    """The re-roll ceiling starts again on every re-entry, so the budget is held against the whole ledger. The
    first pass sent three scenes and the engine rejected one. Re-entered under a $2.00 budget, its re-roll alone
    would fit, but it would bring the run to $2.56, so it is kept back."""
    tk, state = live
    vendor = Vendor(reject={"fal-2"})
    monkeypatch.setattr(L, "http", vendor)
    monkeypatch.setattr(L.LiveToolkit, "script", scripts())
    first = tk.render(state)
    assert first["failed"] == ["b"] and len(vendor.posts()) == 3, first
    v = under_budget(monkeypatch, state, "2.00", tk).render(dict(state, verdict={"render": first}))
    assert v["over_budget"] == ["b"] and len(vendor.posts()) == 3, v
    assert "come to $1.92" in v["why"]["b"] and "bring them to $2.56" in v["why"]["b"], v["why"]


def test_a_request_collected_on_a_re_entry_counts_once_against_the_budget(live, monkeypatch):
    """The first pass died after sending its three scenes. The re-entry collects them rather than paying again,
    which writes no request of its own, so each counts once. Under a budget of exactly four scenes, the re-roll
    of the one the engine rejected still goes, and lands the run on its budget to the cent."""
    tk, state = live
    vendor = Vendor(die_on_status=True, reject={"fal-2"})
    monkeypatch.setattr(L, "http", vendor)
    monkeypatch.setattr(L.LiveToolkit, "script", scripts())
    with pytest.raises(KeyboardInterrupt):
        tk.render(state)
    assert len(vendor.posts()) == 3
    vendor.die_on_status = False
    again = under_budget(monkeypatch, state, "2.56", tk)
    collected = again.render(state)
    assert collected["failed"] == ["b"] and collected["over_budget"] == [] and len(vendor.posts()) == 3, collected
    v = again.render(dict(state, verdict={"render": collected}))
    assert v["over_budget"] == [] and v["failed"] == [] and len(vendor.posts()) == 4, v
    assert not [r for r in tk.ledger.rows() if r.get("check") == "budget"], "a collected request was counted twice"


def test_a_chain_stops_at_the_scene_its_budget_keeps_back(live, monkeypatch, tmp_path):
    """A chained scene is held to the budget before its frame is sent. The scene kept back is the last one the
    chain reaches, and the scenes after it wait on it."""
    tk, state = live
    monkeypatch.setenv("CLOSER_FROM", str(closer_take(tmp_path)))
    takes_and_frames(monkeypatch)
    vendor = Vendor()
    monkeypatch.setattr(L, "http", vendor)
    monkeypatch.setattr(L.LiveToolkit, "script", scripts())
    v = under_budget(monkeypatch, state, "0.70", tk).render(chain_state(state))
    assert v["over_budget"] == ["b"] and v["fresh"] == ["a"] and len(vendor.posts()) == 1, v
    assert v["why"]["c"] == "waits on zai-b, the scene it starts from", v["why"]


def test_a_scene_on_an_engine_with_no_price_is_kept_back(live, monkeypatch):
    """The budget cannot hold a sum it does not know, so a scene on an engine with no recorded price is not sent."""
    tk, state = live
    monkeypatch.delitem(L.PRICE_PER_SCENE, "google/gemini-omni-flash")
    vendor = Vendor()
    monkeypatch.setattr(L, "http", vendor)
    monkeypatch.setattr(L.LiveToolkit, "script", scripts())
    v = tk.render(state)
    assert v["over_budget"] == ["a"] and vendor.posts() == [] and "no price is recorded" in v["why"]["a"], v


@pytest.mark.parametrize("value", ["four", "$4", "0", "-1", "nan", "inf"])
def test_a_budget_that_is_not_a_sum_of_dollars_stops_the_run_before_it_starts(live, monkeypatch, tmp_path, value):
    monkeypatch.setenv("RUN_BUDGET_USD", value)
    with pytest.raises(L.LiveSetupError, match="RUN_BUDGET_USD"):
        L.LiveToolkit(str(tmp_path / "another"))
    assert not (tmp_path / "another").exists(), "a run started before its budget was read"
