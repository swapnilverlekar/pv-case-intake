"""The intake graph.

    intake (code) -> extraction (model) -> product normalization (code) -> validity gate (code)
      invalid -> follow-up planner (AGENT) -> follow-up review (human interrupt) -> commit
      valid   -> seriousness | expectedness | duplicate check   (in parallel)
              -> clock (code) -> review routing (code)
                   needs a human -> case sign-off (human interrupt) -> commit
                   clean, non-serious -> commit (auto-committed, sampled QC)

Every decision -- validity, is_serious, route, due date -- is made in code.
The follow-up planner is the only node where the model chooses its next action.
Configurable eval_mode=true skips both interrupts.
"""

import inspect

from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph

from pv_agent import config
from pv_agent.nodes.clock import clock
from pv_agent.nodes.duplicate import duplicate_check
from pv_agent.nodes.expectedness import expectedness
from pv_agent.nodes.extraction import extraction
from pv_agent.nodes.followup import followup_planner, followup_review
from pv_agent.nodes.intake import intake
from pv_agent.nodes.normalize import normalize
from pv_agent.nodes.review import after_review_routing, case_signoff, commit, review_routing
from pv_agent.nodes.seriousness import seriousness
from pv_agent.nodes.validity import validity
from pv_agent.state import CaseState

SPECIALISTS = ["seriousness", "expectedness", "duplicate_check"]


def on_path(name, fn):
    """Wrap a node so it appends its name to state['trajectory']. A node that
    pauses on interrupt() returns only after resuming, so it is recorded once."""
    takes_config = "config" in inspect.signature(fn).parameters

    def node(state, config: RunnableConfig):
        out = fn(state, config) if takes_config else fn(state)
        return {**(out or {}), "trajectory": [name]}

    node.__name__ = name
    return node


def route_after_gate(state):
    """Valid -> fan out to all three specialists; invalid -> follow-up planner."""
    return SPECIALISTS if state["valid"] else "followup_planner"


def build_graph(checkpointer=None):
    g = StateGraph(CaseState)
    g.add_node("intake", on_path("intake", intake))
    g.add_node("extraction", on_path("extraction", extraction))
    g.add_node("product_normalization", on_path("product_normalization", normalize))
    g.add_node("validity_gate", on_path("validity_gate", validity))
    g.add_node("seriousness", on_path("seriousness", seriousness))
    g.add_node("expectedness", on_path("expectedness", expectedness))
    g.add_node("duplicate_check", on_path("duplicate_check", duplicate_check))
    g.add_node("clock", on_path("clock", clock))
    g.add_node("review_routing", on_path("review_routing", review_routing))
    g.add_node("case_signoff", on_path("case_signoff", case_signoff))
    g.add_node("followup_planner", on_path("followup_planner", followup_planner))
    g.add_node("followup_review", on_path("followup_review", followup_review))
    g.add_node("commit", on_path("commit", commit))

    g.add_edge(START, "intake")
    g.add_edge("intake", "extraction")
    g.add_edge("extraction", "product_normalization")
    g.add_edge("product_normalization", "validity_gate")
    g.add_conditional_edges("validity_gate", route_after_gate, SPECIALISTS + ["followup_planner"])
    g.add_edge(SPECIALISTS, "clock")   # join: clock runs once all three are done
    g.add_edge("clock", "review_routing")
    g.add_conditional_edges("review_routing", after_review_routing, ["case_signoff", "commit"])
    g.add_edge("case_signoff", "commit")
    g.add_edge("followup_planner", "followup_review")
    g.add_edge("followup_review", "commit")
    g.add_edge("commit", END)
    return g.compile(name=config.GRAPH_NAME, checkpointer=checkpointer)


# For `langgraph dev` / Studio: the platform supplies persistence.
graph = build_graph()


def run_config(example_key=None, safety_report_id=None, story=config.STORY, thread_id=None, eval_mode=False):
    """Tracing + run config: tagged by story and, when known, the case id."""
    tags = [f"story={story}"] + (["eval_mode"] if eval_mode else [])
    metadata = {"story": story, "eval_mode": eval_mode}
    if safety_report_id:
        tags.append(f"safety_report_id={safety_report_id}")
        metadata["safety_report_id"] = safety_report_id
    if example_key:
        metadata["example_key"] = example_key
    configurable = {"eval_mode": eval_mode}
    if thread_id:
        configurable["thread_id"] = thread_id
    return {"tags": tags, "metadata": metadata, "run_name": config.GRAPH_NAME, "configurable": configurable}


def agent_inputs(example_inputs):
    """The ONLY thing passed to the graph: the message. Never reference outputs."""
    return {"header": example_inputs["header"], "narrative": example_inputs["narrative"]}
