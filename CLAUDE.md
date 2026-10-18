# PV case intake triage — MVP

## What this is

An MVP agent system that triages inbound pharmacovigilance (adverse event) reports. A messy intake narrative comes in — a call-centre transcript, an HCP email, a literature abstract — and the system decides: is this a valid case, how serious is it, is the event already known for this drug, is it a duplicate, and what regulatory reporting deadline does it start. A qualified human signs off before anything commits.

Built as a take-home for a LangChain Deployed Engineer role. It is presented live to a panel playing customer stakeholders deciding whether to fund the project further. Evaluation rigour is the most heavily weighted criterion — build quality matters, production hardening does not.

## Stack

Python · LangChain / LangGraph · LangSmith for tracing and evals · openFDA for data. Keys in `.env` at the repo root (see `.env.example`).

## Architecture rules — do not violate these

- The model produces evidence; code produces decisions. Every determination must cite the narrative span or label section it rests on.
- The reporting clock is pure deterministic Python. Never computed, adjusted or explained by a model. serious AND unexpected → 15 calendar days from the receipt timestamp. This is a legal deadline; a model cannot be in that path.
- The receipt timestamp is captured once and never recomputed.
- The human gate is enforced in code, not prompted. No case reaches the audit log without sign-off. Every expedited determination goes to a human regardless of confidence score.
- Only one component is a real agent — the follow-up planner, which decides what to ask a reporter when a case is incomplete, because the questions depend on what is missing. Everything else is a deterministic node or a single structured LLM call.
- Do not name something `*_agent` unless the model chooses the next action inside it. Precision here is deliberate and will be questioned live.
- LangSmith tracing on from the first commit, not bolted on at the end.

## Pipeline

```
intake normalizer   (code — captures receipt timestamp)
  → extraction      (model, structured output)
    → validity gate (code — four regulatory elements present?)
       ├─ invalid → follow-up planner  (AGENT)
       └─ valid   → three specialists in parallel:
            · seriousness    (model — six defined criteria)
            · expectedness   (model + retrieval against the drug label)
            · duplicate check (fuzzy match against case store)
         → clock calculation      (code)
         → confidence + routing   (code)
         → human sign-off gate    (hard)
         → case write + audit log (append-only)
```

## Data

Real labels, synthesised narratives. FDA redacts the reporter narrative before publishing FAERS, so we take real labelled cases and reconstruct plausible intake text from their raw facts. The labels stay real; only the wording is generated.

Scope is six drugs: lisinopril, metformin, warfarin, sertraline, atorvastatin, levothyroxine. Each one means an approved label we have to read, which is why the list is short.

Reference labels (pinned in `AE_Data/pull_faers.py` `LABEL_SEARCH`, cached in `AE_Data/data/raw/label_*.json`, tracked in git):

| drug | label | effective_time |
|---|---|---|
| lisinopril | Zestril | 20250102 |
| metformin | Metformin Hydrochloride (generic; no Glucophage label on openFDA) | 20240821 |
| warfarin | Jantoven (Coumadin discontinued) | 20250708 |
| sertraline | Zoloft | 20230808 |
| atorvastatin | Lipitor | 20240415 |
| levothyroxine | Synthroid | 20240220 |

A FAERS report can name two of our drugs as suspects (3 such reports today), so a case is keyed by `(safety_report_id, target_drug)`, not report id alone.

Never use a combination-product label (e.g. lisinopril + HCTZ, sitagliptin + metformin) — `fetch_label` refuses them.

## Current status

