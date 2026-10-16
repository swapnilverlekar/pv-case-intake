#!/usr/bin/env python3
"""
Constructed eval cases: invalid reports, duplicates, and near-misses.

Step 4 of the PV case intake build. FAERS only publishes valid, de-duplicated
cases, so the validity gate and the duplicate check have nothing to be tested
on. This builds that material from real cases, with the same generator and
writing rules as generate_narratives.py:

  invalid    a real case with ONE of the four required elements removed
             (identifiable patient, identifiable reporter, suspect drug,
             adverse event). Answer key: valid = false, missing_element,
             route = follow_up_required.
  duplicate  a second report of a case already in narratives.jsonl, from a
             different reporter and format, with small natural differences.
             Answer key: the original's, plus duplicate_of = original id.
  near_miss  a REAL labelled case (not otherwise narrated) with the same drug
             and a similar patient as a case in narratives.jsonl, but
             different events. Its answer key is its own real one, with
             duplicate_of = null. Tests that the system does not over-merge.

    python construct_cases.py          # build everything into constructed_cases.jsonl (resumable)

No answer key here is decided by a model: invalid keys are fixed by
construction, duplicate keys are copied from the original, near-miss keys
come from cases_labeled.json.
"""

import csv
import json
import random
import re
import sys
from collections import Counter
from datetime import datetime, timedelta
from itertools import product

import generate_narratives as g
from derive_expectedness import non_event_pattern

OUT = g.DATA / "constructed_cases.jsonl"
FLAT = g.DATA / "cases_flat.json"
SEED = g.SEED

N_INVALID = 15
INVALID_DEV = 5
N_DUPLICATES = 10
DUPLICATE_DEV = 5

MISSING_ELEMENTS = ["no_identifiable_patient", "no_identifiable_reporter", "no_suspect_drug", "no_adverse_event"]

INVALID_INSTRUCTIONS = {
    "no_identifiable_patient": (
        "The reporter cannot identify the patient. Refer to them only vaguely, as someone "
        "they heard about second-hand (\"someone at my church\", \"a friend of a friend\", "
        "\"a customer mentioned someone\"). Give no age, sex, initials or other detail that "
        "would identify the patient, and do not say 'my mother', 'my patient' or similar."
    ),
    "no_identifiable_reporter": (
        "The reporter is anonymous. They give no name, no profession, no organisation, no "
        "phone number, email or other way to contact them, and say they do not want to be "
        "contacted. Do not sign off with a name."
    ),
    "no_suspect_drug": (
        "The reporter cannot name the medicine. Refer to it only by the vague description in "
        "the facts (for example \"some blood pressure pill, not sure which\"). Never give a "
        "brand or generic drug name for it."
    ),
    "no_adverse_event": (
        "Nothing happened to the patient's health. Write a product question or complaint "
        "(for example about the tablets' appearance, packaging, storage, supply or price) "
        "with NO symptom, illness, reaction, injury or health effect of any kind. Say the "
        "patient is fine if it fits naturally."
    ),
}

# What a reporter who cannot name the drug might call it.
VAGUE_DRUG = {
    "lisinopril": "some blood pressure pill, not sure which one",
    "metformin": "a diabetes tablet, the reporter doesn't know the name",
    "warfarin": "a blood thinner of some kind",
    "sertraline": "an antidepressant, name not remembered",
    "atorvastatin": "a cholesterol pill, not sure what it's called",
    "levothyroxine": "a thyroid tablet, name unknown",
}

DUPLICATE_INSTRUCTION = (
    "This is a second, independent report of an event someone else may also have reported. "
    "Write it fresh, in this reporter's own words; do not mention any earlier report."
)

# Near-miss cases: (real labelled case B, similar case A already narrated).
# Found by: same target drug, same known sex, age within 5 years, no shared
# reaction terms, B not otherwise narrated. B's answer key is real.
NEAR_MISSES = [
    (("20290104", "warfarin"), ("20321508", "warfarin")),
    (("20296305", "warfarin"), ("20305057", "warfarin")),
    (("20277682", "sertraline"), ("20296572", "sertraline")),
    (("20291254", "levothyroxine"), ("20362145", "levothyroxine")),
    (("20292106", "sertraline"), ("20296572", "sertraline")),
]

