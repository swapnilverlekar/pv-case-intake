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

PLANNER_PROMPT = """You plan the follow-up for an adverse event report that cannot be processed yet because a required element is missing.

Use the tools to see the case facts, what is missing, and how the reporter can be reached. Then write ONE follow-up message with draft_followup_message.

Rules:
- Ask ONLY for what is missing, plus the exception below. Do not re-ask what the report already says.
- If anything in the report sounds severe (a hospital stay, a death, an emergency, a life-threatening situation), ALSO ask about the outcome and whether the patient was admitted to hospital: a hidden 15-day case must be found early.
- Plain, polite language that fits the reporter: everyday words for a patient or family member, clinical language for a healthcare professional, a concise case query for a partner company.
- Never suggest whether the drug caused the event, and never mention reporting deadlines or regulatory categories.
- Keep it short. Number the questions.
- If there is no way to reach the reporter, still draft the message and say so in the channel field."""


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
        """Record the follow-up draft: the channel to use, the numbered questions, and the full message text."""
        drafted.update({"channel": channel, "questions": questions, "message": message})
        return "Draft recorded."

    agent = create_agent(
        model=chat(),
        tools=[get_case_facts, get_missing_elements, get_reporter_channel, draft_followup_message],
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

    payload = {"missing_elements": state["missing_elements"], "draft": draft,
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
              "channel": (draft or {}).get("channel"), "questions": (draft or {}).get("questions"), "message": message}
    return {"followup_review": review,
            "final": {"route": "follow_up_required", "decided_by": f"followup {action} by {response['reviewer']}"},
            "audit_events": [event(state, config, response["reviewer"], f"followup_{action}",
                                   before=draft, after=message if action != "reject" else None, note=response.get("note"))]}
