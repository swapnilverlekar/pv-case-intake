#!/usr/bin/env python3
"""
Pull FAERS adverse-event cases and SPL labels from openFDA.

Step 1 of the PV case intake build. This only downloads and decodes --
it does not build narratives or derive expectedness. Those come next.

Setup:
    pip install -r requirements.txt
    OPENFDA_API_KEY in .env                  # free from open.fda.gov/apis/authentication/
    python pull_faers.py                     # fetch everything not already cached
    python pull_faers.py --from-raw          # no event fetch; rebuild cases from data/raw
    python pull_faers.py --refresh-labels    # re-fetch labels even if cached

Labels are cached and only fetched when missing: the same label version must be
used at eval time and run time, so a re-run must never silently swap it.

Outputs, under data/ next to this script:
    raw/events_<drug>.jsonl    one raw openFDA record per line (keep this -- it is your source of truth)
    raw/label_<drug>.json      that drug's SPL label, with the sections you need for expectedness
    cases_flat.json            one decoded record per case, ready for the next step
    summary.txt                strata counts, so you can see what you actually pulled
"""

import json
import os
import sys
import time
from collections import Counter
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

# ---------------------------------------------------------------- config

# Six drugs. Each one means a label you will have to read, so do not add more
# without deciding you will read that label too.
DRUGS = [
    "lisinopril",
    "metformin",
    "warfarin",
    "sertraline",
    "atorvastatin",
    "levothyroxine",
]

DATE_FROM = "20220101"
DATE_TO = "20241231"

# Over-pull. You will discard a lot of records to missing fields.
TARGET_PER_DRUG = 120

API_KEY = os.environ.get("OPENFDA_API_KEY", "").strip()
EVENT_URL = "https://api.fda.gov/drug/event.json"
LABEL_URL = "https://api.fda.gov/drug/label.json"
PAGE = 100  # reliable page size; larger pages time out more often

# With a key: 240 requests/min. Without: 40/min and 1000/day.
SLEEP = 0.3 if API_KEY else 1.6

OUT = Path(__file__).resolve().parent / "data"
RAW = OUT / "raw"

# Which label is the expectedness reference for each drug. A loose search on
# generic name returns combination products (lisinopril + HCTZ, sitagliptin +
# metformin), whose adverse reactions are not our drug's. So we pin the
# originator brand where openFDA has it, and an exact single-ingredient
# generic where it does not (no Glucophage label is published).
LABEL_SEARCH = {
    "lisinopril": 'openfda.brand_name:"Zestril"',
    "metformin": 'openfda.generic_name.exact:"METFORMIN HYDROCHLORIDE"',
    "warfarin": 'openfda.brand_name:"Jantoven"',  # Coumadin is discontinued
    "sertraline": 'openfda.brand_name:"Zoloft"',
    "atorvastatin": 'openfda.brand_name:"Lipitor"',
    "levothyroxine": 'openfda.brand_name:"Synthroid"',
}

# ------------------------------------------------------- decoding tables
# openFDA returns codes, not words. Getting one of these backwards silently
# corrupts your ground truth, so they are kept in one place on purpose.

SEX = {"1": "male", "2": "female"}

# Counter-intuitive and the single most common bug: 1 is serious, 2 is NOT.
SERIOUS = {"1": "serious", "2": "non-serious"}

DRUG_ROLE = {"1": "suspect", "2": "concomitant", "3": "interacting"}

REACTION_OUTCOME = {
    "1": "recovered/resolved",
    "2": "recovering/resolving",
    "3": "not recovered/not resolved",
    "4": "recovered with sequelae",
    "5": "fatal",
    "6": "unknown",
}

REPORTER = {
    "1": "physician",
    "2": "pharmacist",
    "3": "other health professional",
    "4": "lawyer",
    "5": "consumer or other non-health professional",
}

# Age is a number PLUS a unit. A "6" with unit 802 is six months, not six years.
AGE_UNIT = {
    "800": "decade",
    "801": "year",
    "802": "month",
    "803": "week",
    "804": "day",
    "805": "hour",
}

# Note the spelling of 'congenitalanomali' -- that is openFDA's field name, not a typo here.
SERIOUSNESS_FLAGS = [
    ("seriousnessdeath", "death"),
    ("seriousnesslifethreatening", "life_threatening"),
    ("seriousnesshospitalization", "hospitalization"),
    ("seriousnessdisabling", "disabling"),
    ("seriousnesscongenitalanomali", "congenital_anomaly"),
    ("seriousnessother", "other_medically_important"),
]

