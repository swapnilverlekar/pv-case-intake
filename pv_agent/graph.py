"""The intake graph.

    intake (code) -> extraction (model) -> product normalization (code) -> validity gate (code)
      invalid -> END, route follow_up_required        (story 3: follow-up planner)
      valid   -> seriousness | expectedness | duplicate check   (in parallel)
              -> clock (code) -> END                  (story 4: human sign-off gate)

Each specialist is one structured LLM call (the duplicate check skips it when
the code pre-filter leaves no candidates) and writes only its own state key.
Every decision -- validity, is_serious, route, due date -- is made in code.
"""

from langgraph.graph import END, START, StateGraph

from pv_agent import config
from pv_agent.nodes.clock import clock
from pv_agent.nodes.duplicate import duplicate_check
from pv_agent.nodes.expectedness import expectedness
from pv_agent.nodes.extraction import extraction
from pv_agent.nodes.intake import intake
from pv_agent.nodes.normalize import normalize
from pv_agent.nodes.seriousness import seriousness
from pv_agent.nodes.validity import validity
from pv_agent.state import CaseState

SPECIALISTS = ["seriousness", "expectedness", "duplicate_check"]


def route_after_gate(state):
    """Valid -> fan out to all three specialists; invalid -> stop."""
    return SPECIALISTS if state["valid"] else END


def build_graph():
    g = StateGraph(CaseState)
    g.add_node("intake", intake)
    g.add_node("extraction", extraction)
    g.add_node("product_normalization", normalize)
    g.add_node("validity_gate", validity)
    g.add_node("seriousness", seriousness)
    g.add_node("expectedness", expectedness)
    g.add_node("duplicate_check", duplicate_check)
    g.add_node("clock", clock)

    g.add_edge(START, "intake")
    g.add_edge("intake", "extraction")
    g.add_edge("extraction", "product_normalization")
    g.add_edge("product_normalization", "validity_gate")
    g.add_conditional_edges("validity_gate", route_after_gate, SPECIALISTS + [END])
    g.add_edge(SPECIALISTS, "clock")   # join: clock runs once all three are done
    g.add_edge("clock", END)
    return g.compile(name=config.GRAPH_NAME)


def run_config(example_key=None, safety_report_id=None, story=config.STORY):
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
