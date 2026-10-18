"""clock (code, no model): the reporting route and the legal deadline.

serious AND unexpected -> 15 calendar days from the receipt timestamp
captured at intake. No model computes, adjusts or explains this.
"""

from datetime import datetime, timedelta

from pv_agent import config


def clock(state):
    dup = state["duplicate"]["duplicate_of"]
    serious = state["seriousness"]["is_serious"]
    unexpected = state["expectedness"]["any_unexpected"]

    if dup:
        return {"route": "merge_with_existing", "due_date": None,
                "clock_basis": f"duplicate of {dup}: merge, no new clock"}
    if not serious:
        return {"route": "periodic", "due_date": None, "clock_basis": "not serious"}
    if unexpected:
        received = datetime.fromisoformat(state["receipt_timestamp"]).date()
        due = received + timedelta(days=config.EXPEDITED_DAYS)
        return {"route": "expedited_15_day", "due_date": due.isoformat(),
                "clock_basis": f"serious and unexpected: received {received} + {config.EXPEDITED_DAYS} calendar days"}
    return {"route": "periodic", "due_date": None,
            "clock_basis": "serious, but every reaction expected or not applicable"}
