#!/usr/bin/env python3
"""
Derive expectedness ground truth: is each reported event listed in that drug's label?

Step 2 of the PV case intake build. This is the answer key the expectedness
specialist is graded against, so it must not depend on any model.
NO LLM CALLS ANYWHERE IN THIS FILE. String matching plus human review only.

"Unexpected" follows 21 CFR 314.80: an event not listed in the label,
INCLUDING one that is more severe or more specific than what the label lists.
So the matcher only ever makes lexical matches (same concept, different
words). It never decides that a broader label term covers a specific event;
those come out as "partial" and go to a human.

    python derive_expectedness.py                  # match, select, write review files
    python derive_expectedness.py --show-decided   # also list (drug, term) pairs already decided
    python derive_expectedness.py --spot-check     # sample "expected" rows to check for false matches
    python derive_expectedness.py --spot-check --rest   # every expected pair the sample left out
    python derive_expectedness.py --finalize       # decisions -> cases_labeled.json

Inputs, under data/ next to this script:
    cases_flat.json                 from pull_faers.py
    raw/label_<drug>.json           the pinned label per drug
    expectedness_synonyms.json      term -> label phrasings. LEXICAL equivalents only.
    term_decisions.csv              human decisions per (drug, term). Read, never written.

Outputs (all regenerated on every run; none holds human input):
    eval_candidates.json            the cases selected for the eval set
    expectedness_review.csv         one row per (selected case, reaction): matcher output
    term_review.csv                 one row per undecided (drug, term) to review
    cases_labeled.json              (--finalize) per-case expectedness and route
"""

import csv
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path

DATA = Path(__file__).resolve().parent / "data"
RAW = DATA / "raw"
SYNONYMS = DATA / "expectedness_synonyms.json"
TERM_DECISIONS = DATA / "term_decisions.csv"
CANDIDATES = DATA / "eval_candidates.json"
REVIEW_CSV = DATA / "expectedness_review.csv"
TERM_REVIEW = DATA / "term_review.csv"
LABELED = DATA / "cases_labeled.json"

# ---------------------------------------------------------------- config

# Searched in this order; the first one that matches supplies the snippet.
# Not "contraindications": it lists pre-existing patient conditions, not
# reactions the drug causes. It stays in the cached label, just unsearched.
LABEL_SECTIONS = [
    "adverse_reactions",
    "warnings",
    "warnings_and_cautions",
    "boxed_warning",
    "precautions",
]

# MedDRA terms are British, US labels are American. Plain substring
# replacement, applied to both the term and the label text. Extend freely.
BRITISH_TO_US = {
    "haem": "hem",            # haemorrhage, haematoma, haemoglobin
    "oedema": "edema",
    "diarrhoea": "diarrhea",
    "anaemia": "anemia",
    "oesophag": "esophag",
    "leukaemia": "leukemia",
    "ischaemi": "ischemi",
    "foetal": "fetal",
    "paediatric": "pediatric",
    "dyspnoea": "dyspnea",
    "aesthesia": "esthesia",  # paraesthesia, hypoaesthesia, anaesthesia
    "normalised": "normalized",  # international normalised ratio
    "oestr": "estr",
    "faec": "fec",
    "tumour": "tumor",
    "coeliac": "celiac",
}

# Lab test long name <-> abbreviations. Either side of a term may be swapped
# for the other before searching. Keys and values are normalized on load.
LAB_ABBREVIATIONS = {
    "international normalised ratio": ["inr"],
    "alanine aminotransferase": ["alt"],
    "aspartate aminotransferase": ["ast"],
    "thyroid stimulating hormone": ["tsh"],
    "creatine phosphokinase": ["cpk", "ck"],
}

