"""clock (code, no model): the reporting route and the legal deadline.

serious AND unexpected -> 15 calendar days from the receipt timestamp
captured at intake. No model computes, adjusts or explains this. The same
function recomputes the route after a reviewer correction.
"""

from datetime import datetime, timedelta

from pv_agent import config


def decide_route(duplicate_of, is_serious, any_unexpected, receipt_timestamp):
    """(route, due_date, basis). Pure: same inputs, same answer."""
    if duplicate_of:
        return "merge_with_existing", None, f"duplicate of {duplicate_of}: merge, no new clock"
    if not is_serious:
        return "periodic", None, "not serious"
    if any_unexpected:
        if not receipt_timestamp:
            return "expedited_15_day", None, "serious and unexpected, but NO receipt timestamp: due date cannot be set"
        received = datetime.fromisoformat(receipt_timestamp).date()
        due = received + timedelta(days=config.EXPEDITED_DAYS)
        return ("expedited_15_day", due.isoformat(),
                f"serious and unexpected: received {received} + {config.EXPEDITED_DAYS} calendar days")
    return "periodic", None, "serious, but every reaction expected or not applicable"


def clock(state):
    route, due, basis = decide_route(
        state["duplicate"]["duplicate_of"],
        state["seriousness"]["is_serious"],
        state["expectedness"]["any_unexpected"],
        state.get("receipt_timestamp"),
    )
    return {"route": route, "due_date": due, "clock_basis": basis}
