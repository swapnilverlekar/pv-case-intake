"""follow-up planner: the ONE real agent in the system (LangChain create_agent).

Runs only on the follow_up_required branch. The model chooses which tools to
call and which questions to ask, because the right questions depend on what
is missing and on what the report hints at. The tools are read-only views of
this case plus one tool that records the draft. Nothing is sent: an approved
draft goes to runtime/outbox/ via the commit node.

followup_review pauses the graph (LangGraph interrupt): approve / edit / reject.
"""

import json

from langchain.agents import create_agent
from langchain_core.messages import AIMessage
from langgraph.types import interrupt

from pv_agent.llm import chat
from pv_agent.nodes.review import event, eval_mode

PLANNER_PROMPT = """You plan the next step for an adverse event report that cannot be processed yet because a required element is missing.

First call get_case_facts and get_missing_elements. Then choose ONE action:
- draft_followup_message: ask the reporter for what is missing (call get_reporter_channel first).
- draft_quality_referral: when the ONLY missing element is no_adverse_event AND the report describes a product issue (appearance, packaging, quantity, quality, supply) with no harm to the patient. This is an internal note to the product quality team; nothing goes back to the reporter.

Never re-ask what the report already says. Before drafting, check every question against the message and drop any question the message already answers.
Worked example: a partner forwards a doctor's query that the metformin tablets in the latest pack are a different colour, and says "The patient is fine and has had no problems." Asking the reporter whether the patient had any health problem is WRONG: the report already answers it. The only missing element is an adverse event, the report describes a product issue with no harm, so the right action is draft_quality_referral.

Rules for a follow-up message:
- Ask ONLY for what is missing, plus the exception below.
- If anything in the report sounds severe (a hospital stay, a death, an emergency, a life-threatening situation), ALSO ask about the outcome and whether the patient was admitted to hospital: a hidden 15-day case must be found early.
- Plain, polite language that fits the reporter: everyday words for a patient or family member, clinical language for a healthcare professional, a concise case query for a partner company.
- Never suggest whether the drug caused the event, and never mention reporting deadlines or regulatory categories.
- Keep it short. Number the questions.
- If there is no way to reach the reporter, still draft the message and say so in the channel field.

Rules for a quality referral: a short internal note naming the product, the issue as reported, and the batch or pack details if given; no questions to the reporter, no clinical content the report does not give."""


def followup_planner(state, config):
    drafted = {}
    ex = state["extraction"]

    def get_case_facts() -> str:
        """The report as received: receipt details, the message, and the facts extracted from it (with quotes)."""
        return json.dumps({
            "received": state.get("receipt_timestamp"), "source_type": state.get("source_type"), "ref": state.get("ref"),
            "message": state["narrative"],
            "patient": ex["patient"], "reporter": ex["reporter"],
            "products": state.get("products"), "reactions": ex["reactions"],
        }, ensure_ascii=False)

    def get_missing_elements() -> str:
        """Which of the four required elements (identifiable patient, identifiable reporter, suspect drug, adverse event) are missing, and the evidence for each."""
        return json.dumps({"missing": state["missing_elements"], "basis": state["validity_basis"]}, ensure_ascii=False)

    def get_reporter_channel() -> str:
        """How the reporter can be reached, from the source type and any contact details in the message."""
        source = (state.get("source_type") or "").lower()
        contact = ex["reporter"].get("contact")
        if "partner" in source:
            channel = "partner_case_query: ask the forwarding partner's safety contact to obtain the information from the original reporter"
        elif "email" in source:
            channel = "email_reply: reply to the sender's email address"
        elif "voicemail" in source or "call" in source:
            channel = (f"phone_callback: {contact}" if contact
                       else "phone_callback: no number given in the message; only the caller ID, if the phone system captured it")
        else:
            channel = "unknown"
        anonymous = not (ex["reporter"].get("name") or contact)
        return json.dumps({"channel": channel, "reporter_type": ex["reporter"]["type"],
                           "reporter_gave_name_or_contact": not anonymous})

    def draft_followup_message(channel: str, questions: list[str], message: str) -> str:
        """Record a follow-up query to the reporter: the channel to use, the numbered questions, and the full message text."""
        drafted.clear()
        drafted.update({"type": "followup_query", "channel": channel, "questions": questions, "message": message})
        return "Follow-up query recorded."

    def draft_quality_referral(product_issue: str, summary: str) -> str:
        """Record an internal referral to the product quality team for a product issue with no harm to the patient. No questions go to the reporter."""
        drafted.clear()
        drafted.update({"type": "quality_referral", "channel": "internal: product quality team",
                        "questions": [], "product_issue": product_issue, "message": summary})
        return "Quality referral recorded."

    agent = create_agent(
        model=chat(),
        tools=[get_case_facts, get_missing_elements, get_reporter_channel, draft_followup_message, draft_quality_referral],
        system_prompt=PLANNER_PROMPT,
        name="followup_planner_agent",
    )
    result = agent.invoke({"messages": [("user", "Plan the follow-up for this report.")]}, config=config)

    tool_calls = [{"tool": tc["name"], "args": tc["args"]}
                  for m in result["messages"] if isinstance(m, AIMessage) for tc in m.tool_calls]
    followup = {"draft": drafted or None, "tool_calls": tool_calls,
                "missing_elements": state["missing_elements"],
                "error": None if drafted else "the planner finished without drafting a message"}
    return {"followup": followup,
            "audit_events": [event(state, config, "followup_planner (agent)", "followup_drafted",
                                   after={"draft": drafted or None, "tools_called": [t["tool"] for t in tool_calls]})]}


def followup_review(state, config):
    draft = state["followup"]["draft"]
    if eval_mode(config):
        return {"followup_review": {"action": "skipped_eval_mode"},
                "audit_events": [event(state, config, "review_routing (code)", "followup_review_skipped_eval_mode")]}

    payload = {"draft_type": (draft or {}).get("type"), "missing_elements": state["missing_elements"], "draft": draft,
               "planner_error": state["followup"]["error"],
               "how_to_respond": {"approve": {"action": "approve", "reviewer": "<your name>"},
                                  "edit": {"action": "edit", "reviewer": "<your name>", "message": "<edited text>"},
                                  "reject": {"action": "reject", "reviewer": "<your name>", "note": "<why>"}}}
    response = interrupt(payload)
    while True:
        errors = []
        if not isinstance(response, dict) or response.get("action") not in ("approve", "edit", "reject"):
            errors.append("action must be approve, edit or reject")
        elif not response.get("reviewer"):
            errors.append("reviewer name is required")
        elif response["action"] == "edit" and not response.get("message"):
            errors.append("an edit needs the edited message")
        elif response["action"] == "approve" and not draft:
            errors.append("there is no draft to approve; edit or reject")
        if not errors:
            break
        response = interrupt({**payload, "errors_in_your_last_response": errors})

    action = response["action"]
    message = response.get("message") if action == "edit" else (draft or {}).get("message")
    review = {"action": action, "reviewer": response["reviewer"], "note": response.get("note"),
              "type": (draft or {}).get("type", "followup_query"),
              "channel": (draft or {}).get("channel"), "questions": (draft or {}).get("questions"), "message": message}
    return {"followup_review": review,
            "final": {"route": "follow_up_required", "decided_by": f"followup {action} by {response['reviewer']}"},
            "audit_events": [event(state, config, response["reviewer"], f"followup_{action}",
                                   before=draft, after=message if action != "reject" else None, note=response.get("note"))]}