# Tests that the "<lab test> increased/decreased" rule applies to. Without
# this list "Weight decreased" or "Blood pressure increased" would count as
# lab results. A leading "blood " on the term is ignored. Extend freely.
LAB_TESTS = [
    "glucose",
    "potassium",
    "sodium",
    "creatinine",
    "hemoglobin",
    "platelet count",
    "prothrombin time",
    "bilirubin",
    "thyroxine",
    "triiodothyronine",
    "hepatic enzyme",
    "transaminase",
    "lactic acid",
    "cholesterol",
    "triglycerides",
    *LAB_ABBREVIATIONS,
]
LAB_DIRECTION = {
    "increased": ("increas", "elevat"),
    "decreased": ("decreas", "low"),
}
LAB_WINDOW = 10  # tokens either side of the test name

# Words that qualify a term rather than name the clinical thing. Skipped when
# picking a term's main noun for the "partial" check.
QUALIFIERS = {
    "increased", "decreased", "upper", "lower", "prolonged", "abnormal",
    "aggravated", "acute", "chronic", "severe", "disorder", "syndrome",
    "disease", "symptom", "left", "right", "positive", "negative",
}

# Product / usage terms, not adverse reactions. Matched as substrings of the
# lowercased term; these rows are "not_applicable" and never checked against
# the label. Every catch is printed for review.
NON_EVENT_PATTERNS = [
    "off label",
    "drug ineffective",
    "product use",
    "product dose",
    "dose omission",
    "medication error",
    "wrong",
    "inappropriate schedule",
    "intentional",
    "no adverse event",
    "product quality",
    "drug interaction",
    "treatment failure",
    "product substitution",
    "contraindicated product administered",
    "exposure during pregnancy",
    "foetal exposure",
    "condition aggravated",
    # Product complaints with no health effect (added after Story 1 found
    # complaint-only cases labelled as valid with "unexpected" reactions).
    "product label issue",
    "product packaging",
    "poor quality product",
    "product complaint",
    "product quality issue",
    "product physical",  # physical consistency/appearance complaints (20349133)
    # Medication errors and procedures/treatments are not reactions (rule
    # change after Story 2: 20282292 "Transfusion" was keyed as an
    # unexpected reaction). Other procedure terms in the data (Dialysis,
    # Colectomy, Hip surgery, ...) await a decision: excluding them can hide
    # the serious event they stand in for.
    "incorrect route",
    "prescribing error",
    "wrong product",
    "administration error",
    "transfusion",
]

# Eval candidate selection.
MAX_REACTIONS = 3        # after removing not_applicable terms
MAX_CANDIDATES = 220
RARE_CRITERIA = ["death", "life_threatening", "disabling", "congenital_anomaly"]

# The route rule, applied only in --finalize. Plain date arithmetic.
EXPEDITED_DAYS = 15

# not_applicable: the event is the disease the drug treats (lack of effect),
# so it is excluded from expectedness, like the product/usage terms above.
DECISION_VALUES = {"expected", "unexpected", "ambiguous", "not_applicable"}
PARTIAL_FLAG = "check specificity/severity"

# ---------------------------------------------------------- normalization


def singular(word):
    """Crude, rule-based singular. Applied to term and label alike, so it
    only has to be consistent, not grammatically right."""
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    if word.endswith("sses"):
        return word[:-2]
    if len(word) > 3 and word.endswith("s") and not word.endswith(("ss", "us", "is")):
        return word[:-1]
    return word


def normalize_spelling(text):
    """lowercase + US spelling only, so character offsets still line up."""
    text = text.lower()
    for british, us in BRITISH_TO_US.items():
        text = text.replace(british, us)
    return text


def normalize(text):
    """lowercase, US spelling, punctuation -> space, singular, collapse whitespace."""
    text = re.sub(r"[^a-z0-9]+", " ", normalize_spelling(text))
    return " ".join(singular(w) for w in text.split())


ABBREVIATIONS = {
    normalize(long): [normalize(a) for a in abbrs]
    for long, abbrs in LAB_ABBREVIATIONS.items()
}
LAB_TEST_NAMES = sorted({normalize(t) for t in LAB_TESTS}, key=len, reverse=True)


def find_phrase(phrase, text):
    """Index of a whole-word match of phrase in text, or -1."""
    m = re.search(r"\b" + re.escape(phrase) + r"\b", text)
    return m.start() if m else -1


