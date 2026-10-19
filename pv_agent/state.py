"""Graph state. The receipt timestamp is write-once: no node can change it after intake."""

import operator
from typing import Annotated, Any, TypedDict


def write_once(old, new):
    """Reducer for the legal clock start: the first value sticks; any attempt
    to change it is an error, not a silent overwrite."""
    if old is None:
        return new
    if new is not None and new != old:
        raise ValueError(f"receipt_timestamp is write-once: {old!r} cannot become {new!r}")
    return old


class CaseState(TypedDict, total=False):
    # Inputs: the message, nothing else.
    header: Any                 # dict {source, received, ref} or the header text
    narrative: str

    # intake (code)
    receipt_timestamp: Annotated[str | None, write_once]
    source_type: str | None
    ref: str | None
    intake_errors: list[str]

    # extraction (model) -- every value carries the quote it came from
    extraction: dict
    rejected_evidence: list[dict]   # values dropped because their quote is not in the message

    # product normalization (code)
    products: list[dict]
    target_drug: str | None

    # validity gate (code)
    valid: bool
    missing_elements: list[str]
    validity_basis: dict

    # specialists, in parallel -- each writes only its own key
    seriousness: dict           # per criterion: met + quote; is_serious computed in code
    expectedness: dict          # per reaction: expected/unexpected/not_applicable + label quote
    duplicate: dict             # candidates considered, duplicate_of, reasoning

    # clock (code)
    route: str
    due_date: str | None
    clock_basis: str

    # review routing (code) and sign-off (human, interrupt)
    review_required: bool
    review_reasons: list[str]
    final: dict                 # the determinations committed: agent's, or reviewer-corrected
    review: dict                # who reviewed, action, reason_code, note

    # follow-up planner (agent) and its review (human, interrupt)
    followup: dict
    followup_review: dict

    # audit events gathered along the way; the commit node writes them once
    audit_events: Annotated[list[dict], operator.add]

    # node path, appended by every node (graph.py wraps each node); parallel
    # specialists may appear in any order
    trajectory: Annotated[list[str], operator.add]
