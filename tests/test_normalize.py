"""Drug normalisation (nodes/normalize.py, labels.py): names as written -> one of the six drugs."""

import pytest

from pv_agent.nodes.normalize import match, normalize


@pytest.mark.parametrize("written, drug", [
    ("Zestril", "lisinopril"),                 # brand on the pinned label
    ("Lipitor", "atorvastatin"),
    ("Jantoven", "warfarin"),
    ("Zoloft", "sertraline"),
    ("Synthroid", "levothyroxine"),
    ("Qbrelis", "lisinopril"),                 # brand alias (config.BRAND_ALIASES)
    ("Tirosint Sol", "levothyroxine"),
    ("Atorvastatin Calcium", "atorvastatin"),  # salt form
    ("Sertraline Hcl", "sertraline"),
    ("metformin er 750 mg", "metformin"),      # strength and release form in the name
    ("WARFARIN SODIUM", "warfarin"),           # case-insensitive
])
def test_brand_generic_and_salt_names_map_to_the_generic(written, drug):
    assert match(written)[0] == drug


@pytest.mark.parametrize("written", [
    "Eliquis", "some blood pressure pill", "a thyroid tablet", "Vaxigriptetra", "ibuprofen", "",
])
def test_an_unknown_drug_is_not_forced_onto_one_of_the_six(written):
    assert match(written) == (None, None, None)


def test_matching_is_whole_word_only():
    assert match("Lisinoprilx")[0] is None


def test_normalize_sets_target_to_the_first_suspected_drug_of_ours():
    out = normalize({"extraction": {"products": [
        {"name_as_written": "Vaxigriptetra", "role_as_stated": "suspected", "quote": "q"},
        {"name_as_written": "Zestril", "role_as_stated": "unclear", "quote": "q"},
    ]}})
    assert out["target_drug"] == "lisinopril"
    assert [p["maps_to"] for p in out["products"]] == [None, "lisinopril"]


def test_normalize_leaves_target_empty_when_no_product_is_ours():
    out = normalize({"extraction": {"products": [
        {"name_as_written": "Eliquis", "role_as_stated": "suspected", "quote": "q"}]}})
    assert out["target_drug"] is None


def test_a_drug_explicitly_ruled_out_does_not_become_the_target():
    out = normalize({"extraction": {"products": [
        {"name_as_written": "warfarin", "role_as_stated": "explicitly_not_suspected", "quote": "q"}]}})
    assert out["target_drug"] is None