def snippet_around(text, index, width=200):
    start = max(0, index - width // 2)
    return text[start : start + width]


def non_event_pattern(term):
    """The pattern that marks this term as a non-event, or None."""
    lowered = term.lower()
    return next((p for p in NON_EVENT_PATTERNS if p in lowered), None)


def abbreviation_variants(phrase):
    """The phrase plus every long<->abbreviation swap of it."""
    variants = [phrase]
    for long, abbrs in ABBREVIATIONS.items():
        for abbr in abbrs:
            if find_phrase(long, phrase) >= 0:
                variants.append(re.sub(r"\b" + re.escape(long) + r"\b", abbr, phrase))
            if find_phrase(abbr, phrase) >= 0:
                variants.append(re.sub(r"\b" + re.escape(abbr) + r"\b", long, phrase))
    return variants


def main_noun(phrase):
    """The term's main clinical noun: before 'in'/'of', last non-qualifier word.
    'gastrointestinal hemorrhage' -> hemorrhage, 'pain in extremity' -> pain."""
    head = re.split(r"\b(?:in|of|on|with)\b", phrase)[0].split()
    content = [w for w in head if w not in QUALIFIERS]
    return content[-1] if content else None


# --------------------------------------------------------------- matching


def load_labels():
    labels = {}
    for path in sorted(RAW.glob("label_*.json")):
        label = json.loads(path.read_text())
        labels[label["drug"]] = {
            "effective_time": label["effective_time"],
            "raw": {s: label[s] for s in LABEL_SECTIONS if label.get(s)},
            "sections": {
                s: normalize(label[s]) for s in LABEL_SECTIONS if label.get(s)
            },
        }
    return labels


def search_label(phrase, label):
    """(matched sections, snippet from the first) for one normalized phrase."""
    sections, snippet = [], ""
    for name, text in label["sections"].items():
        i = find_phrase(phrase, text)
        if i >= 0:
            if not sections:
                snippet = snippet_around(text, i)
            sections.append(name)
    return sections, snippet


def search_lab(term, label):
    """'<lab test> increased/decreased': the test name (or its abbreviation)
    within LAB_WINDOW tokens of a word for the same direction."""
    m = re.fullmatch(r"(?:blood )?(.+) (increased|decreased)", term)
    if not m:
        return [], ""
    test, direction = m.groups()
    if test not in LAB_TEST_NAMES:
        return [], ""

    names = abbreviation_variants(test)
    stems = LAB_DIRECTION[direction]
    sections, snippet = [], ""
    for section, text in label["sections"].items():
        tokens = text.split()
        for name in names:
            n = len(name.split())
            hit = next(
                (
                    i
                    for i in range(len(tokens) - n + 1)
                    if tokens[i : i + n] == name.split()
                    and any(
                        t.startswith(stems)
                        for t in tokens[max(0, i - LAB_WINDOW) : i + n + LAB_WINDOW]
                    )
                ),
                None,
            )
            if hit is not None:
                if not sections:
                    start = max(0, hit - LAB_WINDOW)
                    snippet = " ".join(tokens[start : hit + n + LAB_WINDOW])
                sections.append(section)
                break
    return sections, snippet


def classify(term, label, synonyms):
    """status, matched_section, snippet for one reaction term. Order matters:
    every status above "partial" is lexical; "partial" is never a match."""
    if non_event_pattern(term):
        return "not_applicable", "", ""

    norm = normalize(term)

    for variant in abbreviation_variants(norm):
        sections, snippet = search_label(variant, label)
        if sections:
            return "expected", ";".join(sections), snippet

    for phrasing in synonyms.get(norm, []):
        sections, snippet = search_label(normalize(phrasing), label)
        if sections:
            return "expected_synonym", ";".join(sections), snippet

    sections, snippet = search_lab(norm, label)
    if sections:
        return "expected_lab", ";".join(sections), snippet

    noun = main_noun(norm)
    if noun and noun != norm:
        sections, snippet = search_label(noun, label)
        if sections:
            return "partial", ";".join(sections), snippet

    # Not found is a candidate for unexpected, not a verdict.
    return "unmatched", "", ""


def load_synonyms():
    if not SYNONYMS.exists():
        SYNONYMS.write_text("{}\n")
    raw = json.loads(SYNONYMS.read_text())
    return {normalize(term): phrasings for term, phrasings in raw.items()}


def load_term_decisions():
    """{(drug, term): (decision, notes)}. Created empty if missing; never rewritten."""
    if not TERM_DECISIONS.exists():
        TERM_DECISIONS.write_text("target_drug,term,decision,notes\n")
        return {}

    decisions = {}
    with TERM_DECISIONS.open() as f:
        for row in csv.DictReader(f):
            decision = row["decision"].strip().lower()
            if not decision:
                continue
            if decision not in DECISION_VALUES:
                sys.exit(
                    f"{TERM_DECISIONS.name}: bad decision {decision!r} for "
                    f"{row['target_drug']} / {row['term']!r}; "
                    f"use one of {sorted(DECISION_VALUES)}"
                )
            key = (row["target_drug"].strip(), row["term"].strip())
            decisions[key] = (decision, row.get("notes", "").strip())
    return decisions


def match_all(cases, labels, synonyms):
    """{(report id, drug): [reaction row, ...]} for every case."""
    matched = {}
    for case in cases:
        label = labels[case["target_drug"]]
        rows = []
        for reaction in case["reactions"]:
            status, section, snippet = classify(reaction["term"], label, synonyms)
            rows.append(
                {
                    "term": reaction["term"],
                    "status": status,
                    "matched_section": section,
                    "snippet": snippet,
                }
            )
        matched[case_key(case)] = rows
    return matched


def case_key(case):
    # A report can carry two of our drugs as suspects, so a case is keyed by
    # (report id, target drug), not report id alone.
    return (case["safety_report_id"], case["target_drug"])


# ------------------------------------------------------------- selection


def select_candidates(cases, matched):
    """Stratified eval set, chosen before any review so review effort is not
    spent on cases that will never be scored. Frozen once written: a later
    rule change must relabel cases, not silently move them out of the set.
    --reselect rebuilds it."""
    if CANDIDATES.exists() and "--reselect" not in sys.argv:
        frozen = load_candidate_keys()
        selected = [c for c in cases if case_key(c) in frozen]
        reasons = {(c["safety_report_id"], c["target_drug"]): c["reason"] for c in json.loads(CANDIDATES.read_text())}
        print(f"reusing {CANDIDATES.name} ({len(selected)} cases); --reselect to rebuild")
        return selected, selected, {case_key(c): reasons[case_key(c)] for c in selected}

    eligible = [
        c
        for c in cases
        if 1
        <= sum(r["status"] != "not_applicable" for r in matched[case_key(c)])
        <= MAX_REACTIONS
    ]
    eligible.sort(key=case_key)

    picked = {}

    def take(case, reason):
        picked.setdefault(case_key(case), reason)

    for c in eligible:
        if not c["is_serious"]:
            take(c, "non_serious")
    for c in eligible:
        if any(c["seriousness_criteria"][k] for k in RARE_CRITERIA):
            take(c, "rare_criterion")

    # Fill what is left with serious cases, round-robin across drugs so no
    # one drug dominates.
    by_drug = defaultdict(list)
    for c in eligible:
        if c["is_serious"] and case_key(c) not in picked:
            by_drug[c["target_drug"]].append(c)
    while len(picked) < MAX_CANDIDATES and any(by_drug.values()):
        for drug in sorted(by_drug):
            if by_drug[drug] and len(picked) < MAX_CANDIDATES:
                take(by_drug[drug].pop(0), "serious_stratified")

    selected = [c for c in eligible if case_key(c) in picked]
    CANDIDATES.write_text(
        json.dumps(
            [
                {
                    "safety_report_id": c["safety_report_id"],
                    "target_drug": c["target_drug"],
                    "is_serious": c["is_serious"],
                    "reason": picked[case_key(c)],
                }
                for c in selected
            ],
            indent=2,
        )
    )
    return eligible, selected, picked


def load_candidate_keys():
    if not CANDIDATES.exists():
        sys.exit(f"no {CANDIDATES.name}; run without --finalize first")
    return {
        (c["safety_report_id"], c["target_drug"])
        for c in json.loads(CANDIDATES.read_text())
    }


# ------------------------------------------------------------ term review


def label_sentences(label):
    """[(section, original sentence, normalized token set)] for one label."""
    out = []
    for section, text in label["raw"].items():
        for sentence in re.split(r"(?<=[.;])\s+", text):
            tokens = set(normalize(sentence).split())
            if tokens:
                out.append((section, sentence.strip(), tokens))
    return out


def nearest_sentence(term, sentences):
    """Label sentence sharing the most tokens with the term, token Jaccard as
    the tie-break. Sentences holding the term's main noun rank first, so a
    "partial" row shows the text it partially matched. A review aid, never a
    decision. Blank if nothing overlaps."""
    norm = normalize(term)
    want, noun = set(norm.split()), main_noun(norm)
    best = max(
        sentences,
        key=lambda s: (
            noun in s[2],
            len(want & s[2]),
            len(want & s[2]) / len(want | s[2]),
        ),
        default=("", "", set()),
    )
    if not want & best[2]:
        return "", ""

    # Long "sentences" are often flattened lists; centre the excerpt on the
    # main noun so the reviewer sees what matched.
    section, sentence = best[0], best[1]
    hit = re.search(r"\b" + re.escape(noun or ""), normalize_spelling(sentence))
    start = max(0, hit.start() - 120) if hit and noun else 0
    return section, sentence[start : start + 300]


def write_term_review(selected, matched, labels, decisions, show_decided):
    pairs = defaultdict(lambda: {"rows": 0, "serious": False, "statuses": set()})
    for case in selected:
        for r in matched[case_key(case)]:
            if r["status"] in ("unmatched", "partial"):
                p = pairs[(case["target_drug"], r["term"])]
                p["rows"] += 1
                p["serious"] |= case["is_serious"]
                p["statuses"].add(r["status"])

    sentences = {drug: label_sentences(label) for drug, label in labels.items()}
    rows, already_decided = [], 0
    for (drug, term), p in pairs.items():
        decided = decisions.get((drug, term))
        if decided and not show_decided:
            already_decided += 1
            continue
        status = "partial" if "partial" in p["statuses"] else "unmatched"
        section, sentence = nearest_sentence(term, sentences[drug])
        rows.append(
            {
                "target_drug": drug,
                "term": term,
                "status": status,
                "flag": PARTIAL_FLAG if status == "partial" else "",
                "row_count": p["rows"],
                "in_serious_case": "y" if p["serious"] else "n",
                "nearest_label_sentence": sentence,
                "nearest_section": section,
                "decision": decided[0] if decided else "",
                "notes": decided[1] if decided else "",
            }
        )

    rows.sort(key=lambda r: (r["in_serious_case"] != "y", -r["row_count"],
                             r["target_drug"], r["term"]))
    with TERM_REVIEW.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]) if rows else ["target_drug"])
        writer.writeheader()
        writer.writerows(rows)
    return rows, already_decided


