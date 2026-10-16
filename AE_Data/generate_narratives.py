#!/usr/bin/env python3
"""
Generate realistic adverse-event intake messages from labelled cases.

Step 3 of the PV case intake build. The answer key (cases_labeled.json) stays
real; only the wording is generated. The generator sees FACTS ONLY -- never
seriousness, expectedness, route, due date, or anything from the drug label --
so a narrative cannot leak the answer the system is graded on.

    python generate_narratives.py              # qualify cases, print the dev/test split
    python generate_narratives.py --resplit    # rebuild split.json (otherwise it is reused)
    python generate_narratives.py --all        # every qualifying case -> narratives.jsonl (resumable)
    python generate_narratives.py --spotcheck  # rebuild narrative_spotcheck.md from narratives.jsonl

Inputs, under data/:
    cases_labeled.json         from derive_expectedness.py --finalize

Outputs:
    split.json                 dev/test assignment. Reused on every run unless
                               --resplit, so the test set never moves under
                               prompt iteration.
    narrative_spotcheck.md     every needs_review narrative + a random passed sample
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
FULL_OUT = DATA / "narratives.jsonl"
SPOTCHECK = DATA / "narrative_spotcheck.md"

# ---------------------------------------------------------------- config

MODEL = "claude-sonnet-5-5"
EFFORT = "high"  # the model's default, pinned so a default change can't move results
PROMPT_VERSION = "v3"

SEED = 20261016
DEV_SIZE = 20
MAX_SUSPECTS = 3  # 1-4 was checked: it adds only 4 expedited cases (threshold was 8)
WORD_RANGE = (80, 200)          # hard limits, checked after generation
TARGET_RANGE = (80, 170)        # per-case target; below the ceiling because the model runs long
MAX_ATTEMPTS = 2                # a flagged narrative is regenerated once, then needs_review
WORKERS = 6

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

# Reporter names, per country and sex. First names x surnames gives every
# case a unique full name. Unlisted countries use "default". For CN the
# surname comes first. Patients are never named; a reporter who IS the
# patient gives no name at all.
NAMES = {
    "US": {"female": ["Jennifer", "Maria", "Ashley", "Linda", "Keisha", "Rachel", "Megan",
                      "Patricia", "Tanya", "Lauren", "Denise", "Carla"],
           "male": ["Michael", "David", "James", "Carlos", "Marcus", "Kevin", "Brian",
                    "Anthony", "Tyler", "Darnell", "Steven", "Raymond"],
           "surnames": ["Johnson", "Ramirez", "Miller", "Nguyen", "Patel", "Brooks",
                        "Sullivan", "Harris", "Coleman", "Reyes", "Bennett", "Foster"]},
    "GB": {"female": ["Sarah", "Emma", "Claire", "Joanne", "Priya"],
           "male": ["James", "Gareth", "Tom", "Callum", "Neil"],
           "surnames": ["Taylor", "Evans", "Walsh", "Hughes", "Khan"]},
    "AU": {"female": ["Chloe", "Kylie", "Mia"], "male": ["Liam", "Brendan", "Josh"],
           "surnames": ["Murphy", "Kelly", "Nguyen"]},
    "FR": {"female": ["Camille", "Sophie", "Nathalie", "Claire"],
           "male": ["Julien", "Pierre", "Laurent", "Mathieu"],
           "surnames": ["Martin", "Bernard", "Lefèvre", "Moreau"]},
    "DE": {"female": ["Anna", "Katrin", "Sabine", "Julia"],
           "male": ["Thomas", "Stefan", "Jonas", "Markus"],
           "surnames": ["Müller", "Schneider", "Weber", "Fischer"]},
    "AT": {"female": ["Lena", "Theresa"], "male": ["Florian", "Lukas"],
           "surnames": ["Gruber", "Huber"]},
    "IT": {"female": ["Giulia", "Francesca", "Chiara"], "male": ["Marco", "Luca", "Alessandro"],
           "surnames": ["Rossi", "Bianchi", "Romano"]},
    "ES": {"female": ["Lucía", "Carmen"], "male": ["Javier", "Pablo"],
           "surnames": ["García", "Fernández"]},
    "SE": {"female": ["Ingrid", "Maja"], "male": ["Erik", "Lars"],
           "surnames": ["Andersson", "Lindberg"]},
    "NL": {"female": ["Sanne", "Femke"], "male": ["Daan", "Joost"],
           "surnames": ["de Vries", "Bakker"]},
    "CZ": {"female": ["Petra", "Lucie"], "male": ["Jakub", "Tomáš"],
           "surnames": ["Novák", "Dvořák"], "surnames_female": ["Nováková", "Dvořáková"]},
    "JP": {"female": ["Yuki", "Aiko", "Haruka"], "male": ["Kenji", "Takeshi", "Daisuke"],
           "surnames": ["Tanaka", "Suzuki", "Watanabe"]},
    "CN": {"female": ["Na", "Fang", "Jing"], "male": ["Wei", "Yang", "Lei"],
           "surnames": ["Li", "Wang", "Zhang"], "surname_first": True},
    "default": {"female": ["Nina", "Leila", "Sofia"], "male": ["Omar", "Daniel", "Adrian"],
                "surnames": ["Haddad", "Novak", "Costa"]},
}

# One non-clinical detail per case, never repeated. Woven in as the
# "irrelevant detail" real messages carry.
FILLER = [
    "it has been raining all week", "the caller is stuck in traffic on the way to work",
    "a work deadline is looming", "a grandchild's birthday party is this weekend",
    "the heating in the house broke yesterday", "the reporter has just come back from holiday",
    "a delivery driver rang the doorbell mid-message", "the car is in for a service",
    "it is the first warm day of spring", "the office is short-staffed this week",
    "the reporter is moving house next month", "a neighbour is doing loud renovation work",
    "the school run was chaotic this morning", "the reporter's phone battery is low",
    "the train was cancelled earlier", "a family wedding is coming up",
    "the reporter is calling on a lunch break", "it snowed overnight",
    "the clinic's computer system was down this morning", "the reporter just got a new puppy",
    "there is a power cut in the street", "the reporter is writing from a café",
    "the in-laws are visiting for the week", "the reporter missed the bus",
    "a quarterly audit is happening at work", "the garden fence blew down in the wind",
    "the reporter has been on hold with another company all morning",
    "the local football team won last night", "the reporter's teenager is revising for exams",
    "the pharmacy had a queue out of the door today", "the internet at home keeps dropping",
    "a colleague is retiring this Friday", "the reporter is about to start a night shift",
    "the washing machine flooded the kitchen", "the reporter is jet-lagged from a conference",
    "roadworks have blocked the usual route", "it is the reporter's day off",
    "a parcel went to the wrong address", "the reporter's cat knocked over a plant",
    "the hospital car park was full", "the reporter is typing on a borrowed laptop",
    "there was a fire drill at work this morning", "the reporter's flight was delayed",
    "the reporter is waiting for a plumber", "it is unusually foggy today",
    "the reporter just finished a long shift", "a new manager started this week",
    "the reporter is calling from a noisy supermarket", "the kids are off school with a holiday",
    "the reporter's email inbox crashed yesterday", "a storm knocked out the phone lines briefly",
    "the reporter is taking an evening class", "the reporter forgot their reading glasses",
    "a street market is setting up outside", "the reporter's sister is visiting from abroad",
    "the team is covering for a colleague on leave", "the reporter's bike got a flat tyre",
    "the building's lift is out of order", "the reporter is between two meetings",
    "there is a local festival this weekend", "the reporter is painting the spare room",
    "the reporter's dog needs walking soon", "the bins were not collected this week",
    "the reporter recently changed jobs", "it is very hot and the air conditioning is broken",
    "the reporter is calling from the car park", "a long queue at the post office earlier",
    "the reporter's daughter just passed her driving test", "the reporter is house-sitting for a friend",
    "the reporter is on a slow train with patchy signal", "the office kettle broke",
    "the reporter is preparing for a charity run", "the reporter's printer is jammed",
    "a big family dinner is planned tonight", "the reporter has a dentist appointment later",
    "the reporter is new to the area", "the reporter's neighbour's alarm keeps going off",
    "the reporter is sorting out a mobile phone contract", "the reporter is writing late at night",
    "the reporter's garden is flooded after heavy rain",
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

You are given case facts, a message format, the reporter's role, the reporter's name (or that they gave none), a sign-off, a non-clinical detail, and a target length. Write ONE message in that format, conveying all the facts.

Who is writing:
- Write as the reporter role given. A partner safety report is written by the partner company's safety staff, passing on what the given reporter told them.
- Use the sign-off given. If the reporter gave no name, they do not give one anywhere in the message.
- Never give the patient a name.

The patient:
- Always refer to a specific patient ("my mother", "a patient of mine", "a man in his sixties"), even when age and sex are unknown.

Reactions and what happened:
- Describe each reaction in the reporter's own words, not the medical term. A consumer says "black tarry stools", not "melaena". A healthcare professional uses clinical but varied wording, not a copy of the term.
- Include every reaction in the facts.
- Convey each item in "what_happened" through events ("they kept her overnight", "he passed away on Tuesday"), never through regulatory words.
- Medical significance: ONLY if "what_happened" says the reporter assessed the event as medically significant, include that assessment, in the reporter's own voice and your own words ("I'd consider this a significant event"). Never attribute it to anyone other than the reporter. If the fact is absent, say nothing about how significant or concerning the event is. Never use the word "serious".

Add nothing clinical:
- Do NOT add any symptom, sign, test, lab value, diagnosis, treatment, hospital or care detail, drug start, stop or dose change, medical history, or other drug that is not in the facts. Rewording or describing a given reaction is fine; adding a new one is not.
- If a detail is not in the facts (dose, start date, indication, outcome), either leave it out or say it is not known.
- Work in the non-clinical detail you are given, briefly and naturally. Add no other background detail.

Forbidden:
- Never use these words: serious, seriousness, expected, unexpected, expedited, listed, labelled, known side effect.
- Never say or hint whether the effect is known for the drug. "The pharmacist said this can happen" is forbidden; so is "I read this is a side effect".

Style:
- Be realistic: vague or relative dates ("about three weeks ago"), hedging.
- Use the drug name exactly as given in the facts.
- Aim for the target length. Never exceed 200 words.

Output only the message body: no subject line, no headers, no preamble or commentary."""

