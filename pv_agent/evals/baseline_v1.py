"""V1 baseline: ONE LangChain create_agent that does everything in a single pass.

Two tools (the drug's label sections, a case-store search) and the same model
as V2. It returns the same output schema as V2 -- including route and due_date
computed BY THE MODEL. No deterministic clock, no specialists, no code
decisions. This is the "just ask one agent" design V2 is compared against.
"""

import json
import time
from datetime import date, timedelta
from typing import Literal

from langchain.agents import create_agent
from langchain.agents.structured_output import ProviderStrategy
from langchain_core.callbacks import UsageMetadataCallbackHandler
from langchain_core.messages import AIMessage
from pydantic import BaseModel, Field

from pv_agent import config
from pv_agent.data_access import case_store, labels
from pv_agent.evals.common import cost_usd, message_text, total_tokens
from pv_agent.llm import chat

DRUGS = Literal["lisinopril", "metformin", "warfarin", "sertraline", "atorvastatin", "levothyroxine"]
ELEMENTS = Literal["no_identifiable_patient", "no_identifiable_reporter", "no_suspect_drug", "no_adverse_event"]


class BCriterion(BaseModel):
    met: bool
    quote: str | None = Field(description="Exact words from the message, or null.")


class BCriteria(BaseModel):
    death: BCriterion
    life_threatening: BCriterion
    hospitalization: BCriterion
    disability: BCriterion
    congenital_anomaly: BCriterion
    medically_important: BCriterion


class BReaction(BaseModel):
    reaction: str = Field(description="The event in the reporter's words.")
    quote: str = Field(description="Exact words from the message.")
    expectedness: Literal["expected", "unexpected", "not_applicable"]
    label_quote: str = Field(description="Exact label sentence relied on, or NOT FOUND.")


class BaselineOutput(BaseModel):
    valid: bool
    missing_elements: list[ELEMENTS]
    target_drug: DRUGS | None
    is_serious: bool | None
    seriousness_criteria: BCriteria | None
    reactions: list[BReaction]
    route: Literal["expedited_15_day", "periodic", "follow_up_required", "merge_with_existing"]
    due_date: str | None = Field(description="YYYY-MM-DD, or null.")
    duplicate_of: str | None = Field(description="case_id of an earlier report of the same case, or null.")


PROMPT = """You triage adverse event intake messages for a drug safety team. Read the message and produce the full assessment.

1. Validity: a valid report has an identifiable patient, an identifiable reporter (name, contact or healthcare qualification), a suspect drug that is one of lisinopril, metformin, warfarin, sertraline, atorvastatin, levothyroxine, and at least one adverse event. List any missing elements. If invalid, route is follow_up_required.
2. Seriousness (21 CFR 314.80): death, life-threatening (immediate risk of death as it occurred), hospitalization (inpatient admission or prolonged stay), disability, congenital anomaly, medically important (reporter says medically significant, or an important medical event). Quote the message.
3. Expectedness: use get_label_sections for the drug. A reaction is expected only if the label lists it; more specific or more severe than the label = unexpected; disease being treated / lack of effect / product issue = not_applicable. Quote the label or write NOT FOUND.
4. Duplicates: use search_case_store with the drug and the receipt date to see earlier reports. A duplicate is the same patient and the same event.
5. Route: duplicate -> merge_with_existing; not serious -> periodic; serious AND any unexpected reaction -> expedited_15_day with due_date = receipt date + 15 calendar days; otherwise periodic."""


def get_label_sections(drug: str) -> str:
    """The approved US label sections (adverse reactions, warnings, boxed warning, precautions) for one of the six drugs."""
    label = labels().get(drug.lower())
    if not label:
        return f"no label for {drug!r}; drugs: {sorted(labels())}"
    return "\n\n".join(f"## {s}\n{label[s]}" for s in config.EXPECTEDNESS_SECTIONS if label.get(s))


def search_case_store(drug: str, received_before: str) -> str:
    """Earlier reports in the safety database for this drug, received in the 120 days strictly before received_before (YYYY-MM-DD)."""
    try:
        before = date.fromisoformat(received_before[:10])
    except ValueError:
        return "received_before must be YYYY-MM-DD"
    earliest = before - timedelta(days=config.DUPLICATE_WINDOW_DAYS)
    rows = [r for r in case_store() if r["target_drug"] == drug.lower()
            and earliest <= date.fromisoformat(r["receive_date"]) < before]
    return json.dumps(rows)


_agent = create_agent(model=chat(), tools=[get_label_sections, search_case_store], system_prompt=PROMPT,
                      response_format=ProviderStrategy(BaselineOutput), name="baseline_v1_agent")


def run_v1(inputs: dict) -> dict:
    handler = UsageMetadataCallbackHandler()
    start = time.time()
    result = _agent.invoke({"messages": [("user", message_text(inputs))]},
                           config={"callbacks": [handler], "tags": ["story=4", "baseline_v1"],
                                   "metadata": {"system": "v1_baseline"}})
    out = result["structured_response"].model_dump()
    tool_calls = [{"tool": tc["name"], "args": tc["args"]}
                  for m in result["messages"] if isinstance(m, AIMessage) for tc in m.tool_calls]

    reactions = out["reactions"]
    claims = [{"kind": "reaction", "quote": r["quote"], "source": "message"} for r in reactions]
    claims += [{"kind": "label_quote", "quote": r["label_quote"], "source": "label"}
               for r in reactions if r["expectedness"] == "expected"]
    crit = out["seriousness_criteria"] or {}
    claims += [{"kind": f"seriousness.{k}", "quote": v["quote"], "source": "message"} for k, v in crit.items() if v["met"]]

    out.update(
        case_expectedness=(("unexpected" if any(r["expectedness"] == "unexpected" for r in reactions) else "expected")
                           if out["valid"] else None),
        claims=claims, trajectory=["baseline_v1_agent"], tool_calls=tool_calls, followup_draft=None,
        usage=handler.usage_metadata, cost_usd=cost_usd(handler.usage_metadata),
        total_tokens=total_tokens(handler.usage_metadata), latency_s=round(time.time() - start, 2),
    )
    return out
