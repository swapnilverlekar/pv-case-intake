"""validity gate (code, no model): the four elements of a valid ICSR.

Each element is decided here from quoted evidence; the model only supplied
the evidence. Names match the dataset's missing_element values.
"""

IDENTIFIABLE_RELATIONSHIPS = {
    "reporter_is_patient", "family_member", "reporters_patient_or_customer", "other_specific_person",
}
HCP_TYPES = {"physician", "pharmacist", "other_hcp"}


def validity(state):
    ex = state["extraction"]
    patient, reporter = ex["patient"], ex["reporter"]
    basis = {}

    # 1. Identifiable patient: any specific patient reference, or an age or sex.
    ref = patient["reference"]
    evidence = [q for q in (ref["quote"] if ref["relationship"] in IDENTIFIABLE_RELATIONSHIPS else None,
                            patient["age"]["quote"], patient["sex"]["quote"]) if q]
    basis["identifiable_patient"] = {"met": bool(evidence), "evidence": evidence}

    # 2. Identifiable reporter: a name, a contact route, or a stated
    #    healthcare qualification (ICH E2D counts qualification). An anonymous
    #    consumer with no name and no contact is not identifiable.
    evidence = [q for q in (reporter["name_quote"], reporter["contact_quote"],
                            reporter["type_quote"] if reporter["type"] in HCP_TYPES else None) if q]
    basis["identifiable_reporter"] = {"met": bool(evidence), "evidence": evidence}

    # 3. A suspect product that is one of our six drugs. Marketing-authorisation-holder
    #    convention: our product is suspect unless the reporter explicitly rules it out.
    suspects = [p for p in state["products"] if p["maps_to"] and p["role_as_stated"] != "explicitly_not_suspected"]
    basis["suspect_drug"] = {"met": bool(suspects), "evidence": [p["quote"] for p in suspects],
                             "target_drug": state["target_drug"]}

    # 4. At least one adverse event.
    basis["adverse_event"] = {"met": bool(ex["reactions"]), "evidence": [r["quote"] for r in ex["reactions"]]}

    missing = [name for name, key in (
        ("no_identifiable_patient", "identifiable_patient"),
        ("no_identifiable_reporter", "identifiable_reporter"),
        ("no_suspect_drug", "suspect_drug"),
        ("no_adverse_event", "adverse_event"),
    ) if not basis[key]["met"]]

    valid = not missing
    return {
        "valid": valid,
        "missing_elements": missing,
        "validity_basis": basis,
        "route": "pending_assessment" if valid else "follow_up_required",
    }