LABEL_SECTIONS = [
    "adverse_reactions",
    "warnings",
    "warnings_and_cautions",
    "boxed_warning",
    "precautions",
    "contraindications",
]


# ------------------------------------------------------------- fetching


def get(url, params):
    """One request, with retry on rate limit. Returns None when nothing matched."""
    if API_KEY:
        params = {**params, "api_key": API_KEY}

    for attempt in range(4):
        r = requests.get(url, params=params, timeout=60)

        if r.status_code == 200:
            return r.json()

        # openFDA answers 404 when a search matches nothing. Not an error.
        if r.status_code == 404:
            return None

        if r.status_code == 429:
            wait = 20 * (attempt + 1)
            print(f"    rate limited, waiting {wait}s", flush=True)
            time.sleep(wait)
            continue

        print(f"    HTTP {r.status_code}: {r.text[:200]}", flush=True)
        time.sleep(5)

    return None


def fetch_events(drug):
    """Page through adverse-event reports naming this drug."""
    search = (
        f'patient.drug.openfda.generic_name:"{drug}"'
        f" AND receivedate:[{DATE_FROM} TO {DATE_TO}]"
    )
    records, skip = [], 0

    while len(records) < TARGET_PER_DRUG:
        payload = get(EVENT_URL, {"search": search, "limit": PAGE, "skip": skip})
        if not payload or not payload.get("results"):
            break

        batch = payload["results"]
        records.extend(batch)
        skip += len(batch)
        print(f"    {len(records)} records", flush=True)

        if len(batch) < PAGE:
            break  # ran out
        if skip >= 25000:
            break  # openFDA's skip ceiling; window by date if you ever hit this

        time.sleep(SLEEP)

    return records[:TARGET_PER_DRUG]


def fetch_label(drug):
    """The approved label. This is your expectedness source -- cache it and read it."""
    payload = get(LABEL_URL, {"search": LABEL_SEARCH[drug], "limit": 1})
    if not payload or not payload.get("results"):
        return None

    raw = payload["results"][0]
    openfda = raw.get("openfda", {})
    generics = openfda.get("generic_name", [])

    # Refuse a combination product rather than derive expectedness from it.
    if not all(is_target_generic(g, drug) for g in generics):
        print(f"    label is not single-ingredient {drug}: {generics}")
        return None

    label = {
        "drug": drug,
        "spl_id": raw.get("id"),
        "spl_set_id": raw.get("set_id"),
        "effective_time": raw.get("effective_time"),  # pin this; labels change
        "brand_names": openfda.get("brand_name", []),
        "generic_names": generics,
        "manufacturer": openfda.get("manufacturer_name", []),
    }
    for section in LABEL_SECTIONS:
        value = raw.get(section)
        if value:
            label[section] = " ".join(value) if isinstance(value, list) else value
    return label


# ------------------------------------------------------------ flattening


def is_target_generic(generic, target_drug):
    """True for the drug itself or a salt form, false for a combination.

    openFDA usually names the salt: "ATORVASTATIN CALCIUM", "WARFARIN SODIUM".
    An exact match on "atorvastatin" drops those, which is how atorvastatin and
    levothyroxine once came out with zero usable cases. Combinations read
    "LISINOPRIL AND HYDROCHLOROTHIAZIDE" and must not count.
    """
    generic, target = generic.lower(), target_drug.lower()
    if " and " in generic or "," in generic.replace(", film coated", ""):
        return False
    return generic == target or generic.startswith(target + " ")


