"""Human checkpoints and the commit (all code; the reviewer is the human).

review_routing  decides whether a person must look at the case.
case_signoff    pauses the graph (LangGraph interrupt) with a reviewer payload;
                resumes with approve or a correction. On correction, CODE
                recomputes route and due date; the receipt timestamp never moves.
commit          the only node that writes files: case record, audit log,
                corrections, outbox. Skipped in eval mode.

Eval mode (configurable eval_mode=true) skips both interrupts and commits the
agent's own decisions, so an evaluation measures the agent, not a reviewer.
"""

from datetime import date

from langgraph.types import interrupt

from pv_agent import config, records
from pv_agent.nodes.clock import decide_route
from pv_agent.versions import prompt_versions

REASON_CODES = ["seriousness_wrong", "expectedness_wrong", "duplicate_wrong", "extraction_wrong", "other"]
EXPECTEDNESS_VALUES = ["expected", "unexpected", "not_applicable"]


def eval_mode(cfg):
    return bool((cfg or {}).get("configurable", {}).get("eval_mode", False))


def thread_id(cfg, state):
    return (cfg or {}).get("configurable", {}).get("thread_id") or state.get("ref") or "no-thread"


def event(state, cfg, actor, action, before=None, after=None, reason_code=None, note=None):
    """One audit line. Written later, once, by commit."""
    return {
        "timestamp": records.now(),
        "thread_id": thread_id(cfg, state),
        "ref": state.get("ref"),
        "actor": actor,
        "action": action,
        "before": before,
        "after": after,
        "reason_code": reason_code,
        "note": note,
        "label_effective_time": (state.get("expectedness") or {}).get("label_effective_time"),
        "model": config.MODEL,
        "prompt_versions": prompt_versions(),
    }


def agent_determinations(state):
    exp = state["expectedness"]
    return {
        "is_serious": state["seriousness"]["is_serious"],
        "reactions": [{"reaction": r["reaction"], "expectedness": r["expectedness"]} for r in exp["reactions"]],
        "duplicate_of": state["duplicate"]["duplicate_of"],
        "route": state["route"],
        "due_date": state["due_date"],
    }


# ------------------------------------------------------------ routing


def review_routing(state, config):
    reasons = []
    if state["seriousness"]["is_serious"]:
        reasons.append(f"serious case (route {state['route']})")
    flagged = [r["reaction"] for r in state["expectedness"]["reactions"] if r["needs_review"]]
    if flagged:
        reasons.append(f"expectedness needs review: {flagged}")
    if state["duplicate"]["duplicate_of"]:
        reasons.append(f"suspected duplicate of {state['duplicate']['duplicate_of']} (never merged automatically)")
    if state.get("intake_errors"):
        reasons.append(f"intake errors: {state['intake_errors']}")

    agent = agent_determinations(state)
    events = [
        event(state, config, "intake (code)", "receipt_timestamp_captured", after=state.get("receipt_timestamp")),
        event(state, config, "agent", "determinations_proposed", after=agent),
    ]
    if reasons and not eval_mode(config):
        events.append(event(state, config, "review_routing (code)", "review_required", after=reasons))
        return {"review_required": True, "review_reasons": reasons, "audit_events": events}

    if reasons:  # eval mode: a reviewer would have been asked; record the agent's decision
        events.append(event(state, config, "review_routing (code)", "review_skipped_eval_mode", after=reasons))
        final = {**agent, "decided_by": "agent (eval_mode, no human review)"}
    else:
        events.append(event(state, config, "review_routing (code)", "auto_committed, sampled QC in production"))
        final = {**agent, "decided_by": "agent (auto-committed: clean non-serious)"}
    return {"review_required": bool(reasons), "review_reasons": reasons, "final": final, "audit_events": events}


def after_review_routing(state):
    return "case_signoff" if state["review_required"] and "final" not in state else "commit"


# ------------------------------------------------------------ sign-off