# ------------------------------------------------------------- derive


def derive():
    cases = json.loads((DATA / "cases_flat.json").read_text())
    labels = load_labels()
    synonyms = load_synonyms()
    decisions = load_term_decisions()

    matched = match_all(cases, labels, synonyms)
    eligible, selected, picked = select_candidates(cases, matched)

    # Row-level matcher output for the selected cases. No human input lives
    # here, so rewriting it on every run is safe.
    review_rows = [
        {
            "safety_report_id": c["safety_report_id"],
            "target_drug": c["target_drug"],
            "is_serious": c["is_serious"],
            **r,
            "flag": PARTIAL_FLAG if r["status"] == "partial" else "",
        }
        for c in selected
        for r in matched[case_key(c)]
    ]
    review_rows.sort(
        key=lambda r: (
            not r["is_serious"],
            r["status"] not in ("unmatched", "partial"),
            r["target_drug"],
            r["safety_report_id"],
        )
    )
    with REVIEW_CSV.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(review_rows[0]))
        writer.writeheader()
        writer.writerows(review_rows)

    term_rows, already_decided = write_term_review(
        selected, matched, labels, decisions, "--show-decided" in sys.argv
    )

    report(cases, matched, eligible, selected, picked, term_rows, already_decided, labels)


def report(cases, matched, eligible, selected, picked, term_rows, already_decided, labels):
    all_rows = [r for c in cases for r in matched[case_key(c)]]
    sel_rows = [r for c in selected for r in matched[case_key(c)]]

    print("labels used:")
    for drug, label in sorted(labels.items()):
        print(f"  {drug}: effective {label['effective_time']}")

    print(f"\nmatcher status, all {len(cases)} cases ({len(all_rows)} reaction rows):")
    for status, n in Counter(r["status"] for r in all_rows).most_common():
        print(f"  {status}: {n}")
    print(f"unique terms: {len({r['term'] for r in all_rows})}")

    print(f"\nmatcher status, selected cases ({len(sel_rows)} reaction rows):")
    for status, n in Counter(r["status"] for r in sel_rows).most_common():
        print(f"  {status}: {n}")

    caught = Counter(r["term"] for r in all_rows if r["status"] == "not_applicable")
    print(f"\nnot_applicable terms ({len(caught)} unique), with the pattern that caught them:")
    for term, n in sorted(caught.items()):
        print(f"  {n:3}  {term:48} <- '{non_event_pattern(term)}'")

    lab = Counter(
        (c["target_drug"], r["term"])
        for c in cases
        for r in matched[case_key(c)]
        if r["status"] == "expected_lab"
    )
    print(f"\nexpected_lab matches ({len(lab)} unique), audit these:")
    for (drug, term), n in sorted(lab.items()):
        print(f"  {n:3}  {drug:13} {term}")

    serious = [c for c in selected if c["is_serious"]]
    open_serious = [
        c
        for c in serious
        if any(r["status"] in ("unmatched", "partial") for r in matched[case_key(c)])
    ]
    print("\neval candidates:")
    print(f"  eligible (1-{MAX_REACTIONS} reactions after not_applicable): {len(eligible)} of {len(cases)}")
    print(f"  selected: {len(selected)}  (cap {MAX_CANDIDATES})")
    print(f"  serious / non-serious: {len(serious)} / {len(selected) - len(serious)}")
    print(f"  by reason: {dict(Counter(picked.values()))}")
    print("  by drug (serious / non-serious):")
    for drug in sorted({c['target_drug'] for c in selected}):
        mine = [c for c in selected if c["target_drug"] == drug]
        s = sum(c["is_serious"] for c in mine)
        print(f"    {drug:13} {len(mine):3}  ({s} / {len(mine) - s})")
    rare = Counter(
        k for c in selected for k in RARE_CRITERIA if c["seriousness_criteria"][k]
    )
    print(f"  rare criteria kept: {dict(rare)}")
    print(
        f"  selected serious with >=1 unmatched or partial row: "
        f"{len(open_serious)} of {len(serious)}"
    )

    print(f"\nterm_review.csv: {len(term_rows)} (drug, term) rows to review"
          f"  ({already_decided} already decided, hidden)")
    print(f"  {dict(Counter(r['status'] for r in term_rows))}")
    print(f"\nWrote {CANDIDATES.name}, {REVIEW_CSV.name}, {TERM_REVIEW.name}")


