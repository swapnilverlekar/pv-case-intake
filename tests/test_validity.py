"""The validity gate (nodes/validity.py): the four ICSR elements."""

import pytest

from pv_agent.nodes.validity import validity
from tests.conftest import extraction, product


def gate(ex, products=None, target="warfarin"):
    return validity({"extraction": ex, "products": [product()] if products is None else products,
                     "target_drug": target})


def test_all_four_elements_present_is_valid():
    out = gate(extraction())
    assert out["valid"] is True
    assert out["missing_elements"] == []
    assert out["route"] == "pending_assessment"


@pytest.mark.parametrize("ex, products, missing", [
    (extraction(patient=False), None, "no_identifiable_patient"),
    (extraction(reporter=False), None, "no_identifiable_reporter"),
    (extraction(), [], "no_suspect_drug"),
    (extraction(reactions=False), None, "no_adverse_event"),
])
def test_each_missing_element_alone_makes_the_case_invalid(ex, products, missing):
    out = gate(ex, products)
    assert out["valid"] is False
    assert out["missing_elements"] == [missing]
    assert out["route"] == "follow_up_required"


def test_a_secondhand_patient_with_no_age_or_sex_is_not_identifiable():
    ex = extraction()
    ex["patient"] = {"reference": {"text": "a friend of a friend", "relationship": "unidentified_or_secondhand",
                                   "quote": "a friend of a friend"},
                     "age": {"value": None, "unit": None, "approximate": False, "quote": None},
                     "sex": {"value": None, "quote": None}}
    assert gate(ex)["missing_elements"] == ["no_identifiable_patient"]


def test_a_stated_hcp_qualification_identifies_the_reporter_without_name_or_contact():
    ex = extraction(reporter=False, reporter_type="pharmacist")
    ex["reporter"]["type_quote"] = "a pharmacist who did not give a name"
    assert gate(ex)["valid"] is True


def test_an_anonymous_consumer_is_not_identifiable():
    assert gate(extraction(reporter=False, reporter_type="consumer"))["missing_elements"] == ["no_identifiable_reporter"]


def test_a_drug_the_reporter_explicitly_rules_out_is_not_a_suspect():
    out = gate(extraction(), [product(role="explicitly_not_suspected")])
    assert out["missing_elements"] == ["no_suspect_drug"]


def test_a_product_that_is_not_one_of_our_six_is_not_a_suspect():
    out = gate(extraction(), [product(name="Eliquis", maps_to=None)], target=None)
    assert out["missing_elements"] == ["no_suspect_drug"]


def test_several_missing_elements_are_all_reported_in_a_fixed_order():
    out = gate(extraction(patient=False, reactions=False), [])
    assert out["missing_elements"] == ["no_identifiable_patient", "no_suspect_drug", "no_adverse_event"]