- [x] `AE_Data/pull_faers.py` — pulls adverse event cases + SPL labels from openFDA, decodes the coded fields, writes `data/cases_flat.json`. `--from-raw` rebuilds from cached events without hitting the API.
- [x] Rebalance: `pull_faers.py --topup` adds non-serious cases (`serious:2`) and tops up thin drugs. Now 200 cases, 140 serious / 60 non-serious, every drug ≥ 20 (see `data/summary.txt`).
- [x] Derive expectedness per case — `AE_Data/derive_expectedness.py`, deterministic, no LLM calls. Output: `data/cases_labeled.json` (tracked), **128 cases: 58 expedited_15_day / 60 periodic / 10 ambiguous** (3 dropped: every reaction excluded). Later edits: both `Liver disorder` and warfarin `Haemoglobin decreased` → ambiguous (less specific than / a lab sign of what the label lists). Edit decision rows in place; never append a second row for the same pair.
  - Lexical matcher: plurals, British→US, lab abbreviations, `<lab test> increased/decreased` (`expected_lab`), `expectedness_synonyms.json` (lexical equivalents only). Never matches a specific term to a broader label term (21 CFR 314.80) — those are `partial` and need a human decision. Searches adverse_reactions, warnings, warnings_and_cautions, boxed_warning, precautions — **not contraindications**.
  - Eval candidates fixed before review: `data/eval_candidates.json` (131 cases, 1–3 reactions after not_applicable). Accepted as-is: 0 congenital-anomaly cases, lisinopril/levothyroxine below 20, the 13 `expected_lab` matches.
  - Human decisions per (drug, term) in `data/term_decisions.csv` (never written by the script). 81 of them were drafted with ChatGPT and verified by the reviewer (`data/my_review.csv`); the rest were decided directly. `Death` is always `ambiguous`. `not_applicable` = the treated disease (lack of effect).
  - **Rule change (after Story 1):** product-complaint terms added to `NON_EVENT_PATTERNS` ("product label issue", "product packaging", "poor quality product", "product complaint", "product quality issue", "product physical"). A case whose reactions are ALL non-events is **not dropped**: it is labelled invalid (`valid=false`, `missing_element=["no_adverse_event"]`, `follow_up_required`, `label_note`). 5 cases: 20321855, 20349133 (product complaints), 20279756, 20289588, 20297086 (previously dropped). `eval_candidates.json` is now frozen (`--reselect` to rebuild) so a rule change relabels cases instead of moving them out of the set.
  - `missing_element` is a LIST. Message-level gaps add to it (`message_missing_elements` on the narrative record): 20349133's patient-reporter gives no name, contact or qualification → `["no_adverse_event", "no_identifiable_reporter"]`.
  - Duplicate references: route `merge_with_existing`, no due date (no new clock). References for duplicates/near-misses are rebuilt from `cases_labeled.json` at upload time.
  - Routing: non-serious → always periodic; serious AND any unexpected → expedited_15_day; serious AND any ambiguous → ambiguous (excluded from the primary metric, reported separately); else periodic. due_date = receive_date + 15 days, expedited only.
  - 37 non-serious-only pairs remain undecided; they cannot change a route (non-serious is always periodic).
- [x] Generate intake narratives from raw facts — `AE_Data/generate_narratives.py` (Anthropic SDK, `claude-sonnet-5-5`, prompt **v3**, traced to LangSmith project `pv-case-intake`). Output: `data/narratives.jsonl`, **77 narratives** (dev 20 / test 57).
  - Pool: not ambiguous, 1–3 distinct suspect drugs (1–4 checked: only +4 expedited), minus `EXCLUDED_CASES` (20296669: reaction term says "labelled"). 77 cases: 28 expedited / 49 periodic.
  - Split `data/split.json` (tracked, seed 20261016, stratified by route × drug, reused unless `--resplit`): dev 20 (7 exp / 13 per), test 57 (21 / 36). Cases read during prompt work are forced into dev, so the test set stays unseen.
  - Generator sees facts only (no seriousness flag, expectedness, route, due date or label). `other_medically_important` is passed as "the reporter assessed this event as medically significant", voiced only by the reporter. Reporter role follows the FAERS qualification. Patients are never named; reporter names (per country/sex), sign-offs and non-clinical filler are assigned in code, all unique.
  - QA: deterministic checks (forbidden words, 80–200 words, drug name) + LLM fidelity check (same model; generation QA, never ground truth). Flagged → regenerated once → still flagged = `needs_review`.
  - v3 result: 53 passed first time, 13 passed after regeneration, 11 needs_review → reviewed (`reviewed_by: llm_assisted_human`): 4 hand-edited (`manual_edit: true`), 7 accepted. All 202 calls traced.
  - Prompt history: v1 invented symptoms/tests/treatments; v2 fixed that but mis-attributed significance and ran long; v3 fixes both.
- [x] Build invalid cases and duplicate pairs — `AE_Data/construct_cases.py` → `data/constructed_cases.jsonl` (30). No answer key is model-decided: invalid keys are fixed by construction, duplicate keys copied from the original, near-miss keys are real.
  - **invalid (15, dev 5 / test 10):** a real, not-otherwise-narrated case with ONE element removed (no identifiable patient 4 / reporter 4 / suspect drug 4 / adverse event 3). Key: `valid=false`, `missing_element`, `reporting_route=follow_up_required`, rest null. Sources must have ≥1 real adverse event (not a product/usage term, not a human `not_applicable`), so exactly one element is missing.
  - **duplicate (10, dev 5 / test 5):** second report of a narrated case from the other side (consumer ↔ HCP), age ±1, start date a few days off, received 2–12 days later. Key: the original's, plus `duplicate_of` = original report id (due date still runs from the original receipt).
  - **near_miss (5, test):** REAL labelled cases (same drug, same sex, age within 5 y as a narrated case, no shared reactions). Key: their own, `duplicate_of=null`.
  - The fidelity check is shown a constructed case's special instruction, so content the writer was told to produce isn't flagged. One false positive cleared by Claude (`reviewed_by: claude_verified`, with a `review_note`).
