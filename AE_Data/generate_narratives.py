#!/usr/bin/env python3
"""
Generate realistic adverse-event intake messages from labelled cases.

Step 3 of the PV case intake build. The answer key (cases_labeled.json) stays
real; only the wording is generated. The generator sees FACTS ONLY -- never
seriousness, expectedness, route, due date, or anything from the drug label --
so a narrative cannot leak the answer the system is graded on.

    python generate_narratives.py              # qualify cases, print the dev/test split
    python generate_narratives.py --resplit    # rebuild split.json (otherwise it is reused)
    python generate_narratives.py --pilot      # regenerate the pilot cases, print them
    python generate_narratives.py --all        # every qualifying case (not wired up yet)

Inputs, under data/:
    cases_labeled.json         from derive_expectedness.py --finalize

Outputs:
    split.json                 dev/test assignment. Reused on every run unless
                               --resplit, so the test set never moves under
                               prompt iteration.
    narratives_pilot_v2.jsonl  (--pilot)
    narratives.jsonl           (--all)

After generation every narrative gets deterministic checks AND a fidelity
check: the same model lists clinical content in the narrative that is not in
the facts. That is generation QA, not ground truth -- nothing it says changes
the answer key.

Every model call is traced to LangSmith (LANGSMITH_* in .env).
"""

import hashlib
import json
import os
import random
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from itertools import product
from pathlib import Path

import anthropic
from dotenv import load_dotenv
from langsmith import traceable

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

# Tracing is meant to be on for every model call. Without a key every upload
# 401s, so say so loudly once instead of failing quietly on each call.
if os.environ.get("LANGSMITH_TRACING", "").lower() == "true" and not os.environ.get("LANGSMITH_API_KEY"):
    print("WARNING: LANGSMITH_TRACING=true but LANGSMITH_API_KEY is empty in .env -- "
          "this run is NOT traced. Add the key to trace generator calls.\n")
    os.environ["LANGSMITH_TRACING"] = "false"

DATA = Path(__file__).resolve().parent / "data"
LABELED = DATA / "cases_labeled.json"
SPLIT = DATA / "split.json"
PILOT_V1 = DATA / "narratives_pilot.jsonl"   # source of the pilot case list
PILOT_OUT = DATA / "narratives_pilot_v2.jsonl"
FULL_OUT = DATA / "narratives.jsonl"

# ---------------------------------------------------------------- config

MODEL = "claude-sonnet-5-5"
EFFORT = "high"  # the model's default, pinned so a default change can't move results
PROMPT_VERSION = "v2"

SEED = 20261016
DEV_SIZE = 20
MAX_SUSPECTS = 3  # 1-4 was checked: it adds only 4 expedited cases (threshold was 8)
WORD_RANGE = (80, 200)

# Cases kept out of the narrative pool, with the reason.
EXCLUDED_CASES = {
    ("20296669", "sertraline"): "reaction term 'Labelled drug-drug interaction "
                                "medication error' carries label knowledge into the facts",
}

# Values openFDA uses to mean "not known". Never shown to the generator.
UNKNOWN_VALUES = {"product used for unknown indication", "unk", "unknown", ""}

CONSUMER_FORMATS = ["call-centre voicemail transcript", "email from patient or family"]
HCP_FORMATS = ["professional email from HCP", "partner safety report"]
REF_PREFIX = {
    "call-centre voicemail transcript": "CC-VM",
    "email from patient or family": "INBOX",
    "professional email from HCP": "HCP-EM",
    "partner safety report": "PSR",
}

# FAERS reporter qualification -> who the generator writes as. "other health
# professional" is never a pharmacist or physician: those have their own codes.
REPORTER_ROLES = {
    "physician": ["doctor"],
    "pharmacist": ["pharmacist"],
    "other health professional": ["nurse", "nurse practitioner", "physician assistant"],
    "consumer or other non-health professional": ["the patient", "a family member of the patient"],
}
HCP_REPORTERS = {"physician", "pharmacist", "other health professional"}

# What each seriousness criterion LOOKS like as a fact.
WHAT_HAPPENED = {
    "death": "the patient died",
    "life_threatening": "the patient's life was in danger at the time",
    "hospitalization": "the patient was admitted to hospital",
    "disabling": "the patient was left with a lasting disability or incapacity",
    "congenital_anomaly": "a baby was born with a birth defect",
    # A reporter judgment, not an event -- so it is passed on as one. Without
    # it, 16 serious cases would read as non-serious and be ungradeable.
    "other_medically_important": "the reporter assessed this event as medically significant",
}