def flatten(rec, target_drug):
    """One raw openFDA record -> one decoded case. Returns None if unusable."""
    patient = rec.get("patient") or {}

    # --- seriousness ------------------------------------------------
    # Sub-flags are usually ABSENT rather than set to "2". Missing means false.
    criteria = {
        name: rec.get(field) == "1" for field, name in SERIOUSNESS_FLAGS
    }
    serious_code = rec.get("serious")

    # --- drugs ------------------------------------------------------
    drugs, target_is_suspect = [], False
    for d in patient.get("drug") or []:
        openfda = d.get("openfda") or {}
        generics = openfda.get("generic_name", [])
        role = DRUG_ROLE.get(d.get("drugcharacterization"), "unknown")
        is_target = any(is_target_generic(g, target_drug) for g in generics)

        if is_target and role == "suspect":
            target_is_suspect = True

        drugs.append(
            {
                "reported_name": d.get("medicinalproduct"),
                "generic_names": openfda.get("generic_name", []),
                "brand_names": openfda.get("brand_name", []),
                "role": role,
                "indication": d.get("drugindication"),
                "dose_text": d.get("drugdosagetext"),
                "start_date": d.get("drugstartdate"),
                "is_target_drug": is_target,
            }
        )

    # The search matches ANY drug on the case, including concomitant ones.
    # If our drug was not the suspect, the label lookup would be against the
    # wrong product, so the case is no use to us.
    if not target_is_suspect:
        return None

    # --- reactions --------------------------------------------------
    reactions = [
        {
            "term": r.get("reactionmeddrapt"),
            "outcome": REACTION_OUTCOME.get(r.get("reactionoutcome"), "unknown"),
        }
        for r in (patient.get("reaction") or [])
        if r.get("reactionmeddrapt")
    ]
    if not reactions:
        return None

    source = rec.get("primarysource") or {}

    return {
        "safety_report_id": rec.get("safetyreportid"),
        "safety_report_version": rec.get("safetyreportversion"),
        "target_drug": target_drug,
        # The clock start. Everything downstream depends on this.
        "receive_date": rec.get("receivedate"),
        "serious": SERIOUS.get(serious_code, "unknown"),
        "is_serious": serious_code == "1",
        "seriousness_criteria": criteria,
        "patient": {
            "age": patient.get("patientonsetage"),
            "age_unit": AGE_UNIT.get(patient.get("patientonsetageunit")),
            "sex": SEX.get(patient.get("patientsex"), "unknown"),
        },
        "drugs": drugs,
        "reactions": reactions,
        "reporter": {
            "qualification": REPORTER.get(source.get("qualification"), "unknown"),
            "country": source.get("reportercountry"),
        },
    }


# ----------------------------------------------------------------- main


def load_or_fetch_label(drug, refresh):
    path = RAW / f"label_{drug}.json"
    if path.exists() and not refresh:
        label = json.loads(path.read_text())
        print(f"    cached, effective {label.get('effective_time')}")
        return label

    label = fetch_label(drug)
    time.sleep(SLEEP)
    if label:
        path.write_text(json.dumps(label, indent=2))
        have = [s for s in LABEL_SECTIONS if s in label]
        print(f"    {label['brand_names']} effective {label.get('effective_time')}, "
              f"sections: {', '.join(have)}")
    else:
        print("    NO LABEL FOUND -- you cannot derive expectedness for this drug")
    return label


def load_or_fetch_events(drug, from_raw):
    path = RAW / f"events_{drug}.jsonl"
    if from_raw:
        if not path.exists():
            print(f"    no {path.name} to rebuild from")
            return []
        return [json.loads(line) for line in path.open()]

    raw_records = fetch_events(drug)
    with path.open("w") as f:
        for rec in raw_records:
            f.write(json.dumps(rec) + "\n")
    return raw_records


# ---------------------------------------------------------------- top-up
# The first pull is ~86% serious, because most of FAERS is. The eval needs
# enough non-serious cases to show the 15-day clock NOT starting, and enough
# cases per drug to say anything per drug. So we top up, through the same
# flatten() and decoding tables, and never re-add a case we already have.

NON_SERIOUS_PER_DRUG = 10  # x 6 drugs ~= 60 non-serious in total
MIN_CASES_PER_DRUG = 20

# Usable yield is ~20-25% of pulled records (mostly: our drug was only a
# concomitant). We page until we have enough usable cases, up to this cap.
TOPUP_MAX_RECORDS = 1500


def topup_drug(drug, extra_search, need, seen_ids):
    """Page through one search until `need` new usable cases are found.

    New raw records are appended to events_<drug>.jsonl so that --from-raw
    rebuilds exactly the same dataset. Returns the new flattened cases.
    """
    search = (
        f'patient.drug.openfda.generic_name:"{drug}"'
        f" AND receivedate:[{DATE_FROM} TO {DATE_TO}]"
        f"{extra_search}"
    )
    new_cases, new_raw, skip = [], [], 0

    while len(new_cases) < need and skip < TOPUP_MAX_RECORDS:
        payload = get(EVENT_URL, {"search": search, "limit": PAGE, "skip": skip})
        if not payload or not payload.get("results"):
            break
        batch = payload["results"]
        skip += len(batch)

        # Stop at the exact record that fills the quota, so the raw file holds
        # nothing usable beyond it and --from-raw rebuilds the same dataset.
        for rec in batch:
            if len(new_cases) >= need:
                break
            rid = rec.get("safetyreportid")
            if rid in seen_ids:
                continue
            seen_ids.add(rid)
            new_raw.append(rec)
            case = flatten(rec, drug)
            if case:
                new_cases.append(case)

        print(f"    scanned {skip}, {len(new_cases)}/{need} usable", flush=True)
        if len(batch) < PAGE:
            break  # ran out
        time.sleep(SLEEP)

    with (RAW / f"events_{drug}.jsonl").open("a") as f:
        for rec in new_raw:
            f.write(json.dumps(rec) + "\n")
    return new_cases