def signoff_payload(state):
    exp, ser, dup = state["expectedness"], state["seriousness"], state["duplicate"]
    flags = list(state["review_reasons"])
    flags += [f"reaction '{r['reaction']}': {r['note']}" for r in exp["reactions"] if r["needs_review"] and r.get("note")]
    flags += [f"seriousness quote dropped (not in message): {d}" for d in ser.get("dropped", [])]
    due = state["due_date"]
    return {
        "needs_review_flags": flags,
        "case": {"ref": state.get("ref"), "source": state.get("source_type"), "received": state.get("receipt_timestamp"),
                 "drug": state.get("target_drug")},
        "proposed_route": state["route"],
        "due_date": due,
        "days_remaining": (date.fromisoformat(due) - date.today()).days if due else None,
        "deadline_rule": "serious AND unexpected: 15 calendar days from receipt (21 CFR 314.80)",
        "seriousness": {"is_serious": ser["is_serious"],
                        "criteria": [{"criterion": k, "met": v["met"], "quote": v["quote"]} for k, v in ser["criteria"].items()]},
        "reactions": [{"index": i, "reaction": r["reaction"], "expectedness": r["expectedness"],
                       "label_quote": r["label_quote"], "reasoning": r["reasoning"], "needs_review": r["needs_review"]}
                      for i, r in enumerate(exp["reactions"])],
        "label": {"drug": exp["label_drug"], "effective_time": exp["label_effective_time"]},
        "duplicate": ({"candidate": dup["duplicate_of"], "reasoning": dup["reasoning"],
                       "merge": "NOT merged until you confirm"} if dup["duplicate_of"] else None),
        "how_to_respond": {
            "approve": {"action": "approve", "reviewer": "<your name>"},
            "correct": {"action": "correct", "reviewer": "<your name>", "reason_code": REASON_CODES,
                        "note": "<required free text>",
                        "corrections": {"is_serious": "true|false (optional)",
                                        "reactions": [{"index": 0, "expectedness": EXPECTEDNESS_VALUES}],
                                        "duplicate_of": "<case id> or null (optional)"}},
        },
    }


def validate_response(r, n_reactions):
    errors = []
    if not isinstance(r, dict):
        return ["response must be an object"]
    if not r.get("reviewer"):
        errors.append("reviewer name is required")
    if r.get("action") == "approve":
        return errors
    if r.get("action") != "correct":
        return errors + ["action must be 'approve' or 'correct'"]
    if r.get("reason_code") not in REASON_CODES:
        errors.append(f"reason_code must be one of {REASON_CODES}")
    if not r.get("note"):
        errors.append("note is required for a correction")
    c = r.get("corrections") or {}
    if not c:
        errors.append("corrections are required")
    if "is_serious" in c and not isinstance(c["is_serious"], bool):
        errors.append("corrections.is_serious must be true or false")
    for x in c.get("reactions", []):
        if not isinstance(x.get("index"), int) or not 0 <= x["index"] < n_reactions:
            errors.append(f"reaction index {x.get('index')} out of range")
        if x.get("expectedness") not in EXPECTEDNESS_VALUES:
            errors.append(f"reaction expectedness must be one of {EXPECTEDNESS_VALUES}")
    return errors


