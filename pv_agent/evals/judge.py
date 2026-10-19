"""LLM judge for follow-up message quality (invalid examples only), plus the
human calibration of that judge.

The judge is a different, stronger model (config.JUDGE_MODEL) than the system
under test. Its scores are trusted only as far as they agree with a human:
`judge_agreement` compares them with the scores in judge_calibration.csv.
"""

import csv
import json

from pydantic import BaseModel, Field

from pv_agent import config
from pv_agent.llm import structured

CALIBRATION_CSV = config.REPO / "AE_Data" / "data" / "judge_calibration.csv"
JUDGE_SCORES = config.REPO / "AE_Data" / "data" / "judge_calibration_judge_scores.json"  # kept apart: no anchoring


class FollowupJudgement(BaseModel):
    asks_exactly_missing: bool = Field(description="Asks for every missing element and does not re-ask what the report already gives.")
    severity_questions_appropriate: bool = Field(description="Asks about outcome/hospitalisation ONLY if the event sounds severe (hospital, death, emergency, life-threatening); true if it correctly omits them for a mild event.")
    no_clinical_advice: bool
    polite_and_reporter_appropriate: bool = Field(description="Plain and polite; tone and vocabulary fit the reporter (consumer, HCP, partner company).")
    no_invented_facts: bool = Field(description="States nothing about the case that the report does not say.")
    score: int = Field(ge=1, le=5, description="Overall quality, 1 (unusable) to 5 (send as is).")
    reasoning: str = Field(description="Two sentences at most.")


RUBRIC = """You grade a follow-up message a drug safety team drafted to the reporter of an adverse event report that cannot be processed yet because required elements are missing.

Score each rubric item, then an overall score from 1 to 5:
5 = send as is; 4 = minor wording fixes; 3 = usable after a real edit; 2 = wrong or missing questions; 1 = unusable or harmful.

Rubric:
- asks for exactly the missing elements (no more, no fewer; does not re-ask what the report already says)
- asks about outcome / hospitalisation ONLY when the event sounds severe
- gives no clinical advice
- polite, plain, and appropriate to the reporter (patient/family, healthcare professional, partner company)
- invents no facts about the case"""


def judge_followup(report_text, missing_elements, draft):
    return structured(FollowupJudgement, model=config.JUDGE_MODEL).invoke([
        ("system", RUBRIC),
        ("human", f"Original report:\n{report_text}\n\nMissing elements: {missing_elements}\n\n"
                  f"Channel: {draft.get('channel')}\n\nDrafted follow-up message:\n{draft.get('message')}"),
    ])


def followup_quality(inputs, outputs, reference_outputs):
    """LangSmith evaluator: only where the system drafted a follow-up."""
    draft = outputs.get("followup_draft")
    if not draft or not draft.get("message"):
        return {"key": "followup_quality", "score": None}
    missing = sorted((reference_outputs.get("missing_element") or []) if not reference_outputs["valid"]
                     else outputs.get("missing_elements") or [])
    j = judge_followup(f"{inputs.get('header')}\n\n{inputs.get('narrative')}", missing, draft)
    return {"key": "followup_quality", "score": j.score, "comment": json.dumps(j.model_dump())}


# ---------------------------------------------------------- calibration


def write_calibration(drafts):
    """drafts: [{draft_id, example_key, repetition, report, missing, channel, message, judge}]."""
    with CALIBRATION_CSV.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["draft_id", "example_key", "repetition", "missing_elements", "report", "channel",
                    "draft_message", "my_score_1to5", "my_notes"])
        for d in drafts:
            w.writerow([d["draft_id"], d["example_key"], d["repetition"], ", ".join(d["missing"]), d["report"],
                        d["channel"], d["message"], "", ""])
    JUDGE_SCORES.write_text(json.dumps({d["draft_id"]: d["judge"] for d in drafts}, indent=2))


def judge_agreement():
    """Judge vs human on the calibration drafts: exact and within-1 agreement."""
    judge = json.loads(JUDGE_SCORES.read_text())
    pairs = []
    with CALIBRATION_CSV.open() as f:
        for row in csv.DictReader(f):
            if row["my_score_1to5"].strip():
                pairs.append((int(row["my_score_1to5"]), judge[row["draft_id"]]["score"], row["draft_id"]))
    if not pairs:
        return None
    exact = sum(h == j for h, j, _ in pairs) / len(pairs)
    within1 = sum(abs(h - j) <= 1 for h, j, _ in pairs) / len(pairs)
    return {"n": len(pairs), "exact": exact, "within_1": within1,
            "disagreements": [(d, h, j) for h, j, d in pairs if abs(h - j) > 1]}


if __name__ == "__main__":
    print(json.dumps(judge_agreement(), indent=2))
