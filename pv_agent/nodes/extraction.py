"""extraction (model, structured output): evidence only, every value quoted.

The model reads the message and returns what it SAYS, each value with the
exact words it came from. Code then enforces "no quote, no value": any value
whose quote is not literally in the message is dropped and logged.
"""

import re
from typing import Literal

from pydantic import BaseModel, Field

from pv_agent.llm import is_quote_of, structured
from pv_agent.nodes.normalize import match

QUOTE = "Exact words copied from the message that state this, or null if the message does not say it."


class PatientReference(BaseModel):
    text: str | None = Field(description="How the message refers to the patient, verbatim (e.g. 'my mother', 'a patient of mine', 'someone at my church').")
    relationship: Literal[
        "reporter_is_patient", "family_member", "reporters_patient_or_customer",
        "other_specific_person", "unidentified_or_secondhand",
    ] | None = Field(description="Who the patient is relative to the reporter, as the message states it. Use unidentified_or_secondhand for someone the reporter cannot identify (a friend of a friend, 'someone I heard about').")
    quote: str | None = Field(description=QUOTE)


class Age(BaseModel):
    value: float | None = Field(description="The PATIENT's age as stated (60 for 'in his sixties'). Not anyone else's age.")
    unit: Literal["years", "months", "weeks", "days"] | None = None
    approximate: bool = Field(False, description="True for an age range or decade ('in his sixties').")
    quote: str | None = Field(description=QUOTE)


class Sex(BaseModel):
    value: Literal["female", "male"] | None = Field(description="The PATIENT's sex, only if stated, including by a pronoun or a word like 'my mother'. Not the sex of the reporter or anyone else in the message.")
    quote: str | None = Field(description=QUOTE)


class Patient(BaseModel):
    reference: PatientReference
    age: Age
    sex: Sex


class Reporter(BaseModel):
    type: Literal["consumer", "physician", "pharmacist", "other_hcp", "unknown"] = Field(description="The person who observed or was told about the event (for a forwarded partner report: the original reporter, not the forwarding company's staff). other_hcp = nurse, nurse practitioner, physician assistant, etc.")
    type_quote: str | None = Field(description=QUOTE)
    name: str | None = Field(description="The reporter's name if given (not the forwarding company's staff).")
    name_quote: str | None = Field(description=QUOTE)
    contact: str | None = Field(description="Any way to reach the reporter that the message gives or refers to: phone number, email, 'call me back on this number'.")
    contact_quote: str | None = Field(description=QUOTE)


class Product(BaseModel):
    name_as_written: str = Field(description="Only the drug's name (no dose or strength), copied exactly as written in the message. Its quote must contain these exact words.")
    role_as_stated: Literal["suspected", "explicitly_not_suspected", "unclear"] = Field(description="'explicitly_not_suspected' ONLY when the message explicitly says this drug is not suspected or not related. A drug that is simply mentioned is 'unclear'.")
    quote: str | None = Field(description=QUOTE)


class Reaction(BaseModel):
    reporter_words: str = Field(description="The event in the reporter's own words, copied verbatim from the message. Its quote must contain these exact words.")
    quote: str | None = Field(description=QUOTE)


class Extraction(BaseModel):
    patient: Patient
    reporter: Reporter
    products: list[Product] = Field(description="Every drug the message names or describes, including vague ones ('some blood pressure pill').")
    reactions: list[Reaction] = Field(description=(
        "Every adverse event: symptoms, diagnoses, abnormal findings. NOT outcomes or consequences of an "
        "event (death, hospital admission, recovery, treatment given) -- those are assessed separately. "
        "Exception: if the patient died and no cause or other event is given, record the death as the event. "
        "NOT product complaints (appearance, packaging, price) and not statements that the patient is fine."))


SYSTEM = """You extract evidence from an adverse event intake message for a drug safety team.

Extract only what the message says. Never infer, guess, or add anything. If the message does not state something, return null for it.

For every value, give the exact words from the message it came from, copied character for character, as a short span (a phrase or one sentence). No quote, no value."""


# ------------------------------------------------------- grounding (code)

grounded = is_quote_of


def sentence_naming(name, message):
    """The first sentence of the message that contains this drug name."""
    for sentence in re.split(r"(?<=[.!?])\s+|\n+", message):
        if re.search(r"\b" + re.escape(name) + r"\b", sentence, re.IGNORECASE):
            return sentence.strip()
    return None


def enforce_quotes(ex, message):
    """No quote, no value. Returns (cleaned extraction dict, rejected list)."""
    d = ex.model_dump()
    rejected = []

    def check(path, obj, value_keys, quote_key="quote"):
        if obj.get(quote_key) and grounded(obj[quote_key], message):
            return True
        if any(obj.get(k) not in (None, False, "unknown") for k in value_keys):
            rejected.append({"field": path, "value": {k: obj.get(k) for k in value_keys},
                             "quote": obj.get(quote_key), "reason": "quote missing or not in message"})
        for k in value_keys:
            obj[k] = None if k != "approximate" else False
        obj[quote_key] = None
        return False

    ref = d["patient"]["reference"]
    if ref.get("text") and ref.get("quote") and not grounded(ref["text"], ref["quote"]):
        ref["quote"] = None  # the reference must sit inside its own quote
    check("patient.reference", ref, ["text", "relationship"])
    check("patient.age", d["patient"]["age"], ["value", "unit", "approximate"])
    check("patient.sex", d["patient"]["sex"], ["value"])

    r = d["reporter"]
    if not check("reporter.type", r, ["type"], "type_quote"):
        r["type"] = "unknown"
    check("reporter.name", r, ["name"], "name_quote")
    check("reporter.contact", r, ["contact"], "contact_quote")

    def keep(kind, item, words_key, supports):
        ok = (grounded(item.get("quote"), message) and grounded(item[words_key], message)
              and supports(item[words_key], item["quote"]))
        if not ok:
            rejected.append({"field": kind, "value": item[words_key], "quote": item.get("quote"),
                             "reason": "quote not in message, value not in message, or quote does not support value"})
        return ok

    # Products: if the model's name or quote is not verbatim but the product is
    # one of our drugs and the message names it, code locates the sentence
    # that names it and uses that as the quote. The quote is then a real span.
    products = []
    for p in d["products"]:
        p["quote_source"] = "model"
        drug, matched, _ = match(p["name_as_written"])
        supported = grounded(p.get("quote"), message) and (
            grounded(p["name_as_written"], p["quote"]) or (drug and match(p["quote"])[0] == drug))
        if not supported and drug:
            sentence = sentence_naming(matched, message)
            if sentence:
                p["quote"], p["quote_source"], supported = sentence, "code_located", True
        if supported:
            products.append(p)
        else:
            rejected.append({"field": "product", "value": p["name_as_written"], "quote": p.get("quote"),
                             "reason": "quote not in message or does not name this drug"})
    d["products"] = products

    # Reactions: the quote must be in the message and contain the reporter's words.
    d["reactions"] = [x for x in d["reactions"]
                      if keep("reaction", x, "reporter_words", grounded)]
    return d, rejected


def extraction(state):
    message = state["narrative"]
    result = structured(Extraction).invoke([("system", SYSTEM), ("human", f"Message:\n\n{message}")])
    cleaned, rejected = enforce_quotes(result, message)
    return {"extraction": cleaned, "rejected_evidence": rejected}