# Non-clinical detail for constructed cases, separate from the main list so
# the main narratives' assignments never shift. Never repeated.
FILLER = [
    "the reporter is at a bus stop in the rain", "a toddler is singing in the background",
    "the reporter is on a coffee break at work", "the reporter has just come in from gardening",
    "the TV is on loudly next door", "the reporter is about to collect a parcel",
    "it is the reporter's first week back after a holiday", "the reporter is cooking dinner",
    "a choir rehearsal is about to start", "the reporter is waiting at the vet's",
    "the reporter's laptop is updating", "the reporter is walking to the station",
    "a thunderstorm is rolling in", "the reporter is in a hotel lobby",
    "the reporter has guests arriving soon", "the reporter is sorting the recycling",
    "the reporter's shift starts in ten minutes", "the reporter is at the hairdresser's",
    "a marching band is passing outside", "the reporter is queueing at the bank",
    "the reporter is assembling flat-pack furniture", "the reporter's train is about to leave",
    "it is the reporter's birthday", "the reporter is on the ferry",
    "the reporter is minding a neighbour's children", "the power just came back on",
    "the reporter is at the library", "the reporter's car alarm went off earlier",
    "the reporter is waiting for a taxi", "the reporter has a job interview tomorrow",
    "the reporter is decorating for a party", "the reporter just finished a run",
]

# --------------------------------------------------------------- helpers


def used_names():
    names = set()
    for r in map(json.loads, g.FULL_OUT.open()):
        style = r["style_given"]
        if style["reporter_name"]:
            names.add(style["reporter_name"])
        if style["format"] == "partner safety report":
            names.add(style["sign_off"].split(",")[0])
    return names


class Names:
    """Unique names from the same per-country, per-sex pools as the main set,
    excluding every name already used there."""

    def __init__(self):
        self.taken = used_names()
        self.pools = {}

    def take(self, country, sex):
        country = country if country in g.NAMES else "default"
        names = g.NAMES[country]
        if (country, sex) not in self.pools:
            surnames = names.get(f"surnames_{sex}", names["surnames"])
            combos = [
                f"{last} {first}" if names.get("surname_first") else f"{first} {last}"
                for first, last in product(names[sex], surnames)
            ]
            random.Random(f"{SEED}:constructed:{country}:{sex}").shuffle(combos)
            self.pools[(country, sex)] = [n for n in combos if n not in self.taken]
        if not self.pools[(country, sex)]:
            country = "default"
            return self.take(country, sex)
        name = self.pools[(country, sex)].pop()
        self.taken.add(name)
        return name


def make_style(case, fmt, role, name, filler, org=None):
    if fmt == "partner safety report":
        sign_off = f"{name}, Drug Safety Associate, {org}"
    elif name is None:
        sign_off = "(none: the reporter gives no name)"
    elif role == "doctor":
        sign_off = f"Dr {name}"
    elif role in ("pharmacist", "nurse", "nurse practitioner", "physician assistant"):
        sign_off = f"{name}, {role}"
    else:
        sign_off = name
    return {
        "format": fmt,
        "reporter_role": role,
        "reporter_name": name if fmt != "partner safety report" else None,
        "sign_off": sign_off,
        "non_clinical_detail": filler,
        "target_words": g.case_rng(case, "constructed_length").randint(*g.TARGET_RANGE),
    }


def checks(narrative, fmt, case, kind, missing):
    """Deterministic checks. A no_suspect_drug case must NOT name the drug."""
    record = {"narrative": narrative, "source_type": fmt}
    problems = [p for p in g.deterministic_checks(record, case) if not p.startswith("(info)")]
    if missing == "no_suspect_drug":
        problems = [p for p in problems if p != "target drug name not found"]
        lowered = narrative.lower()
        named = [n for n in g.target_name_options(case) if re.search(r"\b" + re.escape(n) + r"\b", lowered)]
        if named:
            problems.append(f"drug named in a no_suspect_drug case: {named}")
    return problems