# ----------------------------------------------------------- spot check

# Short or generic terms are the likeliest false exact matches ("Fall"
# matching "a fall in blood pressure"), so they are sampled first.
GENERIC_TERMS = {"death", "fall", "pain", "malaise", "fatigue", "injury"}
SPOT_CHECK_SIZE = 20
SPOT_CHECK_SEED = 7  # fixed, so the same sample comes back on a re-run


def spot_check(rest_only=False):
    """Print a sample of "expected" rows with the label sentence that matched.
    With rest_only=True, print every expected pair the sample left out."""
    import random

    cases = json.loads((DATA / "cases_flat.json").read_text())
    labels = load_labels()
    matched = match_all(cases, labels, load_synonyms())
    candidates = load_candidate_keys()

    pairs = sorted(
        {
            (c["target_drug"], r["term"])
            for c in cases
            if case_key(c) in candidates
            for r in matched[case_key(c)]
            if r["status"] == "expected"
        }
    )
    generic = [p for p in pairs if normalize(p[1]) in GENERIC_TERMS
               or len(normalize(p[1]).split()) == 1]
    rest = [p for p in pairs if p not in generic]
    rng = random.Random(SPOT_CHECK_SEED)
    sample = generic if len(generic) <= SPOT_CHECK_SIZE else rng.sample(generic, SPOT_CHECK_SIZE)
    sample += rng.sample(rest, min(len(rest), SPOT_CHECK_SIZE - len(sample)))
    if rest_only:
        sample = [p for p in pairs if p not in sample]

    sentences = {drug: label_sentences(label) for drug, label in labels.items()}
    which = "not in the seeded sample" if rest_only else "single-word / generic terms first"
    print(f"{len(sample)} of {len(pairs)} expected (drug, term) pairs; {which}\n")
    for i, (drug, term) in enumerate(sample, 1):
        phrase = normalize(term)
        section, sentence = next(
            (
                (sec, sent)
                for sec, sent, _ in sentences[drug]
                if find_phrase(phrase, normalize(sent)) >= 0
            ),
            ("", "(phrase spans a sentence break)"),
        )
        hit = re.search(re.escape(phrase.split()[0]), normalize_spelling(sentence))
        start = max(0, hit.start() - 120) if hit else 0
        print(f"{i:2}. {drug:13} {term}\n    [{section}] ...{sentence[start:start + 260]}...\n")


