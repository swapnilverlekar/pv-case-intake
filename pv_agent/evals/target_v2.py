"""V2 under test: the designed graph, in eval_mode (no human pauses)."""

import time

from langchain_core.callbacks import UsageMetadataCallbackHandler

from pv_agent.evals.common import cost_usd, total_tokens
from pv_agent.graph import agent_inputs, build_graph, run_config

_graph = build_graph()


def to_outputs(state):
    """Graph state -> the unified output shape."""
    valid = bool(state.get("valid"))
    ex = state.get("extraction") or {}
    quotes = {r["reporter_words"]: r["quote"] for r in ex.get("reactions", [])}

    reactions, claims = [], []
    for r in (state.get("expectedness") or {}).get("reactions", []):
        reactions.append({"reaction": r["reaction"], "quote": quotes.get(r["reaction"]),
                          "expectedness": r["expectedness"], "label_quote": r["label_quote"]})
        if r.get("model_expectedness") == "expected":   # every label quote the model offered, kept or downgraded
            claims.append({"kind": "label_quote", "quote": r["label_quote"], "source": "label"})
    ser = state.get("seriousness") or {}
    for name, c in (ser.get("criteria") or {}).items():
        if c["met"]:
            claims.append({"kind": f"seriousness.{name}", "quote": c["quote"], "source": "message"})
    claims += [{"kind": f"seriousness.{d['criterion']}", "quote": d["quote"], "source": "message"}
               for d in ser.get("dropped", [])]
    claims += [{"kind": "extraction.reaction", "quote": r["quote"], "source": "message"} for r in ex.get("reactions", [])]
    claims += [{"kind": f"extraction.{x['field']}", "quote": x.get("quote"), "source": "message"}
               for x in state.get("rejected_evidence", [])]

    return {
        "valid": valid,
        "missing_elements": state.get("missing_elements", []),
        "target_drug": state.get("target_drug"),
        "is_serious": ser.get("is_serious") if valid else None,
        "seriousness_criteria": {k: {"met": v["met"], "quote": v["quote"]} for k, v in (ser.get("criteria") or {}).items()} or None,
        "reactions": reactions,
        "case_expectedness": ((("unexpected" if state["expectedness"]["any_unexpected"] else "expected"))
                              if valid and state.get("expectedness") else None),
        "route": state.get("route"),
        "due_date": state.get("due_date"),
        "duplicate_of": (state.get("duplicate") or {}).get("duplicate_of"),
        "claims": claims,
        "trajectory": state.get("trajectory", []),
        "tool_calls": (state.get("followup") or {}).get("tool_calls", []),
        "followup_draft": (state.get("followup") or {}).get("draft"),
    }


def run_v2(inputs: dict) -> dict:
    handler = UsageMetadataCallbackHandler()
    cfg = run_config(story=4, eval_mode=True)
    cfg["callbacks"] = [handler]
    start = time.time()
    state = _graph.invoke(agent_inputs(inputs), config=cfg)
    out = to_outputs(state)
    out.update(usage=handler.usage_metadata, cost_usd=cost_usd(handler.usage_metadata),
               total_tokens=total_tokens(handler.usage_metadata), latency_s=round(time.time() - start, 2))
    return out
