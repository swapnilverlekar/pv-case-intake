"""The intake graph. Story 1: intake -> extraction -> normalization -> validity gate.

Only extraction calls a model. The routing after the gate is code; story 2
replaces the pending_assessment END with the specialists, story 3 replaces
the follow_up_required END with the follow-up planner.
"""

from langgraph.graph import END, START, StateGraph

from pv_agent import config
from pv_agent.nodes.extraction import extraction
from pv_agent.nodes.intake import intake
from pv_agent.nodes.normalize import normalize
from pv_agent.nodes.validity import validity
from pv_agent.state import CaseState


def route_after_gate(state):
    return state["route"]


def build_graph():
    g = StateGraph(CaseState)
    g.add_node("intake", intake)
    g.add_node("extraction", extraction)
    g.add_node("product_normalization", normalize)
    g.add_node("validity_gate", validity)

    g.add_edge(START, "intake")
    g.add_edge("intake", "extraction")
    g.add_edge("extraction", "product_normalization")
    g.add_edge("product_normalization", "validity_gate")
    g.add_conditional_edges("validity_gate", route_after_gate, {
        "follow_up_required": END,   # story 3: follow-up planner
        "pending_assessment": END,   # story 2: specialists
    })
    return g.compile(name=config.GRAPH_NAME)


def run_config(example_key=None, safety_report_id=None, story=1):
    """Tracing config: tagged by story and, when known, the case id."""
    tags = [f"story={story}"]
    metadata = {"story": story}
    if safety_report_id:
        tags.append(f"safety_report_id={safety_report_id}")
        metadata["safety_report_id"] = safety_report_id
    if example_key:
        metadata["example_key"] = example_key
    return {"tags": tags, "metadata": metadata, "run_name": config.GRAPH_NAME}


def agent_inputs(example_inputs):
    """The ONLY thing passed to the graph: the message. Never reference outputs."""
    return {"header": example_inputs["header"], "narrative": example_inputs["narrative"]}