def generate_checked(case, facts, style, instruction, split, kind, missing=None, example_id=None):
    """Same policy as the main set: flagged -> regenerate once -> needs_review."""
    trace = {"metadata": {
        "example_id": example_id, "constructed": kind, "split": split,
        "prompt_version": g.PROMPT_VERSION, "model": g.MODEL,
    }}
    attempts = []
    for _ in range(g.MAX_ATTEMPTS):
        narrative, served_by = g.generate(facts, style, instruction, langsmith_extra=trace)
        det = checks(narrative, style["format"], case, kind, missing)
        fid = g.fidelity_check(facts, narrative, instruction, langsmith_extra=trace)
        attempts.append({"narrative": narrative, "model": served_by, "det": det, "fid": fid})
        if not det and not fid:
            break
    final = attempts[-1]
    flagged = bool(final["det"] or final["fid"])
    return {
        "narrative": final["narrative"],
        "generator_model": final["model"],
        "deterministic_problems": final["det"],
        "fidelity_additions": final["fid"],
        "attempts": len(attempts),
        "status": "needs_review" if flagged else ("passed" if len(attempts) == 1 else "passed_after_regeneration"),
        "needs_review": flagged,
        "first_attempt_flags": (attempts[0]["det"] + [a["quote"] for a in attempts[0]["fid"]]) if len(attempts) > 1 else [],
    }


def answer_key_from(case, duplicate_of=None):
    """A real case's answer key, as the dataset stores it."""
    return {
        "valid": True,
        "missing_element": None,
        "is_serious": case["is_serious"],
        "seriousness_criteria": case["seriousness_criteria"],
        "reaction_expectedness": [
            {"term": r["term"], "expectedness": r["expectedness"]} for r in case["reaction_expectedness"]
        ],
        "case_expectedness": case["expectedness"],
        "reporting_route": case["reporting_route"],
        "due_date": case["due_date"],
        "duplicate_of": duplicate_of,
        "label_effective_time": case["label_effective_time"],
    }


INVALID_KEY = {
    "valid": False, "is_serious": None, "seriousness_criteria": None,
    "reaction_expectedness": None, "case_expectedness": None,
    "reporting_route": "follow_up_required", "due_date": None, "duplicate_of": None,
    "label_effective_time": None,
}

# ---------------------------------------------------------------- builders


def build_invalid(names, fillers):
    """N_INVALID real cases that are not otherwise narrated, one element removed each."""
    flat = json.loads(FLAT.read_text())
    narrated_ids = {r["safety_report_id"] for r in map(json.loads, g.FULL_OUT.open())}
    near_miss_ids = {b[0] for b, _ in NEAR_MISSES}
    with (g.DATA / "term_decisions.csv").open() as f:
        not_applicable = {(r["target_drug"], r["term"]) for r in csv.DictReader(f) if r["decision"] == "not_applicable"}
    sources = sorted(
        (c for c in flat
         if c["safety_report_id"] not in narrated_ids | near_miss_ids
         and g.case_key(c) not in g.seen_case_keys()  # read during prompt work
         and g.case_key(c) not in g.EXCLUDED_CASES
         # At least one real adverse event (not a product/usage term, not a
         # human not_applicable decision), so exactly one element is missing.
         and any(not non_event_pattern(r["term"]) and (c["target_drug"], r["term"]) not in not_applicable
                 for r in c["reactions"])
         and 1 <= g.suspect_count(c) <= g.MAX_SUSPECTS),
        key=g.case_key,
    )
    rng = random.Random(f"{SEED}:invalid")
    # Spread across drugs: round-robin over drugs, shuffled within each.
    by_drug = {}
    for c in sources:
        by_drug.setdefault(c["target_drug"], []).append(c)
    for d in by_drug.values():
        rng.shuffle(d)
    picked = []
    while len(picked) < N_INVALID:
        for d in sorted(by_drug):
            if by_drug[d] and len(picked) < N_INVALID:
                picked.append(by_drug[d].pop())

    jobs = []
    for i, case in enumerate(picked):
        missing = MISSING_ELEMENTS[i % len(MISSING_ELEMENTS)]
        split = "dev" if i < INVALID_DEV else "test"  # first pass covers every element in dev
        facts = g.build_facts(case)
        fmt, role = g.source_type(case), g.reporter_role(case)
        name = None if role == "the patient" else names.take(case["reporter"]["country"],
                                                             g.case_rng(case, "writer_sex").choice(["female", "male"]))

        if missing == "no_identifiable_patient":
            facts["patient"] = {}
            if role == "the patient":  # a reporter who is the patient is identifiable by definition
                role = "a family member of the patient"
                name = names.take(case["reporter"]["country"], "female")
        elif missing == "no_identifiable_reporter":
            fmt = g.case_rng(case, "anon_format").choice(g.CONSUMER_FORMATS)
            role, name = "anonymous member of the public", None
        elif missing == "no_suspect_drug":
            facts["drug"] = {"name": None, "description": VAGUE_DRUG[case["target_drug"]]}
            facts["other_suspect_drugs"] = []
        elif missing == "no_adverse_event":
            facts["reactions"] = []
            facts["what_happened"] = []

        style = make_style(case, fmt, role, name, fillers.pop(), org=g.PARTNER_ORGS[i % len(g.PARTNER_ORGS)])
        if missing == "no_identifiable_reporter":
            style["sign_off"] = "(none: anonymous, no contact details)"
        example_id = f"INV-{case['safety_report_id']}-{case['target_drug']}"
        jobs.append(dict(
            example_id=example_id, kind="invalid", missing=missing, split=split, case=case,
            facts=facts, style=style, instruction=INVALID_INSTRUCTIONS[missing],
            answer_key={**INVALID_KEY, "missing_element": missing},
            header=g.header(case, style["format"]),
            source_case=[case["safety_report_id"], case["target_drug"]],
        ))
    return jobs


