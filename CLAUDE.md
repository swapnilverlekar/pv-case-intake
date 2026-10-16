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
  - Routing: non-serious → always periodic; serious AND any unexpected → expedited_15_day; serious AND any ambiguous → ambiguous (excluded from the primary metric, reported separately); else periodic. due_date = receive_date + 15 days, expedited only.
  - 37 non-serious-only pairs remain undecided; they cannot change a route (non-serious is always periodic).
- [x] Generate intake narratives from raw facts — `AE_Data/generate_narratives.py` (Anthropic SDK, `claude-sonnet-5-5`, prompt **v3**, traced to LangSmith project `pv-case-intake`). Output: `data/narratives.jsonl`, **77 narratives** (dev 20 / test 57).
  - Pool: not ambiguous, 1–3 distinct suspect drugs (1–4 checked: only +4 expedited), minus `EXCLUDED_CASES` (20296669: reaction term says "labelled"). 77 cases: 28 expedited / 49 periodic.
  - Split `data/split.json` (tracked, seed 20261016, stratified by route × drug, reused unless `--resplit`): dev 20 (7 exp / 13 per), test 57 (21 / 36). Cases read during prompt work are forced into dev, so the test set stays unseen.
  - Generator sees facts only (no seriousness flag, expectedness, route, due date or label). `other_medically_important` is passed as "the reporter assessed this event as medically significant", voiced only by the reporter. Reporter role follows the FAERS qualification. Patients are never named; reporter names (per country/sex), sign-offs and non-clinical filler are assigned in code, all unique.
  - QA: deterministic checks (forbidden words, 80–200 words, drug name) + LLM fidelity check (same model; generation QA, never ground truth). Flagged → regenerated once → still flagged = `needs_review`.
  - v3 result: 53 passed first time, 13 passed after regeneration, **11 needs_review** (all fidelity flags; most look like the checker over-flagging rewordings — review in `data/narrative_spotcheck.md`). All 202 calls traced.
  - Prompt history: v1 invented symptoms/tests/treatments; v2 fixed that but mis-attributed significance and ran long; v3 fixes both.
- [ ] Build invalid cases and duplicate pairs
- [ ] Push dataset to LangSmith
- [ ] Build the agent system
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