FIDELITY_PROMPT = """You are a QA reviewer for synthetic adverse event narratives. You get the facts a writer was given and the narrative they wrote. List every piece of CLINICAL content in the narrative that is not supported by the facts.

Flag: symptoms, signs, tests, lab values, diagnoses, treatments, hospital or care details (ICU, resuscitation, length of stay, discharge), drug starts, stops or dose changes, other drugs, and outcomes that are not in the facts.

Flag only NEW clinical content. Do NOT flag:
- rewording or describing a reaction that IS in the facts, in lay or clinical language, at the same level of severity (for example "red and blotchy" or "on her arms" for a rash);
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


def reporter_role(case):
    return case_rng(case, "role").choice(REPORTER_ROLES[reporter_class(case)])


def people_and_filler(all_cases):
    """Per case: the writer's name (unique across all cases, from the
    reporter's country and a sex consistent with who is writing), a partner
    org, and a non-clinical detail (unique across all cases)."""
    if len(all_cases) > len(FILLER):
        sys.exit(f"{len(all_cases)} cases but only {len(FILLER)} filler options")
    rng = random.Random(SEED)
    filler = FILLER[:]
    rng.shuffle(filler)

    pools = {}
    def next_name(country, sex):
        names = NAMES.get(country, NAMES["default"])
        if (country, sex) not in pools:
            surnames = names.get(f"surnames_{sex}", names["surnames"])
            combos = [
                f"{last} {first}" if names.get("surname_first") else f"{first} {last}"
                for first, last in product(names[sex], surnames)
            ]
            random.Random(f"{SEED}:{country}:{sex}").shuffle(combos)
            pools[(country, sex)] = combos
        if not pools[(country, sex)]:
            sys.exit(f"ran out of unique names for {country}/{sex}")
        return pools[(country, sex)].pop()

    out = {}
    for i, c in enumerate(sorted(all_cases, key=case_key)):
        role = reporter_role(c)
        country = c["reporter"]["country"]
        if role == "the patient":
            name = None  # the reporter is the patient, and patients are never named
        else:
            sex = case_rng(c, "writer_sex").choice(["female", "male"])
            name = next_name(country if country in NAMES else "default", sex)
        out[case_key(c)] = {
            "name": name,
            "org": PARTNER_ORGS[i % len(PARTNER_ORGS)],
            "filler": filler[i],
        }
    return out


def build_style(case, people):
    """Non-clinical writing instructions. Recorded alongside the facts."""
    source = source_type(case)
    role = reporter_role(case)
    who = people[case_key(case)]
    name = who["name"]
    if source == "partner safety report":
        sign_off = f"{name}, Drug Safety Associate, {who['org']}"
    elif name is None:
        sign_off = "(none: the reporter gives no name)"
    elif role == "doctor":
        sign_off = f"Dr {name}"
    elif role in ("pharmacist", "nurse", "nurse practitioner", "physician assistant"):
        sign_off = f"{name}, {role}"
    else:
        sign_off = name
    return {
        "format": source,
        "reporter_role": role,
        "reporter_name": name if source != "partner safety report" else None,
        "sign_off": sign_off,
        "non_clinical_detail": who["filler"],
        "target_words": case_rng(case, "length").randint(*TARGET_RANGE),
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
def generate(facts, style, extra_instruction=""):
    """extra_instruction is empty for every real case; constructed cases
    (construct_cases.py) use it to remove a validity element."""
    user = (
        f"Message format: {style['format']}\n"
        f"Reporter role: {style['reporter_role']}\n"
        f"Reporter name: {style['reporter_name'] or 'none given'}\n"
        f"Sign-off: {style['sign_off']}\n"
        f"Non-clinical detail to work in: {style['non_clinical_detail']}\n"
        f"Target length: about {style['target_words']} words (never more than 200)\n\n"
        f"Case facts:\n{json.dumps(facts, indent=2)}\n\n"
        + (f"Special instruction (overrides the rules above where they conflict):\n{extra_instruction}\n\n"
           if extra_instruction else "")
        + "Write the message."
    )
    return call_model(SYSTEM_PROMPT, user)


@traceable(run_type="llm", name="fidelity_check")
def fidelity_check(facts, narrative, extra_instruction=""):
    """Generation QA, not ground truth: clinical content the writer added.
    A constructed case's special instruction is shown too: content the
    writer was told to produce is not an addition."""
    user = f"Facts:\n{json.dumps(facts, indent=2)}\n\n"
    if extra_instruction:
        user += f"The writer was also given this special instruction:\n{extra_instruction}\n\n"
    user += f"Narrative:\n{narrative}"
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


def attempt(case, split, facts, style):
    """One generation plus all checks."""
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
    record = {"narrative": narrative, "source_type": style["format"], "generator_model": served_by}
    problems = deterministic_checks(record, case)
    record["deterministic_problems"] = [p for p in problems if not p.startswith("(info)")]
    record["deterministic_info"] = [p for p in problems if p.startswith("(info)")]
    record["fidelity_additions"] = fidelity_check(facts, narrative, langsmith_extra=trace)
    record["flagged"] = bool(record["deterministic_problems"] or record["fidelity_additions"])
    return record


def make_record(case, split, people):
    """Generate; if flagged (including over 200 words), regenerate once; if
    still flagged, keep the second one and mark it needs_review."""
    facts = build_facts(case)
    style = build_style(case, people)
    attempts = []
    for _ in range(MAX_ATTEMPTS):
        attempts.append(attempt(case, split, facts, style))
        if not attempts[-1]["flagged"]:
            break
    final = attempts[-1]
    if not final["flagged"]:
        status = "passed" if len(attempts) == 1 else "passed_after_regeneration"
    else:
        status = "needs_review"
    return {
        "safety_report_id": case["safety_report_id"],
        "target_drug": case["target_drug"],
        "split": split,
        "source_type": style["format"],
        "header": header(case, style["format"]),
        "narrative": final["narrative"],
        "generator_model": final["generator_model"],
        "prompt_version": PROMPT_VERSION,
        "facts_given": facts,
        "style_given": style,
        "status": status,
        "attempts": len(attempts),
        "deterministic_problems": final["deterministic_problems"],
        "deterministic_info": final["deterministic_info"],
        "fidelity_additions": final["fidelity_additions"],
        # What the first attempt was flagged for, when it was regenerated.
        "first_attempt_flags": (
            attempts[0]["deterministic_problems"] + [a["quote"] for a in attempts[0]["fidelity_additions"]]
            if len(attempts) > 1 else []
        ),
    }


# ------------------------------------------------------------------ batch


def run_all(cases, assignment, people):
    """Every qualifying case, in parallel, written as each finishes so an
    interrupted run resumes where it stopped. Rewritten sorted at the end."""
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from threading import Lock

    done = {}
    if FULL_OUT.exists():
        for r in map(json.loads, FULL_OUT.open()):
            if r["prompt_version"] == PROMPT_VERSION:
                done[(r["safety_report_id"], r["target_drug"])] = r
    todo = [c for c in cases if case_key(c) not in done]
    print(f"\n{len(done)} already generated with {PROMPT_VERSION}; generating {len(todo)}")

    lock = Lock()
    with FULL_OUT.open("w") as f:
        for r in done.values():
            f.write(json.dumps(r) + "\n")
        f.flush()
        with ThreadPoolExecutor(max_workers=WORKERS) as pool:
            futures = {pool.submit(make_record, c, assignment[case_key(c)], people): c for c in todo}
            for n, future in enumerate(as_completed(futures), 1):
                case = futures[future]
                try:
                    record = future.result()
                except Exception as e:  # keep going; the case is retried on the next run
                    print(f"  [{n}/{len(todo)}] {case_key(case)} FAILED: {e}")
                    continue
                with lock:
                    f.write(json.dumps(record) + "\n")
                    f.flush()
                    done[case_key(case)] = record
                print(f"  [{n}/{len(todo)}] {case_key(case)} {record['status']}", flush=True)

    records = sorted(done.values(), key=lambda r: (r["safety_report_id"], r["target_drug"]))
    with FULL_OUT.open("w") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")
    return records


def summarize(records, expected_total):
    status = Counter(r["status"] for r in records)
    print(f"\ngenerated: {len(records)} of {expected_total}")
    print(f"  passed first time:          {status['passed']}")
    print(f"  regenerated (any outcome):  {sum(r['attempts'] > 1 for r in records)}")
    print(f"    passed after regeneration: {status['passed_after_regeneration']}")
    print(f"  still needs_review:         {status['needs_review']}")
    print(f"  word counts: min {min(len(r['narrative'].split()) for r in records)}, "
          f"max {max(len(r['narrative'].split()) for r in records)}")
    names = [r["style_given"]["reporter_name"] for r in records if r["style_given"]["reporter_name"]]
    fillers = [r["style_given"]["non_clinical_detail"] for r in records]
    print(f"  unique reporter names: {len(set(names))} of {len(names)} named; "
          f"unique filler: {len(set(fillers))} of {len(fillers)}")


# -------------------------------------------------------------- spot check


def write_spotcheck(records):
    """Every needs_review narrative, plus 10 random passed ones (5 dev,
    5 test, both routes in each), each with facts and the answer key."""
    labeled = {case_key(c): c for c in json.loads(LABELED.read_text())}
    rng = random.Random(SEED)

    def pick(split, n_exp, n_per):
        passed = [r for r in records if r["split"] == split and r["status"] != "needs_review"]
        route = lambda r: labeled[(r["safety_report_id"], r["target_drug"])]["reporting_route"]
        exp = sorted([r for r in passed if route(r) == "expedited_15_day"], key=lambda r: r["safety_report_id"])
        per = sorted([r for r in passed if route(r) == "periodic"], key=lambda r: r["safety_report_id"])
        return rng.sample(exp, min(n_exp, len(exp))) + rng.sample(per, min(n_per, len(per)))

    review = [r for r in records if r["status"] == "needs_review"]
    sample = pick("dev", 3, 2) + pick("test", 2, 3)

    lines = [
        "# Narrative spot check",
        "",
        f"Prompt `{PROMPT_VERSION}`, model `{MODEL}`. {len(records)} narratives: "
        f"{sum(r['status'] == 'passed' for r in records)} passed first time, "
        f"{sum(r['status'] == 'passed_after_regeneration' for r in records)} passed after one regeneration, "
        f"{len(review)} need review.",
        "",
        "The fidelity check is generation QA (the same model listing clinical content not in the facts), not ground truth.",
        "",
    ]

    def block(r):
        case = labeled[(r["safety_report_id"], r["target_drug"])]
        h, style = r["header"], r["style_given"]
        out = [
            f"### {r['safety_report_id']} / {r['target_drug']} ({r['split']}, {r['status']})",
            "",
            f"**Answer key:** route `{case['reporting_route']}`"
            + (f", due `{case['due_date']}`" if case["due_date"] else "")
            + f"; serious `{case['is_serious']}`"
            + f" ({', '.join(k for k, v in case['seriousness_criteria'].items() if v) or 'no criteria'})",
            "",
            "| reaction | expectedness | decided by |",
            "|---|---|---|",
            *[f"| {x['term']} | {x['expectedness']} | {x['decided_by']} |" for x in case["reaction_expectedness"]],
            "",
            f"**Reporter:** {case['reporter']['qualification']} → {style['reporter_role']}, "
            f"{style['format']}, target {style['target_words']} words, "
            f"actual {len(r['narrative'].split())}",
            "",
            f"**Facts given:** `{json.dumps(r['facts_given'], ensure_ascii=False)}`",
            "",
            f"> Source: {h['source']}  ",
            f"> Received: {h['received']}  ",
            f"> Ref: {h['ref']}",
            ">",
            *[f"> {line}" if line else ">" for line in r["narrative"].splitlines()],
            "",
        ]
        if r["deterministic_problems"] or r["fidelity_additions"]:
            out.append("**Flags on the kept version:**")
            out += [f"- deterministic: {p}" for p in r["deterministic_problems"]]
            out += [f"- fidelity [{a['category']}]: \"{a['quote']}\" ({a['why']})" for a in r["fidelity_additions"]]
            out.append("")
        if r["first_attempt_flags"]:
            out.append("**First attempt was flagged for:** " + "; ".join(f"\"{q}\"" for q in r["first_attempt_flags"]))
            out.append("")
        return out

    lines += [f"## Needs review ({len(review)})", ""]
    for r in review:
        lines += block(r)
    if not review:
        lines += ["None.", ""]
    lines += [f"## Random passed sample ({len(sample)}: 5 dev, 5 test)", ""]
    for r in sample:
        lines += block(r)
    SPOTCHECK.write_text("\n".join(lines))
    print(f"wrote {SPOTCHECK.name}: {len(review)} needs_review + {len(sample)} sampled")


# ------------------------------------------------------------------- main


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
              f"periodic {routes['periodic']:3}")

    people = people_and_filler(cases)

    if "--all" in sys.argv:
        records = run_all(cases, assignment, people)
        summarize(records, len(cases))
        write_spotcheck(records)
    elif "--spotcheck" in sys.argv:
        records = [json.loads(l) for l in FULL_OUT.open()]
        summarize(records, len(cases))
        write_spotcheck(records)


if __name__ == "__main__":
    main()