def build_duplicates(names, fillers):
    """Second reports of N_DUPLICATES narrated cases, from the other side
    (consumer <-> HCP), with small natural differences."""
    labeled = {g.case_key(c): c for c in json.loads(g.LABELED.read_text())}
    narratives = {(r["safety_report_id"], r["target_drug"]): r for r in map(json.loads, g.FULL_OUT.open())}
    near_miss_a = {a for _, a in NEAR_MISSES}

    rng = random.Random(f"{SEED}:duplicates")
    picks = []
    for split, n in (("dev", DUPLICATE_DEV), ("test", N_DUPLICATES - DUPLICATE_DEV)):
        candidates = sorted(k for k, r in narratives.items() if r["split"] == split and k not in near_miss_a)
        rng.shuffle(candidates)
        # Spread across drugs and routes: take the first unseen (drug, route) each time.
        seen, chosen = set(), []
        for k in candidates:
            stratum = (k[1], labeled[k]["reporting_route"])
            if stratum not in seen:
                seen.add(stratum)
                chosen.append(k)
            if len(chosen) == n:
                break
        picks += [(split, k) for k in chosen]

    jobs = []
    for i, (split, key) in enumerate(picks):
        case, original = labeled[key], narratives[key]
        rng_c = g.case_rng(case, "duplicate")
        facts = json.loads(json.dumps(original["facts_given"]))  # deep copy

        # Small natural differences a second reporter would introduce.
        age = facts["patient"].get("age")
        if age and age.split()[0].isdigit() and int(age.split()[0]) > 2:
            n, unit = age.split(" ", 1)
            facts["patient"]["age"] = f"{int(n) + rng_c.choice([-1, 1])} {unit}"
        started = facts["drug"].get("started")
        if started and len(started) == 8:
            d = datetime.strptime(started, "%Y%m%d") + timedelta(days=rng_c.choice([-6, -3, 2, 4, 7]))
            facts["drug"]["started"] = d.strftime("%Y%m%d")

        # The other side reports it: consumer original -> HCP second report, and vice versa.
        was_hcp = original["source_type"] in g.HCP_FORMATS
        if was_hcp:
            fmt, role = rng_c.choice(g.CONSUMER_FORMATS), rng_c.choice(["the patient", "a family member of the patient"])
        else:
            fmt, role = rng_c.choice(g.HCP_FORMATS), rng_c.choice(["doctor", "pharmacist", "nurse"])
        name = None if role == "the patient" else names.take(facts["reporter_country"], rng_c.choice(["female", "male"]))
        style = make_style(case, fmt, role, name, fillers.pop(), org=g.PARTNER_ORGS[(i + 7) % len(g.PARTNER_ORGS)])

        # Arrives a few days after the original.
        received = datetime.fromisoformat(original["header"]["received"]) + timedelta(
            days=rng_c.randint(2, 12), hours=rng_c.randint(-5, 5))
        header = {
            "source": fmt,
            "received": received.isoformat(),
            "ref": f"{g.REF_PREFIX[fmt]}-{received.year}-{rng_c.randint(10000, 99999)}",
        }
        jobs.append(dict(
            example_id=f"DUP-{key[0]}-{key[1]}", kind="duplicate", missing=None, split=split, case=case,
            facts=facts, style=style, instruction=DUPLICATE_INSTRUCTION,
            answer_key=answer_key_from(case, duplicate_of=key[0]),
            header=header, source_case=list(key),
        ))
    return jobs


