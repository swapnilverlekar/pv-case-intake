"""product normalization (code): map each extracted product to one of our six drugs.

Matches the generic and brand names in the cached labels, plus BRAND_ALIASES,
as whole words, case-insensitively. A generic matches inside its salt form
("atorvastatin" in "atorvastatin calcium"). Longest name wins.
"""

import re

from pv_agent.labels import name_index


def match(name_as_written):
    text = name_as_written.lower()
    for name, drug, source in name_index():
        if re.search(r"\b" + re.escape(name) + r"\b", text):
            return drug, name, source
    return None, None, None


def normalize(state):
    products = []
    for p in state["extraction"]["products"]:
        drug, matched, source = match(p["name_as_written"])
        products.append({**p, "maps_to": drug, "matched_name": matched, "match_source": source})

    suspected = [p for p in products if p["maps_to"] and p["role_as_stated"] != "explicitly_not_suspected"]
    target = suspected[0]["maps_to"] if suspected else None
    return {"products": products, "target_drug": target}