- [x] Push dataset to LangSmith — `AE_Data/upload_dataset.py` → dataset **`pv-case-intake`**, **107 examples: dev 30 (9 expedited / 16 periodic / 5 follow-up), test 77 (25 / 42 / 10)**. Local files are the source of truth; never edit in the UI. Deterministic example ids (uuid5 of the case key) → a re-run updates the same dataset (new version), tagged `git-<commit>`. `needs_review` records are never uploaded.
- [~] Build the agent system — package `pv_agent/` (LangGraph v1 `StateGraph`, `langchain-anthropic`, model in `pv_agent/config.py`). The agent's only inputs are the message (header + narrative) and the cached labels (`labels.py` refuses any other path); run scripts pass `agent_inputs()` only, never reference outputs.
  - [x] **Story 1: intake → extraction → product normalization → validity gate.** `python -m pv_agent.run_one <example_key>` (dev only), `python -m pv_agent.run_dev_validity`.
    - intake (code): receipt timestamp from the header's `Received:` line; the state reducer makes it write-once (a changed value raises).
    - extraction (one structured LLM call, `method="json_schema"` — Sonnet 5.5 rejects forced tool choice): patient, reporter, products, reactions, each with a verbatim quote. Code enforces "no quote, no value" and logs drops in `rejected_evidence`; a product's quote may be code-located (`quote_source: code_located`) when the message names one of our drugs.
    - normalization (code): label generic/brand names + `BRAND_ALIASES` (other US brands of the same ingredient), whole-word, longest match.
    - validity gate (code): patient = specific reference, age or sex; reporter = name, contact, **or stated HCP qualification (ICH E2D)**; suspect drug = one of our six, suspect unless the reporter explicitly rules it out (MAH convention); ≥1 event. invalid → `follow_up_required`, valid → `pending_assessment`.
    - Dev result: 26/30 valid and missing_element. 3 of the 4 misses are **answer-key defects**: 20321855 (and its duplicate) and 20349133 are product complaints whose FAERS terms include "No adverse event", but product-issue terms ("Product label issue", "Poor quality product administered", ...) slipped past `NON_EVENT_PATTERNS`, so the key says valid. Not yet fixed. 1 agent miss: INV-20304190, where the relaying hairdresser's "She" was taken as the patient's sex.
  - [x] **Story 2: specialists, duplicate check, clock.** Valid branch fans out to three parallel specialists (each writes its own state key), joined at the clock. `python -m pv_agent.run_dev_route`.
    - seriousness (one structured call): the six 21 CFR 314.80 criteria, each with a quote; code drops quotes not in the message and computes `is_serious`.
    - expectedness (one structured call per case): reactions vs the target label's adverse_reactions/warnings/warnings_and_cautions/boxed_warning/precautions (not contraindications), label text prompt-cached, `label_effective_time` logged as run metadata. Code: "expected" needs a verbatim label quote, else downgraded to unexpected + `needs_review`; "unsure" → unexpected + `needs_review`. Built independently of the answer-key method (nothing from derive_expectedness / term_decisions / synonyms).
    - duplicate check: `AE_Data/build_case_store.py` → `data/case_store.json` (tracked; identifying facts only, no seriousness/expectedness/route). Visible = received strictly before this report's receipt date; code pre-filter (same drug, compatible sex, age ±2 y, within 120 days); one structured call picks `duplicate_of` from the candidates (anything else is ignored).
    - clock (code): duplicate → `merge_with_existing`; not serious → periodic; serious + any unexpected → `expedited_15_day`, due = receipt date + 15; else periodic.
    - Extraction fix found by the metformin lactic-acidosis death: outcomes (death, admission, recovery, treatment) are NOT reactions — "she died" as a reaction made an expected fatal lactic acidosis look unexpected.
    - Dev: route 28/30, **expedited recall 6/7, precision 6/6**, is_serious 22/22, due date 6/6, duplicate_of 4/5 (the miss is DUP-20321855, an invalid report — the gate fires before the duplicate check, by design). Misses: 20282292 (key says "Transfusion" is an unexpected reaction; the agent treats it as treatment — arguably a key issue) and 20328474 (agent merges with 20292174: same pharmacist-reported 65/66 M lisinopril angioedema 8 days earlier — a plausible real FAERS duplicate the key doesn't mark).
  - [ ] Story 3: follow-up planner (the only agent). [ ] Human sign-off gate + audit log.
- [ ] Evaluators and experiments

## Conventions

- Anaconda's Brotli 1.0.9 breaks the Anthropic SDK's response decoding (surfaces as "Connection error"); clients send `Accept-Encoding: gzip`. `pip install -U brotli` is the real fix.
- Keep the dataset build in scripts, not notebooks — it gets regenerated.
- Cache SPL labels to disk with their effective_time; the same label version must be used at eval time and run time. Labels are only re-fetched with `--refresh-labels`.
- Log the label version as run metadata on every expectedness call.
- Small, readable modules over clever abstractions. This code gets read aloud.

## Out of scope — do not build these

Clinical trial (IND) reporting, MedDRA autocoding, causality assessment, E2B submission, more drugs, auth, a UI beyond what the demo needs.

After the dataset is built, no new capability goes in. If there is spare time it goes into evaluation, not features.
