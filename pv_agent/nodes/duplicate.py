"""duplicate check: code pre-filters the case store, one LLM call compares.

Only records received STRICTLY BEFORE this report's receipt date are visible:
the database as it was when the report arrived.
"""

from datetime import date, datetime, timedelta

from pydantic import BaseModel, Field

from pv_agent import config
from pv_agent.data_access import case_store
from pv_agent.llm import structured

YEARS_PER_UNIT = {"year": 1, "years": 1, "decade": 10, "month": 1 / 12, "months": 1 / 12,
                  "week": 1 / 52, "weeks": 1 / 52, "day": 1 / 365, "days": 1 / 365}


def age_years(value, unit):
    try:
        return float(value) * YEARS_PER_UNIT[unit]
    except (TypeError, ValueError, KeyError):
        return None


def candidates(state):
    received = datetime.fromisoformat(state["receipt_timestamp"]).date()
    earliest = received - timedelta(days=config.DUPLICATE_WINDOW_DAYS)
    patient = state["extraction"]["patient"]
    sex = patient["sex"]["value"]
    age = age_years(patient["age"]["value"], patient["age"]["unit"])

    out = []
    for r in case_store():
        r_date = date.fromisoformat(r["receive_date"])
        if not (earliest <= r_date < received):        # strictly before receipt
            continue
        if r["target_drug"] != state["target_drug"]:
            continue
        if sex and r["patient_sex"] in ("male", "female") and r["patient_sex"] != sex:
            continue
        r_age = age_years(r["patient_age"], r["patient_age_unit"])
        if age is not None and r_age is not None and abs(age - r_age) > config.DUPLICATE_AGE_TOLERANCE_YEARS:
            continue
        out.append(r)
    return out


class DuplicateDecision(BaseModel):
    duplicate_of: str | None = Field(description="The case_id this report describes again (same patient, same event), or null.")
    reasoning: str = Field(description="One line.")


SYSTEM = """You decide whether an incoming adverse event report describes a case already in the safety database: the SAME patient and the SAME event, possibly reported by a different person, in different words, with small differences (age off by a year, dates off by a few days).

Similar patients on the same drug with a DIFFERENT event, or clearly different timing, are NOT duplicates. If no candidate is the same case, answer null."""


def duplicate_check(state):
    pool = candidates(state)
    base = {"candidates_considered": [c["case_id"] for c in pool],
            "visible_before": state["receipt_timestamp"][:10]}
    if not pool:
        return {"duplicate": {**base, "duplicate_of": None, "reasoning": "no candidates after pre-filter", "llm_called": False}}

    ex = state["extraction"]
    incoming = {
        "patient": {"reference": ex["patient"]["reference"]["text"], "age": ex["patient"]["age"]["value"],
                    "age_unit": ex["patient"]["age"]["unit"], "sex": ex["patient"]["sex"]["value"]},
        "reporter_type": ex["reporter"]["type"],
        "drug": state["target_drug"],
        "reactions": [r["reporter_words"] for r in ex["reactions"]],
    }
    result = structured(DuplicateDecision).invoke([
        ("system", SYSTEM),
        ("human", f"Incoming report:\n{incoming}\n\nMessage:\n{state['narrative']}\n\nCandidates:\n{pool}"),
    ])
    dup = result.duplicate_of if result.duplicate_of in base["candidates_considered"] else None
    note = None if dup == result.duplicate_of else f"model answered {result.duplicate_of!r}, not a candidate; ignored"
    return {"duplicate": {**base, "duplicate_of": dup, "reasoning": result.reasoning, "llm_called": True, "note": note}}
