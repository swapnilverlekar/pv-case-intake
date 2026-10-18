#!/usr/bin/env python3
"""
Build the case store the duplicate check searches: the safety database as
the agent sees it.

One record per case in cases_flat.json with ONLY identifying facts -- no
seriousness, no expectedness, no route. Nothing in it is answer key.

    python build_case_store.py      # -> data/case_store.json
"""

import json
from pathlib import Path

DATA = Path(__file__).resolve().parent / "data"


def main():
    cases = json.loads((DATA / "cases_flat.json").read_text())
    store = [
        {
            "case_id": c["safety_report_id"],
            "receive_date": f"{c['receive_date'][:4]}-{c['receive_date'][4:6]}-{c['receive_date'][6:]}",
            "patient_age": c["patient"]["age"],
            "patient_age_unit": c["patient"]["age_unit"],
            "patient_sex": c["patient"]["sex"],
            "target_drug": c["target_drug"],
            "reaction_terms": [r["term"] for r in c["reactions"]],
            "reporter_qualification": c["reporter"]["qualification"],
        }
        for c in cases
    ]
    store.sort(key=lambda r: (r["receive_date"], r["case_id"], r["target_drug"]))
    (DATA / "case_store.json").write_text(json.dumps(store, indent=2))
    print(f"wrote {len(store)} records to case_store.json "
          f"({store[0]['receive_date']} .. {store[-1]['receive_date']})")


if __name__ == "__main__":
    main()
