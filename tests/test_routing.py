"""Routing (graph.py route_after_gate, nodes/review.py review_routing + after_review_routing)
and the graph's wiring. The graph is compiled to inspect its edges; it is never invoked."""

import pytest

import pv_agent.nodes.review as review
from pv_agent.graph import SPECIALISTS, build_graph, route_after_gate

CFG = {"configurable": {"thread_id": "t1"}}
CFG_EVAL = {"configurable": {"thread_id": "t1", "eval_mode": True}}


@pytest.fixture(autouse=True)
def stub_prompt_versions(monkeypatch):
    # event() stamps prompt-version hashes; those import the LLM node modules. Not needed here.
    monkeypatch.setattr(review, "prompt_versions", lambda: {"stub": "v"})


def case(serious=False, needs_review=False, duplicate=None, intake_errors=None, route="periodic"):
    return {
        "receipt_timestamp": "2022-01-05T18:39:30+00:00", "ref": "R1", "route": route, "due_date": None,
        "seriousness": {"is_serious": serious},
        "expectedness": {"reactions": [{"reaction": "rash", "expectedness": "expected", "needs_review": needs_review}],
                         "label_effective_time": "20250708"},
        "duplicate": {"duplicate_of": duplicate},
        "intake_errors": intake_errors or [],
    }


def next_node(state, cfg=CFG):
    return review.after_review_routing({**state, **review.review_routing(state, cfg)})


# --- after the validity gate ------------------------------------------------

def test_valid_case_fans_out_to_all_three_specialists():
    assert route_after_gate({"valid": True}) == ["seriousness", "expectedness", "duplicate_check"]


def test_invalid_case_goes_to_the_follow_up_planner():
    assert route_after_gate({"valid": False}) == "followup_planner"


# --- after the clock ----------------------------------------------------------

@pytest.mark.parametrize("state, why", [
    (case(serious=True, route="expedited_15_day"), "serious, 15-day"),
    (case(serious=True, route="periodic"), "serious, periodic"),
    (case(needs_review=True), "an expectedness flag"),
    (case(duplicate="20281949", route="merge_with_existing"), "a suspected duplicate"),
    (case(intake_errors=["no 'Received:' line in header"]), "an intake error"),
])
def test_cases_needing_a_human_go_to_case_signoff(state, why):
    assert next_node(state) == "case_signoff", why


def test_a_clean_non_serious_case_is_auto_committed():
    out = review.review_routing(case(), CFG)
    assert out["review_required"] is False
    assert out["final"]["decided_by"].startswith("agent (auto-committed")
    assert out["audit_events"][-1]["action"] == "auto_committed, sampled QC in production"
    assert review.after_review_routing({**case(), **out}) == "commit"


def test_a_suspected_duplicate_is_never_merged_without_a_human():
    out = review.review_routing(case(duplicate="20281949", route="merge_with_existing"), CFG)
    assert out["review_required"] is True and "final" not in out
    assert any("never merged automatically" in r for r in out["review_reasons"])


def test_eval_mode_skips_the_pause_but_records_that_review_was_needed():
    state = case(serious=True, route="expedited_15_day")
    out = review.review_routing(state, CFG_EVAL)
    assert out["final"]["decided_by"] == "agent (eval_mode, no human review)"
    assert out["audit_events"][-1]["action"] == "review_skipped_eval_mode"
    assert review.after_review_routing({**state, **out}) == "commit"


# --- graph wiring (compiled, not run) --------------------------------------------

@pytest.fixture(scope="module")
def edges():
    g = build_graph().get_graph()
    return {(e.source, e.target) for e in g.edges}


def test_the_clock_runs_only_after_all_three_specialists(edges):
    assert {s for s, t in edges if t == "clock"} == set(SPECIALISTS)


def test_the_follow_up_branch_never_reaches_the_clock(edges):
    assert {t for s, t in edges if s == "followup_planner"} == {"followup_review"}
    assert {t for s, t in edges if s == "followup_review"} == {"commit"}


def test_every_path_ends_in_a_single_commit_node(edges):
    assert {t for s, t in edges if s == "commit"} == {"__end__"}
    assert {s for s, t in edges if t == "__end__"} == {"commit"}
    assert {s for s, t in edges if t == "commit"} == {"review_routing", "case_signoff", "followup_review"}