def build_near_misses(names, fillers):
    """Real labelled cases, similar to a narrated one but a different event."""
    labeled = {g.case_key(c): c for c in json.loads(g.LABELED.read_text())}
    narratives = {(r["safety_report_id"], r["target_drug"]): r for r in map(json.loads, g.FULL_OUT.open())}
    jobs = []
    for i, (b_key, a_key) in enumerate(NEAR_MISSES):
        case = labeled[b_key]
        facts = g.build_facts(case)
        fmt, role = g.source_type(case), g.reporter_role(case)
        name = None if role == "the patient" else names.take(case["reporter"]["country"],
                                                             g.case_rng(case, "writer_sex").choice(["female", "male"]))
        style = make_style(case, fmt, role, name, fillers.pop(), org=g.PARTNER_ORGS[(i + 13) % len(g.PARTNER_ORGS)])
        jobs.append(dict(
            example_id=f"{b_key[0]}-{b_key[1]}", kind="near_miss", missing=None,
            split=narratives[a_key]["split"], case=case, facts=facts, style=style, instruction="",
            answer_key=answer_key_from(case, duplicate_of=None),
            header=g.header(case, fmt), source_case=list(b_key), near_miss_of=list(a_key),
        ))
    return jobs


# ------------------------------------------------------------------ main


def main():
    names = Names()
    fillers = FILLER[:]
    random.Random(f"{SEED}:constructed_filler").shuffle(fillers)
    if len(fillers) < N_INVALID + N_DUPLICATES + len(NEAR_MISSES):
        sys.exit("not enough constructed filler options")

    jobs = build_invalid(names, fillers) + build_duplicates(names, fillers) + build_near_misses(names, fillers)
    print(f"constructed jobs: {dict(Counter(j['kind'] for j in jobs))}")
    print(f"  by split: {dict(Counter((j['kind'], j['split']) for j in jobs))}")
    print(f"  missing elements: {dict(Counter(j['missing'] for j in jobs if j['missing']))}")

    done = {}
    if OUT.exists():
        done = {r["example_id"]: r for r in map(json.loads, OUT.open()) if r["prompt_version"] == g.PROMPT_VERSION}
    todo = [j for j in jobs if j["example_id"] not in done]
    print(f"{len(done)} already built; generating {len(todo)}")

    from concurrent.futures import ThreadPoolExecutor, as_completed

    def run(job):
        result = generate_checked(job["case"], job["facts"], job["style"], job["instruction"],
                                  job["split"], job["kind"], job["missing"], job["example_id"])
        return {
            "example_id": job["example_id"],
            "constructed": job["kind"],
            "split": job["split"],
            "safety_report_id": job["case"]["safety_report_id"],
            "target_drug": job["case"]["target_drug"],
            "source_case": job["source_case"],
            "near_miss_of": job.get("near_miss_of"),
            "source_type": job["style"]["format"],
            "header": job["header"],
            "prompt_version": g.PROMPT_VERSION,
            "facts_given": job["facts"],
            "style_given": job["style"],
            "extra_instruction": job["instruction"],
            "answer_key": job["answer_key"],
            "manual_edit": False,
            "reviewed_by": "automated_checks",
            **result,
        }

    with ThreadPoolExecutor(max_workers=g.WORKERS) as pool:
        futures = {pool.submit(run, j): j for j in todo}
        for n, future in enumerate(as_completed(futures), 1):
            job = futures[future]
            try:
                record = future.result()
            except Exception as e:
                print(f"  [{n}/{len(todo)}] {job['example_id']} FAILED: {e}")
                continue
            done[record["example_id"]] = record
            print(f"  [{n}/{len(todo)}] {job['example_id']} {record['status']}", flush=True)

    records = [done[j["example_id"]] for j in jobs if j["example_id"] in done]
    with OUT.open("w") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    status = Counter(r["status"] for r in records)
    print(f"\nbuilt {len(records)} of {len(jobs)}: {dict(status)}")
    for r in records:
        if r["needs_review"]:
            print(f"  needs_review {r['example_id']}: "
                  + "; ".join(r["deterministic_problems"] + [f"[{a['category']}] {a['quote']}" for a in r["fidelity_additions"]]))


if __name__ == "__main__":
    main()
