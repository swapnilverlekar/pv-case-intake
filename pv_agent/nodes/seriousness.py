"""seriousness (one structured LLM call): evidence for each 21 CFR 314.80
criterion. Code decides is_serious and drops any quote not in the message."""

from pydantic import BaseModel, Field

from pv_agent.llm import is_quote_of, structured

CRITERIA = ["death", "life_threatening", "hospitalization", "disability", "congenital_anomaly", "medically_important"]


class Criterion(BaseModel):
    met: bool
    quote: str | None = Field(description="Exact words from the message that show this criterion is met, copied character for character. Null if not met.")


class Seriousness(BaseModel):
    death: Criterion = Field(description="The patient died.")
    life_threatening: Criterion = Field(description="The patient was at immediate risk of death from the event AS IT OCCURRED -- not an event that might have caused death had it been more severe.")
    hospitalization: Criterion = Field(description="Inpatient hospital admission, or prolongation of an existing hospital stay. An emergency-room visit without admission does not count.")
    disability: Criterion = Field(description="A persistent or significant incapacity, or substantial disruption of the ability to conduct normal life functions.")
    congenital_anomaly: Criterion = Field(description="A congenital anomaly or birth defect.")
    medically_important: Criterion = Field(description="The reporter states the event was medically significant or important, OR the event is of the kind the regulation lists as an important medical event (e.g. allergic bronchospasm needing intensive treatment, blood dyscrasias, convulsions not resulting in hospitalization, development of drug dependency).")


SYSTEM = """You assess an adverse event intake message against the serious adverse drug experience criteria of 21 CFR 314.80.

For each criterion, say whether the message shows it is met, and give the exact words from the message that show it. If you cannot quote the message, the criterion is not met. Judge only from what the message says; do not assume outcomes it does not state."""


def seriousness(state):
    message = state["narrative"]
    facts = {
        "patient": state["extraction"]["patient"],
        "reactions": [r["reporter_words"] for r in state["extraction"]["reactions"]],
    }
    result = structured(Seriousness).invoke([
        ("system", SYSTEM),
        ("human", f"Message:\n\n{message}\n\nExtracted facts:\n{facts}"),
    ])

    criteria, dropped = {}, []
    for name in CRITERIA:
        c = getattr(result, name)
        met = c.met and is_quote_of(c.quote, message)
        if c.met and not met:
            dropped.append({"criterion": name, "quote": c.quote, "reason": "quote not in message"})
        criteria[name] = {"met": met, "quote": c.quote if met else None}

    return {"seriousness": {
        "criteria": criteria,
        "is_serious": any(c["met"] for c in criteria.values()),  # decided in code
        "dropped": dropped,
    }}