# Fictional names for signatures; each case gets a unique combination.
FIRST_NAMES = [
    "Amara", "Ben", "Carmen", "Dmitri", "Elena", "Farid", "Grace", "Hiroshi", "Ines",
    "Jonah", "Kavya", "Liam", "Mei", "Nikolai", "Olusegun", "Priya", "Quentin", "Rosa",
    "Samir", "Tamsin", "Uma", "Viktor", "Wen", "Ximena", "Yusuf", "Zofia", "Aidan",
    "Beatriz", "Callum", "Daniela", "Emeka", "Fiona", "Gustavo", "Hannah", "Ivan",
]
LAST_NAMES = [
    "Achebe", "Bergstrom", "Castillo", "Dubois", "Eriksen", "Fontaine", "Gallagher",
    "Haddad", "Iwasaki", "Jovanovic", "Kowalski", "Lindqvist", "Mbeki", "Nakamura",
    "Okafor", "Petrov", "Quinlan", "Rossi", "Sato", "Thornton", "Ubaldi", "Varga",
    "Whitcombe", "Xu", "Yilmaz", "Zielinski", "Abbott", "Brennan", "Carvalho", "Desai",
]
# Fictional partner companies for forwarded safety reports.
PARTNER_ORGS = [
    "Halvern Therapeutics", "Ostrava Pharma", "Kestrel Health Partners", "Maribel Labs",
    "Northgate Medicines", "Tarnow Biologics", "Corvane Pharmaceuticals", "Lumen Ridge Health",
    "Brightwater Generics", "Sablewood Pharma", "Ferncliff Medical", "Arkhaven Life Sciences",
    "Pinecrest Distribution", "Velmora Pharma", "Quarry Hill Health", "Solenne Laboratories",
    "Dunmore Pharma Services", "Altavia Health", "Redmarsh Therapeutics", "Ivory Coast Medica",
    "Glenhallow Pharma", "Marrowind Labs", "Ostlund Medicines", "Copperfield Health",
    "Tiderun Pharma", "Wexley Biopharma", "Calder Peak Health", "Orlinsky Pharma",
    "Bellweather Medical", "Stonebridge Generics",
]

# Checked after generation. Word-boundary, case-insensitive.
FORBIDDEN = [
    "serious", "seriousness", "expected", "unexpected", "expedited",
    "listed", "labelled", "labeled", "known side effect",
]

SYSTEM_PROMPT = """You write realistic adverse event intake messages, the kind a pharmaceutical drug safety team receives: call-centre voicemail transcripts, emails from patients or their families, emails from healthcare professionals, and safety reports forwarded by partner companies.

You are given case facts, a message format, the reporter's role, a sign-off, and a target length. Write ONE message in that format, conveying all the facts.

Who is writing:
- Write as the reporter role given. A partner safety report is written by the partner company's safety staff, passing on what the given reporter told them.
- Use the sign-off given. Do not invent other names for the reporter.

The patient:
- Always refer to a specific patient ("my mother", "a patient of mine", "a man in his sixties"), even when age and sex are unknown.

Reactions and what happened:
- Describe each reaction in the reporter's own words, not the medical term. A consumer says "black tarry stools", not "melaena". A healthcare professional uses clinical but varied wording, not a copy of the term.
- Include every reaction in the facts.
- Convey each item in "what_happened" through events ("they kept her overnight", "he passed away on Tuesday"), never through regulatory words.
- If the facts say the reporter assessed the event as medically significant, voice that naturally and in your own words ("I'd consider this a significant event", "the doctor said it was concerning"). Never use the word "serious".

Add nothing clinical:
- Do NOT add any symptom, sign, test, lab value, diagnosis, treatment, hospital or care detail, drug start, stop or dose change, or other drug that is not in the facts. Rewording a given reaction is fine; adding a new one is not.
- If a detail is not in the facts (dose, start date, indication, outcome), either leave it out or say it is not known.
- Irrelevant detail is welcome but must be non-clinical: pets, the weather, the caller's day, background noise, work.

Forbidden:
- Never use these words: serious, seriousness, expected, unexpected, expedited, listed, labelled, known side effect.
- Never say or hint whether the effect is known for the drug. "The pharmacist said this can happen" is forbidden; so is "I read this is a side effect".

Style:
- Be realistic: vague or relative dates ("about three weeks ago"), hedging.
- Use the drug name exactly as given in the facts.
- Aim for the target length.

Output only the message body: no subject line, no headers, no preamble or commentary."""