def case_signoff(state, config):
    payload = signoff_payload(state)
    n = len(state["expectedness"]["reactions"])
    response = interrupt(payload)
    while errors := validate_response(response, n):
        response = interrupt({**payload, "errors_in_your_last_response": errors})

    agent = agent_determinations(state)
    reviewer = response["reviewer"]

    if response["action"] == "approve":
        final = {**agent, "decided_by": f"agent, approved by {reviewer}"}
        review = {"reviewer": reviewer, "action": "approve", "reason_code": None, "note": response.get("note")}
        action = "reviewer_approved" + (" (duplicate merge confirmed)" if agent["duplicate_of"] else "")
        return {"final": final, "review": review,
                "audit_events": [event(state, config, reviewer, action, before=agent, after=final)]}

    # Correction: apply the reviewer's determinations, then CODE recomputes.
    c = response["corrections"]
    is_serious = c.get("is_serious", agent["is_serious"])
    reactions = [dict(r) for r in agent["reactions"]]
    for x in c.get("reactions", []):
        reactions[x["index"]]["expectedness"] = x["expectedness"]
    duplicate_of = c["duplicate_of"] if "duplicate_of" in c else agent["duplicate_of"]
    route, due, basis = decide_route(duplicate_of, is_serious,
                                     any(r["expectedness"] == "unexpected" for r in reactions),
                                     state.get("receipt_timestamp"))   # unchanged: captured once at intake
    final = {"is_serious": is_serious, "reactions": reactions, "duplicate_of": duplicate_of,
             "route": route, "due_date": due, "clock_basis": basis,
             "decided_by": f"reviewer {reviewer} ({response['reason_code']}); route recomputed by code"}
    review = {"reviewer": reviewer, "action": "correct", "reason_code": response["reason_code"], "note": response["note"],
              "corrections": c}
    return {
        "final": final, "review": review, "route": route, "due_date": due, "clock_basis": basis,
        "audit_events": [event(state, config, reviewer, "reviewer_corrected", before=agent, after=final,
                               reason_code=response["reason_code"], note=response["note"])],
    }


# ------------------------------------------------------------ commit


def correction_example(state, review, final):
    """A reviewer correction, shaped like a dataset example, so it can become a test case."""
    return {
        "inputs": {"header": state.get("header"), "narrative": state.get("narrative")},
        "outputs": {
            "valid": True, "missing_element": None,
            "is_serious": final["is_serious"],
            "reaction_expectedness": [{"term": r["reaction"], "expectedness": r["expectedness"]} for r in final["reactions"]],
            "case_expectedness": "unexpected" if any(r["expectedness"] == "unexpected" for r in final["reactions"]) else "expected",
            "reporting_route": final["route"], "due_date": final["due_date"], "duplicate_of": final["duplicate_of"],
        },
        "metadata": {"source": "reviewer_correction", "reviewer": review["reviewer"], "reason_code": review["reason_code"],
                     "note": review["note"], "corrected_at": records.now(), "ref": state.get("ref"),
                     "agent_before": agent_determinations(state), "prompt_versions": prompt_versions()},
    }


def commit(state, config):
    tid = thread_id(config, state)
    done = event(state, config, "commit (code)", "case_committed",
                 after={"route": (state.get("final") or {}).get("route", state.get("route")),
                        "eval_mode": eval_mode(config)})
    if eval_mode(config):
        return {"audit_events": [done]}

    review = state.get("review") or {}
    record = {
        "thread_id": tid, "ref": state.get("ref"), "source_type": state.get("source_type"),
        "receipt_timestamp": state.get("receipt_timestamp"),
        "valid": state.get("valid"), "missing_elements": state.get("missing_elements"),
        "target_drug": state.get("target_drug"),
        "final": state.get("final"), "review": review,
        "agent": {k: state.get(k) for k in ("extraction", "seriousness", "expectedness", "duplicate", "validity_basis")},
        "followup": state.get("followup"), "followup_review": state.get("followup_review"),
        "committed_at": records.now(),
    }
    records.write_case(tid, record)
    if review.get("action") == "correct":
        records.append_correction(correction_example(state, review, state["final"]))
    fr = state.get("followup_review") or {}
    if fr.get("action") in ("approve", "edit"):
        records.write_outbox(tid, {"type": fr.get("type", "followup_query"),
                                   "to": fr["channel"], "message": fr["message"], "questions": fr["questions"],
                                   "approved_by": fr["reviewer"], "approved_at": records.now(), "ref": state.get("ref"),
                                   "sent": False, "note": "outbox only: no real email or call is made"})
    records.append_audit(state.get("audit_events", []) + [done])
    return {"audit_events": [done]}