# ------------------------------------------------------------- finalize

# Matcher status -> final expectedness when no human decision exists.
DEFAULT_DECISION = {
    "expected": "expected",
    "expected_synonym": "expected",
    "expected_lab": "expected",
    "unmatched": "unexpected",
    "not_applicable": "excluded",
    # "partial" deliberately absent: it needs a human decision.
}

NO_EVENT_NOTE = (
    "Relabelled invalid (no_adverse_event): every reported term is a non-event "
    "(product complaint, lack of effect, or usage term). Rule change after Story 1; "
    "previously such cases were dropped, or labelled valid when a product-complaint "
    "term slipped past NON_EVENT_PATTERNS."
)

# Human decision -> final expectedness. Only not_applicable is renamed.
HUMAN_DECISION = {
    "expected": "expected",
    "unexpected": "unexpected",
    "ambiguous": "ambiguous",
    "not_applicable": "excluded",
}


def finalize():
    cases = json.loads((DATA / "cases_flat.json").read_text())
    labels = load_labels()
    decisions = load_term_decisions()
    candidates = load_candidate_keys()
    matched = match_all(cases, labels, load_synonyms())

    selected = [c for c in cases if case_key(c) in candidates]
    if len(selected) != len(candidates):
        sys.exit("eval_candidates.json names cases missing from cases_flat.json")

    # An undecided partial blocks finalizing only if it can change a route,
    # i.e. it appears in a serious case. In non-serious cases it can never
    # make a case expedited, so it is recorded as ambiguous instead.
    partial_in_serious = {
        (c["target_drug"], r["term"])
        for c in selected
        if c["is_serious"]
        for r in matched[case_key(c)]
        if r["status"] == "partial"
    }

    labeled, undecided_partial, relabelled = [], set(), []
    for case in selected:
        reactions = []
        for r in matched[case_key(case)]:
            pair = (case["target_drug"], r["term"])
            decided = decisions.get(pair)
            if decided:
                final, source = HUMAN_DECISION[decided[0]], "human"
            elif r["status"] == "partial" and pair in partial_in_serious:
                undecided_partial.add(pair)
                continue
            elif r["status"] == "partial":
                final, source = "ambiguous", "undecided_partial_non_serious"
            else:
                final, source = DEFAULT_DECISION[r["status"]], "matcher"
            reactions.append({**r, "expectedness": final, "decided_by": source})

        # Every reaction is a non-event (product complaint, lack of effect,
        # usage term): there is no adverse event, so this is not a valid
        # case. It is kept and labelled invalid, not dropped.
        if reactions and all(r["expectedness"] == "excluded" for r in reactions):
            relabelled.append(case_key(case))
            labeled.append(
                {
                    **case,
                    "reaction_expectedness": reactions,
                    "valid": False,
                    "missing_element": ["no_adverse_event"],
                    "expectedness": None,
                    "reporting_route": "follow_up_required",
                    "due_date": None,
                    "label_effective_time": labels[case["target_drug"]]["effective_time"],
                    "label_note": NO_EVENT_NOTE,
                }
            )
            continue

        # Precedence: one unexpected reaction in a serious case is enough to
        # start the clock, whatever the other reactions are.
        finals = {r["expectedness"] for r in reactions}
        if "unexpected" in finals:
            expectedness = "unexpected"
        elif "ambiguous" in finals:
            expectedness = "ambiguous"
        else:
            expectedness = "expected"

        # A non-serious case can never be expedited, so its route is known
        # whatever its reactions are; only serious cases can be ambiguous.
        if not case["is_serious"]:
            route = "periodic"
        elif expectedness == "unexpected":
            route = "expedited_15_day"
        elif expectedness == "ambiguous":
            route = "ambiguous"  # reported separately, not in the primary metric
        else:
            route = "periodic"

        due = None
        if route == "expedited_15_day":
            d = case["receive_date"]
            due = date(int(d[:4]), int(d[4:6]), int(d[6:8])) + timedelta(days=EXPEDITED_DAYS)

        labeled.append(
            {
                **case,
                "reaction_expectedness": reactions,
                "valid": True,
                "missing_element": None,
                "expectedness": expectedness,
                "reporting_route": route,
                "due_date": due.isoformat() if due else None,
                "label_effective_time": labels[case["target_drug"]]["effective_time"],
            }
        )

    if undecided_partial:
        print(f"{len(undecided_partial)} partial (drug, term) pairs have no decision "
              f"in {TERM_DECISIONS.name}:")
        for drug, term in sorted(undecided_partial):
            print(f"  {drug:13} {term}")
        sys.exit("Decide these before finalizing. Nothing written.")

    LABELED.write_text(json.dumps(labeled, indent=2))

    if relabelled:
        print(f"relabelled {len(relabelled)} cases invalid (no_adverse_event: every reaction is a non-event):")
        for report_id, drug in relabelled:
            print(f"  {report_id}  {drug}")
        print()

    routes = ["expedited_15_day", "periodic", "ambiguous", "follow_up_required"]
    print(f"cases: {len(labeled)}")
    print(f"  {'drug':13} " + " ".join(f"{r:>18}" for r in routes))
    for drug in sorted({c["target_drug"] for c in labeled}):
        counts = Counter(c["reporting_route"] for c in labeled if c["target_drug"] == drug)
        print(f"  {drug:13} " + " ".join(f"{counts[r]:>18}" for r in routes))
    totals = Counter(c["reporting_route"] for c in labeled)
    print(f"  {'total':13} " + " ".join(f"{totals[r]:>18}" for r in routes))
    print(f"\nWrote {LABELED}")


if __name__ == "__main__":
    if "--finalize" in sys.argv:
        finalize()
    elif "--spot-check" in sys.argv:
        spot_check(rest_only="--rest" in sys.argv)
    else:
        derive()