FIDELITY_PROMPT = """You are a QA reviewer for synthetic adverse event narratives. You get the facts a writer was given and the narrative they wrote. List every piece of CLINICAL content in the narrative that is not supported by the facts.

Flag: symptoms, signs, tests, lab values, diagnoses, treatments, hospital or care details (ICU, resuscitation, length of stay, discharge), drug starts, stops or dose changes, other drugs, and outcomes that are not in the facts.

Do NOT flag:
- rewording of a reaction that IS in the facts, in lay or clinical language, at the same level of severity;
- the reporter's identity, names, sign-off, contact details, or where they work;
- non-clinical background detail (pets, weather, the caller's day);
- vague or relative timing, hedging, or uncertainty;
- statements that something is unknown or was not provided;
- the reporter's opinion that the event is significant or concerning, if the facts say the reporter assessed it as medically significant;
- a forwarding partner company's own process (follow-up requests, data exchange agreements).

Quote each addition exactly as it appears in the narrative. Return an empty list if there are none."""

FIDELITY_SCHEMA = {
    "type": "object",
    "properties": {
        "additions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "quote": {"type": "string"},
                    "category": {
                        "type": "string",
                        "enum": [
                            "symptom_or_sign", "test_or_lab", "diagnosis", "treatment",
                            "care_detail", "drug_change", "other_drug", "outcome", "other",
                        ],
                    },
                    "why": {"type": "string"},
                },
                "required": ["quote", "category", "why"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["additions"],
    "additionalProperties": False,
}

# ------------------------------------------------------------- qualifying


def case_key(case):
    return (case["safety_report_id"], case["target_drug"])


def known(value):
    return value is not None and str(value).strip().lower() not in UNKNOWN_VALUES


def drug_identity(drug):
    """One name per distinct drug, so a target listed twice counts once."""
    if drug["generic_names"]:
        return drug["generic_names"][0].lower()
    return re.sub(r"\s*/.*$", "", (drug["reported_name"] or "")).strip().lower()


def suspect_count(case):
    return len({drug_identity(d) for d in case["drugs"] if d["role"] == "suspect"})


def qualifying_cases():
    cases = json.loads(LABELED.read_text())
    return [
        c
        for c in cases
        if c["reporting_route"] != "ambiguous"
        and 1 <= suspect_count(c) <= MAX_SUSPECTS
        and case_key(c) not in EXCLUDED_CASES
    ]


# ------------------------------------------------------------------ split


def make_split(cases):
    """Stratified by (route, drug), largest-remainder allocation to DEV_SIZE.
    Reused unless --resplit, so the test set is never silently re-drawn."""
    if SPLIT.exists() and "--resplit" not in sys.argv:
        split = json.loads(SPLIT.read_text())
        print(f"reusing {SPLIT.name} (seed {split['seed']}, dev {len(split['dev'])})")
        return {tuple(k): s for s in ("dev", "test") for k in split[s]}

    rng = random.Random(SEED)
    strata = defaultdict(list)
    for c in sorted(cases, key=case_key):
        strata[(c["reporting_route"], c["target_drug"])].append(c)

    total = len(cases)
    quota = {s: DEV_SIZE * len(members) / total for s, members in strata.items()}
    alloc = {s: int(q) for s, q in quota.items()}
    remainder_order = sorted(quota, key=lambda s: (alloc[s] - quota[s], s))
    for s in remainder_order[: DEV_SIZE - sum(alloc.values())]:
        alloc[s] += 1

    # Cases already read during prompt work are dev by definition: scoring
    # them as test would leak prompt iteration into the headline numbers.
    seen = seen_case_keys()

    assignment = {}
    for s in sorted(strata):
        members = strata[s][:]
        rng.shuffle(members)
        members.sort(key=lambda c: case_key(c) not in seen)  # stable: seen first
        n_dev = max(alloc[s], sum(case_key(c) in seen for c in members))
        for i, c in enumerate(members):
            assignment[case_key(c)] = "dev" if i < n_dev else "test"

    SPLIT.write_text(
        json.dumps(
            {
                "seed": SEED,
                "stratified_by": ["reporting_route", "target_drug"],
                "excluded": [list(k) for k in EXCLUDED_CASES],
                "forced_dev_already_seen": sorted([list(k) for k in seen]),
                "dev": sorted([list(k) for k, v in assignment.items() if v == "dev"]),
                "test": sorted([list(k) for k, v in assignment.items() if v == "test"]),
            },
            indent=2,
        )
    )
    print(f"wrote {SPLIT.name}")
    return assignment


def seen_case_keys():
    """Cases whose narratives have been read while writing the prompt."""
    if not PILOT_V1.exists():
        return set()
    return {(r["safety_report_id"], r["target_drug"]) for r in map(json.loads, PILOT_V1.open())}


# ------------------------------------------------------------------ facts


def case_rng(case, purpose):
    """Per-case, per-purpose RNG: the same case always gets the same drug
    name, format, role, length and timestamp, and changing one draw never
    shifts another."""
    seed = f"{SEED}:{case['safety_report_id']}:{case['target_drug']}:{purpose}"
    return random.Random(int(hashlib.sha256(seed.encode()).hexdigest(), 16))


def display_name(name, is_brand):
    return name.title() if is_brand else name.lower()


def target_entries(case):
    return [d for d in case["drugs"] if d["is_target_drug"] and d["role"] == "suspect"]


def target_name_options(case):
    """Every brand and generic name for the target drug, plus the bare name."""
    names = {case["target_drug"]}
    for d in target_entries(case):
        names.update(n.lower() for n in d["brand_names"] + d["generic_names"])
    return names


def drug_fact(drug, name):
    fact = {"name": name}
    if known(drug["indication"]):
        fact["taken_for"] = drug["indication"]
    if known(drug["dose_text"]):
        fact["dose"] = drug["dose_text"]
    if known(drug["start_date"]):
        fact["started"] = drug["start_date"]
    return fact


def build_facts(case):
    """The ONLY clinical content the generator sees. Facts, no judgments
    except the reporter's own medically-significant assessment."""
    target = target_entries(case)[0]
    choices = [(n, True) for n in target["brand_names"]] + [(n, False) for n in target["generic_names"]]
    name, is_brand = case_rng(case, "drug_name").choice(sorted(set(choices)))

    others, seen = [], {drug_identity(target)}
    for d in case["drugs"]:
        if d["role"] == "suspect" and drug_identity(d) not in seen:
            seen.add(drug_identity(d))
            others.append(drug_fact(d, re.sub(r"\s*/.*$", "", d["reported_name"]).strip().title()))

    patient = {}
    if known(case["patient"]["age"]) and case["patient"]["age_unit"]:
        patient["age"] = f"{case['patient']['age']} {case['patient']['age_unit']}s"
    if case["patient"]["sex"] in ("male", "female"):
        patient["sex"] = case["patient"]["sex"]

    reactions = []
    for r in case["reactions"]:
        reaction = {"event": r["term"]}
        if r["outcome"] != "unknown":
            reaction["outcome"] = r["outcome"]
        reactions.append(reaction)

    return {
        "patient": patient,
        "drug": drug_fact(target, display_name(name, is_brand)),
        "other_suspect_drugs": others,
        "reactions": reactions,
        "what_happened": [
            text for crit, text in WHAT_HAPPENED.items() if case["seriousness_criteria"][crit]
        ],
        "reporter_country": case["reporter"]["country"],
    }


def reporter_class(case):
    q = case["reporter"]["qualification"]
    # Unknown reporters (2 cases) are written as consumers: no HCP role to be faithful to.
    return q if q in REPORTER_ROLES else "consumer or other non-health professional"


def source_type(case):
    formats = HCP_FORMATS if reporter_class(case) in HCP_REPORTERS else CONSUMER_FORMATS
    return case_rng(case, "format").choice(formats)


def signature_index(all_cases):
    """A unique (first, last, partner org) per case, so no two narratives
    share a sign-off. Assigned over every qualifying case in sorted order."""
    combos = list(product(FIRST_NAMES, LAST_NAMES))
    random.Random(SEED).shuffle(combos)
    return {
        case_key(c): {
            "person": f"{combos[i][0]} {combos[i][1]}",
            "org": PARTNER_ORGS[i % len(PARTNER_ORGS)],
        }
        for i, c in enumerate(sorted(all_cases, key=case_key))
    }


def build_style(case, signatures):
    """Non-clinical writing instructions. Recorded alongside the facts."""
    source = source_type(case)
    role = case_rng(case, "role").choice(REPORTER_ROLES[reporter_class(case)])
    sig = signatures[case_key(case)]
    if source == "partner safety report":
        sign_off = f"{sig['person']}, Drug Safety Associate, {sig['org']}"
    elif role == "doctor":
        sign_off = f"Dr {sig['person']}"
    elif role in ("pharmacist", "nurse", "nurse practitioner", "physician assistant"):
        sign_off = f"{sig['person']}, {role}"
    else:
        sign_off = sig["person"]  # consumers; a voicemail may use just the first name
    return {
        "format": source,
        "reporter_role": role,
        "sign_off": sign_off,
        "target_words": case_rng(case, "length").randint(*WORD_RANGE),
    }


def header(case, source):
    """Metadata a real intake system stamps on arrival. The date IS the FAERS
    receive_date, so the 15-day clock in the answer key still lines up."""
    rng = case_rng(case, "header")
    d = case["receive_date"]
    received = datetime(int(d[:4]), int(d[4:6]), int(d[6:8]), tzinfo=timezone.utc) + timedelta(
        seconds=rng.randint(7 * 3600, 19 * 3600)
    )
    ref = f"{REF_PREFIX[source]}-{d[:4]}-{rng.randint(10000, 99999)}"
    return {"source": source, "received": received.isoformat(), "ref": ref}


# -------------------------------------------------------------- model calls

client = None


def call_model(system, user, output_format=None):
    global client
    # gzip only: the Brotli 1.0.9 that ships with Anaconda is too old for the
    # SDK's decoder and fails every response with a "Connection error".
    client = client or anthropic.Anthropic(default_headers={"Accept-Encoding": "gzip"})

    output_config = {"effort": EFFORT}
    if output_format:
        output_config["format"] = output_format
    response = client.beta.messages.create(
        model=MODEL,
        max_tokens=16000,
        output_config=output_config,
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    if response.stop_reason == "refusal":
        raise RuntimeError(f"refused: {response.stop_details}")
    if response.stop_reason == "max_tokens":
        raise RuntimeError("hit max_tokens")
    text = "".join(b.text for b in response.content if b.type == "text").strip()
    return text, response.model


@traceable(run_type="llm", name="generate_narrative")
def generate(facts, style):
    user = (
        f"Message format: {style['format']}\n"
        f"Reporter role: {style['reporter_role']}\n"
        f"Sign-off: {style['sign_off']}\n"
        f"Target length: about {style['target_words']} words\n\n"
        f"Case facts:\n{json.dumps(facts, indent=2)}\n\n"
        f"Write the message."
    )
    return call_model(SYSTEM_PROMPT, user)


@traceable(run_type="llm", name="fidelity_check")
def fidelity_check(facts, narrative):
    """Generation QA, not ground truth: clinical content the writer added."""
    user = f"Facts:\n{json.dumps(facts, indent=2)}\n\nNarrative:\n{narrative}"
    text, _ = call_model(
        FIDELITY_PROMPT, user, {"type": "json_schema", "schema": FIDELITY_SCHEMA}
    )
    return json.loads(text)["additions"]


# ------------------------------------------------------------------ checks


def deterministic_checks(record, case):
    """No model. Returns a list of problems."""
    text = record["narrative"]
    problems = []

    for word in FORBIDDEN:
        for m in re.finditer(r"\b" + re.escape(word) + r"\b", text, re.IGNORECASE):
            start = max(0, m.start() - 40)
            problems.append(f"forbidden word {word!r}: ...{text[start:m.end() + 40]}...")

    words = len(text.split())
    if not WORD_RANGE[0] <= words <= WORD_RANGE[1]:
        problems.append(f"word count {words} outside {WORD_RANGE}")

    lowered = text.lower()
    if not any(re.search(r"\b" + re.escape(n) + r"\b", lowered) for n in target_name_options(case)):
        problems.append("target drug name not found")

    if record["source_type"] in CONSUMER_FORMATS:
        for r in case["reactions"]:
            if (len(r["term"].split()) > 1 or len(r["term"]) > 8) and r["term"].lower() in lowered:
                problems.append(f"(info) consumer uses MedDRA term verbatim: {r['term']!r}")
    return problems


def make_record(case, split, signatures):
    facts = build_facts(case)
    style = build_style(case, signatures)
    trace = {
        "metadata": {
            "safety_report_id": case["safety_report_id"],
            "target_drug": case["target_drug"],
            "split": split,
            "prompt_version": PROMPT_VERSION,
            "model": MODEL,
        }
    }
    narrative, served_by = generate(facts, style, langsmith_extra=trace)
    additions = fidelity_check(facts, narrative, langsmith_extra=trace)
    return {
        "safety_report_id": case["safety_report_id"],
        "target_drug": case["target_drug"],
        "split": split,
        "source_type": style["format"],
        "header": header(case, style["format"]),
        "narrative": narrative,
        "generator_model": served_by,
        "prompt_version": PROMPT_VERSION,
        "facts_given": facts,
        "style_given": style,
        "fidelity_additions": additions,
    }


# ------------------------------------------------------------------ pilot


def print_record(i, record, case, problems):
    style = record["style_given"]
    print("=" * 100)
    print(f"[{i}] {case['safety_report_id']} / {case['target_drug']}   "
          f"route={case['reporting_route']}  serious={case['is_serious']}  "
          f"criteria={[k for k, v in case['seriousness_criteria'].items() if v]}")
    print(f"    answer key: {[(r['term'], r['expectedness']) for r in case['reaction_expectedness']]}")
    print(f"    reporter: {case['reporter']['qualification']} -> {style['reporter_role']}; "
          f"sign-off {style['sign_off']!r}; target {style['target_words']} words")
    print(f"    facts given: {json.dumps(record['facts_given'])}")
    print("-" * 100)
    h = record["header"]
    print(f"Source: {h['source']}\nReceived: {h['received']}\nRef: {h['ref']}\n")
    print(record["narrative"])
    print("-" * 100)
    print(f"    words={len(record['narrative'].split())} (target {style['target_words']})  "
          f"model={record['generator_model']}")
    print("    deterministic: " + ("PASS" if not problems else "\n      ".join([""] + problems)))
    adds = record["fidelity_additions"]
    print("    fidelity: " + ("PASS (no additions)" if not adds else f"FLAG ({len(adds)} additions)"))
    for a in adds:
        print(f"      - [{a['category']}] {a['quote']!r} -- {a['why']}")


def main():
    cases = qualifying_cases()
    all_cases = json.loads(LABELED.read_text())
    print(f"labelled cases: {len(all_cases)}; qualifying (not ambiguous, "
          f"1-{MAX_SUSPECTS} distinct suspect drugs, minus {len(EXCLUDED_CASES)} excluded): {len(cases)}")
    print("  by route:", dict(Counter(c["reporting_route"] for c in cases)))
    print("  by source format:", dict(Counter(source_type(c) for c in cases)))

    assignment = make_split(cases)
    print("  split by route:")
    for split in ("dev", "test"):
        group = [c for c in cases if assignment.get(case_key(c)) == split]
        routes = Counter(c["reporting_route"] for c in group)
        print(f"    {split:4} {len(group):3}  expedited {routes['expedited_15_day']:3}  "
              f"periodic {routes['periodic']:3}   drugs {dict(sorted(Counter(c['target_drug'] for c in group).items()))}")

    signatures = signature_index(cases)

    if "--pilot" in sys.argv:
        v1_keys = [(r["safety_report_id"], r["target_drug"])
                   for r in map(json.loads, PILOT_V1.open())]
        by_key = {case_key(c): c for c in cases}
        dropped = [k for k in v1_keys if k not in by_key]
        print(f"\npilot: {len(v1_keys)} v1 cases, {len(dropped)} no longer qualify: {dropped}")

        records = []
        for i, key in enumerate([k for k in v1_keys if k in by_key], 1):
            case = by_key[key]
            record = make_record(case, assignment.get(key, "unassigned"), signatures)
            records.append(record)
            print_record(i, record, case, deterministic_checks(record, case))
        with PILOT_OUT.open("w") as f:
            for r in records:
                f.write(json.dumps(r) + "\n")
        flagged = sum(bool(r["fidelity_additions"]) for r in records)
        print(f"\nWrote {len(records)} to {PILOT_OUT}; fidelity flagged {flagged}")

    elif "--all" in sys.argv:
        sys.exit("--all is deliberately not wired up until the pilot is reviewed")


if __name__ == "__main__":
    main()