def topup():
    cases = json.loads((OUT / "cases_flat.json").read_text())

    # Seen = every raw record already on disk, usable or not, so a record we
    # rejected once is not re-scanned and re-appended.
    seen_ids = {c["safety_report_id"] for c in cases}
    for drug in DRUGS:
        path = RAW / f"events_{drug}.jsonl"
        if path.exists():
            seen_ids.update(json.loads(line)["safetyreportid"] for line in path.open())

    for drug in DRUGS:
        print(f"\n{drug}")
        mine = [c for c in cases if c["target_drug"] == drug]
        non_serious = sum(1 for c in mine if not c["is_serious"])

        need = NON_SERIOUS_PER_DRUG - non_serious
        if need > 0:
            print(f"  non-serious: have {non_serious}, need {need} more")
            added = topup_drug(drug, " AND serious:2", need, seen_ids)
            cases.extend(added)
            mine.extend(added)

        need = MIN_CASES_PER_DRUG - len(mine)
        if need > 0:
            print(f"  any seriousness: have {len(mine)}, need {need} more")
            cases.extend(topup_drug(drug, "", need, seen_ids))

    write_outputs(cases)


# ----------------------------------------------------------------- main


def write_outputs(all_cases):
    (OUT / "cases_flat.json").write_text(json.dumps(all_cases, indent=2))

    # --- summary: this is what tells you whether your strata are workable ---
    serious = sum(1 for c in all_cases if c["is_serious"])
    by_drug = Counter(c["target_drug"] for c in all_cases)
    serious_by_drug = Counter(c["target_drug"] for c in all_cases if c["is_serious"])
    by_reporter = Counter(c["reporter"]["qualification"] for c in all_cases)
    by_criterion = Counter(
        name
        for c in all_cases
        for name, hit in c["seriousness_criteria"].items()
        if hit
    )

    lines = [
        f"total usable cases: {len(all_cases)}",
        f"serious: {serious}  ({serious / len(all_cases):.0%})",
        f"non-serious: {len(all_cases) - serious}",
        "",
        "by drug (serious / non-serious):",
        *(
            f"  {d}: {n}  ({serious_by_drug[d]} / {n - serious_by_drug[d]})"
            for d, n in by_drug.most_common()
        ),
        "",
        "by reporter type:",
        *(f"  {r}: {n}" for r, n in by_reporter.most_common()),
        "",
        "seriousness criteria hit:",
        *(f"  {k}: {n}" for k, n in by_criterion.most_common()),
    ]
    report = "\n".join(lines)
    (OUT / "summary.txt").write_text(report)

    print("\n" + "=" * 60)
    print(report)
    print("=" * 60)
    print(f"\nWrote {OUT}/cases_flat.json and {OUT}/summary.txt")


def main():
    from_raw = "--from-raw" in sys.argv
    refresh_labels = "--refresh-labels" in sys.argv

    if not API_KEY and not from_raw:
        print("No OPENFDA_API_KEY set -- running at 40 requests/min.")
        print("Get a free key at open.fda.gov/apis/authentication/ and re-run.\n")

    if "--topup" in sys.argv:
        topup()
        return

    RAW.mkdir(parents=True, exist_ok=True)
    all_cases = []

    for drug in DRUGS:
        print(f"\n{drug}")

        print("  label")
        load_or_fetch_label(drug, refresh_labels)

        print("  events")
        raw_records = load_or_fetch_events(drug, from_raw)
        if not raw_records:
            print("    nothing returned")
            continue

        kept = [c for c in (flatten(r, drug) for r in raw_records) if c]
        all_cases.extend(kept)
        print(f"    {len(raw_records)} pulled, {len(kept)} usable")

    if not all_cases:
        print("\nNothing usable. Check your key and the drug names.")
        sys.exit(1)

    write_outputs(all_cases)
    print("Next: read the six labels, then derive expectedness.")


if __name__ == "__main__":
    main()
