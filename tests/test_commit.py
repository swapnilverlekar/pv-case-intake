"""Commit and records (nodes/review.py commit, records.py), written to a temp
runtime/ directory. No graph run, no model, no network."""

import json

import pytest

import pv_agent.nodes.review as review
from pv_agent import config

CFG = {"configurable": {"thread_id": "case-1"}}


@pytest.fixture(autouse=True)
def runtime(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "RUNTIME", tmp_path)
    monkeypatch.setattr(review, "prompt_versions", lambda: {"stub": "v"})
    return tmp_path


def state(**extra):
    return {
        "ref": "R1", "receipt_timestamp": "2022-01-05T18:39:30+00:00", "route": "periodic", "valid": True,
        "final": {"route": "periodic", "is_serious": False, "reactions": [], "duplicate_of": None, "due_date": None},
        "audit_events": [{"action": "receipt_timestamp_captured"}, {"action": "determinations_proposed"}],
        **extra,
    }


def audit_lines(runtime):
    path = runtime / "audit_log.jsonl"
    return [json.loads(l) for l in path.open()] if path.exists() else []


def test_one_commit_writes_each_audit_event_exactly_once(runtime):
    review.commit(state(), CFG)
    actions = [row["action"] for row in audit_lines(runtime)]
    assert actions == ["receipt_timestamp_captured", "determinations_proposed", "case_committed"]


def test_one_commit_writes_one_case_record(runtime):
    review.commit(state(), CFG)
    assert [p.name for p in (runtime / "cases").iterdir()] == ["case-1.json"]


def test_the_audit_log_is_append_only_across_cases(runtime):
    review.commit(state(ref="R1"), {"configurable": {"thread_id": "case-1"}})
    review.commit(state(ref="R2"), {"configurable": {"thread_id": "case-2"}})
    rows = audit_lines(runtime)
    assert len(rows) == 6
    assert [r["action"] for r in rows if r["action"] == "case_committed"] == ["case_committed"] * 2


def test_eval_mode_writes_nothing(runtime):
    review.commit(state(), {"configurable": {"thread_id": "case-1", "eval_mode": True}})
    assert list(runtime.iterdir()) == []


def test_a_reviewer_correction_is_written_once_as_a_dataset_example(runtime):
    s = state(header={"received": "x"}, narrative="n",
              seriousness={"is_serious": True}, duplicate={"duplicate_of": None}, due_date=None,
              expectedness={"reactions": [{"reaction": "rash", "expectedness": "unexpected"}]},
              review={"action": "correct", "reviewer": "Dr A", "reason_code": "expectedness_wrong", "note": "n"})
    review.commit(s, CFG)
    rows = [json.loads(l) for l in (runtime / "corrections.jsonl").open()]
    assert len(rows) == 1 and set(rows[0]) == {"inputs", "outputs", "metadata"}
    assert rows[0]["metadata"]["reason_code"] == "expectedness_wrong"


def test_an_approved_follow_up_goes_to_the_outbox_marked_not_sent(runtime):
    s = state(followup_review={"action": "approve", "reviewer": "J", "type": "quality_referral",
                               "channel": "internal: product quality team", "questions": [], "message": "m"})
    review.commit(s, CFG)
    out = json.loads((runtime / "outbox" / "case-1.json").read_text())
    assert out["type"] == "quality_referral" and out["sent"] is False


def test_a_rejected_follow_up_writes_no_outbox(runtime):
    review.commit(state(followup_review={"action": "reject", "reviewer": "J"}), CFG)
    assert not (runtime / "outbox").exists()


@pytest.mark.xfail(strict=True, reason=(
    "commit() is not idempotent: calling it twice for the same thread appends the audit lines again. "
    "Once-only writing relies on the graph running the commit node once per case "
    "(see test_routing.py::test_every_path_ends_in_a_single_commit_node), not on commit() itself."))
def test_a_repeated_commit_for_the_same_case_does_not_duplicate_audit_lines(runtime):
    review.commit(state(), CFG)
    review.commit(state(), CFG)
    assert len(audit_lines(runtime)) == 3
