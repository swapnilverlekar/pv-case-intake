"""The write-once reducer on receipt_timestamp (state.py), alone and inside a LangGraph StateGraph."""

import pytest
from langgraph.graph import END, START, StateGraph

from pv_agent.state import CaseState, write_once

T1 = "2022-01-05T18:39:30+00:00"
T2 = "2022-01-06T09:00:00+00:00"


def test_first_write_is_accepted():
    assert write_once(None, T1) == T1


def test_same_value_again_is_accepted():
    assert write_once(T1, T1) == T1


def test_a_different_second_write_is_rejected():
    with pytest.raises(ValueError, match="write-once"):
        write_once(T1, T2)


def test_an_update_without_the_field_keeps_the_original():
    assert write_once(T1, None) == T1


def test_the_reducer_is_enforced_by_the_graph_state():
    # A two-node graph on the real CaseState: the second node tries to move the clock start.
    g = StateGraph(CaseState)
    g.add_node("capture", lambda s: {"receipt_timestamp": T1})
    g.add_node("tamper", lambda s: {"receipt_timestamp": T2})
    g.add_edge(START, "capture")
    g.add_edge("capture", "tamper")
    g.add_edge("tamper", END)
    with pytest.raises(ValueError, match="write-once"):
        g.compile().invoke({"narrative": "x"})


def test_the_graph_keeps_the_timestamp_when_later_nodes_leave_it_alone():
    g = StateGraph(CaseState)
    g.add_node("capture", lambda s: {"receipt_timestamp": T1})
    g.add_node("later", lambda s: {"route": "periodic"})
    g.add_edge(START, "capture")
    g.add_edge("capture", "later")
    g.add_edge("later", END)
    assert g.compile().invoke({"narrative": "x"})["receipt_timestamp"] == T1
