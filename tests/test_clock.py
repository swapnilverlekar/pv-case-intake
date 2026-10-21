"""The reporting clock (nodes/clock.py): every row of the 21 CFR 314.80 table,
the 15-calendar-day arithmetic, and independence from model output."""

import inspect

import pytest

from pv_agent import config
from pv_agent.nodes.clock import clock, decide_route
from pv_agent.nodes.validity import validity
from tests.conftest import extraction, product

RECEIVED = "2022-01-05T18:39:30+00:00"


# --- the 314.80 table -------------------------------------------------------

def test_invalid_case_routes_to_follow_up_with_no_deadline():
    # An invalid report never reaches the clock: the gate routes it to follow-up.
    out = validity({"extraction": extraction(reactions=False), "products": [product()], "target_drug": "warfarin"})
    assert out["route"] == "follow_up_required"
    assert "due_date" not in out


@pytest.mark.parametrize("any_unexpected", [False, True])
def test_valid_non_serious_is_periodic_whatever_the_expectedness(any_unexpected):
    route, due, _ = decide_route(None, False, any_unexpected, RECEIVED)
    assert (route, due) == ("periodic", None)


def test_serious_and_expected_is_periodic():
    route, due, _ = decide_route(None, True, False, RECEIVED)
    assert (route, due) == ("periodic", None)


def test_serious_and_unexpected_is_15_day_with_due_date():
    route, due, _ = decide_route(None, True, True, RECEIVED)
    assert route == "expedited_15_day"
    assert due == "2022-01-20"


def test_duplicate_merges_and_starts_no_new_clock():
    route, due, _ = decide_route("20281949", True, True, RECEIVED)
    assert (route, due) == ("merge_with_existing", None)


def test_expedited_without_receipt_timestamp_sets_no_due_date():
    route, due, basis = decide_route(None, True, True, None)
    assert route == "expedited_15_day" and due is None
    assert "NO receipt timestamp" in basis


# --- 15 calendar days -------------------------------------------------------

def test_deadline_is_15_calendar_days():
    assert config.EXPEDITED_DAYS == 15


@pytest.mark.parametrize("received, due", [
    ("2022-01-20T10:00:00+00:00", "2022-02-04"),  # crosses a month end
    ("2022-01-31T23:59:59+00:00", "2022-02-15"),  # received on the last second of a month
    ("2024-02-20T09:00:00+00:00", "2024-03-06"),  # leap-year February
    ("2022-12-25T12:00:00+00:00", "2023-01-09"),  # crosses a year end
    ("2022-12-31T00:00:00+00:00", "2023-01-15"),  # received on the last day of the year
])
def test_due_date_boundaries(received, due):
    assert decide_route(None, True, True, received)[1] == due


def test_due_date_uses_the_calendar_date_in_the_receipt_timestamps_own_offset():
    # 23:30 on 31 Jan in New York is 1 Feb in UTC. The clock counts from the
    # date as recorded in the timestamp (31 Jan), not from the UTC date.
    assert decide_route(None, True, True, "2022-01-31T23:30:00-05:00")[1] == "2022-02-15"


# --- independence from model output -----------------------------------------

def test_decide_route_takes_only_booleans_ids_and_the_timestamp():
    assert list(inspect.signature(decide_route).parameters) == [
        "duplicate_of", "is_serious", "any_unexpected", "receipt_timestamp"]


def test_clock_ignores_everything_else_the_model_returned():
    minimal = {
        "receipt_timestamp": RECEIVED,
        "seriousness": {"is_serious": True},
        "expectedness": {"any_unexpected": True},
        "duplicate": {"duplicate_of": None},
    }
    noisy = {
        "receipt_timestamp": RECEIVED,
        "seriousness": {"is_serious": True, "due_date": "1999-01-01", "criteria": {"death": {"met": True}}},
        "expectedness": {"any_unexpected": True, "due_date": "1999-01-01", "label_effective_time": "19990101",
                         "reactions": [{"reaction": "x", "expectedness": "unexpected", "due_date": "1999-01-01"}]},
        "duplicate": {"duplicate_of": None, "reasoning": "deadline is tomorrow", "due_date": "1999-01-01"},
        "due_date": "1999-01-01",            # a stale or model-written value in state
        "extraction": {"note": "report says it is due on 2099-12-31"},
    }
    assert clock(minimal) == clock(noisy)
    assert clock(noisy)["due_date"] == "2022-01-20"
