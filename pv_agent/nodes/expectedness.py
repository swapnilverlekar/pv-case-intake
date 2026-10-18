"""expectedness (one structured LLM call per case): each reaction against the
target drug's label.

Built independently of the answer key: nothing here comes from
derive_expectedness.py, term_decisions.csv or expectedness_synonyms.json.

Code enforces: "expected" needs a label sentence that exists verbatim in the
label. If it doesn't, or the model is unsure, the reaction is unexpected and
flagged for review -- the costly error is missing a 15-day case.
"""

from typing import Literal

from pydantic import BaseModel, Field

from pv_agent import config
from pv_agent.data_access import labels
from pv_agent.llm import is_quote_of, structured


class ReactionAssessment(BaseModel):
    reaction: str = Field(description="The reaction as given (the reporter's words).")
    expectedness: Literal["expected", "unexpected", "not_applicable"]
    label_quote: str = Field(description="The exact label sentence relied on, copied character for character, or NOT FOUND.")
    reasoning: str = Field(description="One line.")
    unsure: bool = Field(description="True if you are not confident. If unsure, expectedness must be 'unexpected'.")


class Expectedness(BaseModel):
    reactions: list[ReactionAssessment]


SYSTEM = """You assess whether adverse reactions are expected for a drug, using ONLY its approved US label (below) and the rule of 21 CFR 314.80.

- expected: the reaction is listed in the label. Quote the exact label sentence that lists it.
- unexpected: the reaction is not listed, OR it is more severe or more specific than what the label lists (e.g. the label lists "hepatitis" and the report is "hepatic necrosis"; the label lists "atrial arrhythmias" and the report is "atrial fibrillation"). A broader label term does not make a more specific or more severe event expected.
- not_applicable: not an adverse reaction: the disease the drug treats or lack of effect, or a product issue (packaging, quality, usage).

If you are unsure, answer unexpected and set unsure=true. Missing an unexpected reaction is the costly error. Quote the label exactly or write NOT FOUND."""


def label_text(drug):
    label = labels()[drug]
    return "\n\n".join(f"## {s}\n{label[s]}" for s in config.EXPECTEDNESS_SECTIONS if label.get(s))


def expectedness(state):
    drug = state["target_drug"]
    label = labels()[drug]
    text = label_text(drug)
    reactions = [r["reporter_words"] for r in state["extraction"]["reactions"]]

    system = [
        {"type": "text", "text": SYSTEM},
        # The label is the same for every case of this drug: cache it.
        {"type": "text", "text": f"# Label for {drug} (effective {label['effective_time']})\n\n{text}",
         "cache_control": {"type": "ephemeral"}},
    ]
    result = structured(Expectedness).invoke(
        [("system", system), ("human", f"Reactions to assess:\n" + "\n".join(f"- {r}" for r in reactions))],
        config={"metadata": {"label_drug": drug, "label_effective_time": label["effective_time"],
                             "label_spl_id": label.get("spl_id")}},
    )

    assessed = []
    for a in result.reactions:
        final, needs_review, note = a.expectedness, False, None
        if a.expectedness == "expected" and not is_quote_of(a.label_quote, text):
            final, needs_review, note = "unexpected", True, "label quote not found verbatim in the label; downgraded"
        if a.unsure:
            final, needs_review = ("unexpected" if final == "expected" else final), True
            note = note or "model unsure"
        assessed.append({**a.model_dump(), "model_expectedness": a.expectedness,
                         "expectedness": final, "needs_review": needs_review, "note": note})

    return {"expectedness": {
        "label_drug": drug,
        "label_effective_time": label["effective_time"],
        "reactions": assessed,
        "any_unexpected": any(r["expectedness"] == "unexpected" for r in assessed),
        "needs_review": any(r["needs_review"] for r in assessed),
    }}
