# How we evaluate the PV intake triage system

This document explains how we know whether the system works: what we test it on, what we measure, why one number matters more than the others, and how we would keep measuring it in production.

## 1. What the system has to get right

An adverse event report comes in. The system must decide:

- **is it a valid case?** It needs an identifiable patient, an identifiable reporter, one of our drugs as the suspect, and an adverse event.
- **is it serious?** One of the six 21 CFR 314.80 criteria: death, life-threatening, hospitalisation, disability, congenital anomaly, or medically important.
- **is each event expected,** i.e. listed in the drug's approved label?
- **is it a duplicate** of a case we already hold?
- **which route** follows: a **15-day expedited report** (serious AND unexpected), periodic reporting, follow-up with the reporter, or merging into an existing case.

The model only produces evidence (quotes from the message or the label). Code makes every decision, and a qualified person signs off on every serious case.

## 2. The test data and its limits

**What it is.** The dataset `pv-case-intake` in LangSmith has 107 examples, split into 30 dev and 77 test. They come from three sources:

| source | how it was built | count |
|---|---|---|
| real cases | FDA FAERS reports for six drugs (lisinopril, metformin, warfarin, sertraline, atorvastatin, levothyroxine). FDA removes the reporter's own words, so we generated a realistic intake message (voicemail, email, HCP email, partner report) from each case's real facts. **The facts and the answer are real; only the wording is generated.** | 77 |
| invalid reports | real cases with exactly one required element removed (no identifiable patient / reporter / drug / adverse event) | 15 |
| duplicates and near-misses | a second report of an existing case from a different reporter, and real cases that look similar but are a different event | 10 + 5 |

**How the answer key was made.**
- **Seriousness** comes from the FAERS report itself.
- **Expectedness** comes from a string matcher against the pinned FDA label. Every term the matcher could not settle was decided by a human reviewer; those 107 decisions are recorded with notes in `term_decisions.csv`. Most were drafted with an LLM and then checked by the reviewer.
- **Route and due date** are computed from those two by the same rule the regulation states.
- **Rule changes:** every answer-key rule change, and the dev example that exposed it, is logged in `DEV_LOG.md`.

**How the test set is protected.**
- The split was drawn once, stratified by route and drug, and never redrawn. Cases read while writing prompts were forced into dev.
- All prompt and code changes were made on dev only, and each one is logged. The test set is run once, at the end.

**Limits you should know.**
- **Small.** 77 test examples, 23 of them expedited. One expedited case is about 4 percentage points of recall. Treat differences of one or two cases as noise.
- **Generated wording.** The narratives were written by a Claude model, and a Claude model reads them, so real reports will be messier (typos, missing context, several products, non-English). Our numbers are likely an upper bound on real performance.
- **One reviewer.** Expectedness decisions were made by one person (LLM-assisted). Two references are explicitly disputed, for example 20328474: FAERS doesn't link it to an earlier case, but the system thinks it is a duplicate. We report both readings.
- **Narrow scope.** Six drugs, one label version per drug, US regulation only.
- **Constructed cases** test the logic (the validity gate, duplicate merging) but not the full variety of real incomplete or duplicate reports.

## 3. What we measure offline

Every metric is computed by code against the reference, except one judged metric (follow-up quality) that is itself checked against a human.

### Headline: expedited recall
Of the cases that truly need a 15-day report, how many did the system route as expedited?

**Why this one.** Missing a 15-day case is a regulatory breach: the report goes in late, which leads to inspection findings. Over-routing a periodic case as expedited only costs a reviewer some time, because a human signs off every serious case anyway. So recall is the headline, and precision is reported next to it to show we are not getting recall by flagging everything. We always list the missed cases (false negatives) by ID.

### The full set

| metric | what it checks |
|---|---|
| expedited recall / precision | 15-day routing (duplicates excluded); missed cases listed |
| route correct | the route on every non-duplicate example |
| due date exact | when both the reference and the system say expedited, is the date right (receipt + 15 calendar days)? |
| is_serious accuracy, recall per criterion | death, life-threatening, hospitalisation, medically important |
| case expectedness | expected vs unexpected, on serious valid cases |
| validity, missing elements | the gate, with missing elements compared as sets |
| duplicate precision / recall | over **all** examples: a false merge on any case counts against precision, and merging the wrong case loses the case |
| evidence grounding | share of the model's quotes that appear word-for-word in the message or label |
| trajectory | the system followed the intended path: intake → extraction → validity → (three specialists in parallel → clock) or (follow-up planner). The planner reads what is missing before it drafts. |
| follow-up quality (1–5) | an LLM judge (a stronger model than the system's) scores the drafted follow-up on a rubric: asks exactly what is missing and never re-asks what the report says, asks about outcome only if the event sounds severe, no clinical advice, polite and right for the reporter, no invented facts; for a product issue with no harm, an internal quality referral (not questions to the reporter) is the correct output. The judge is calibrated against human scores on 10 drafts, under the same rubric; we report exact and within-1 agreement, and re-calibrate whenever the rubric changes. |
| cost per case, p50/p95 latency | tokens priced at list rates, and seconds per report |

**Run-to-run variation.** Each system runs three times on the same data, and we report the mean and the spread. A difference smaller than the spread is not a difference.

**Baseline.** We compare against a single "do everything" agent: the same model, the same label and case-store tools, the same output. It computes the route and the due date itself. The comparison shows what the designed structure buys:
- deterministic dates;
- verified quotes;
- specialists that each do one thing;
- a gate the model cannot talk its way past.

## 4. Monitoring in production (documented, not built)

Offline scores say how the system did on our data. In production, the question becomes whether it is still right on today's reports. The signals below come from records the system already writes: the audit log, reviewer corrections and case files.

1. **Reviewer override rate, by determination type.** Every sign-off is either an approval or a correction with a reason code. Track the share of cases a reviewer corrects, separately for seriousness, expectedness, duplicates and extraction, weekly and per drug. A rising override rate on one determination is the earliest sign of drift.
2. **Reason-code distribution.** If `expectedness_wrong` suddenly dominates for one drug, check whether its label changed. Every expectedness call logs the label version (`effective_time`), so a mismatch with the current label is visible.
3. **Reference-free checks on live traffic.** These need no answer key:
   - evidence grounding (does every quote exist?);
   - the follow-up quality judge on every draft;
   - the share of cases flagged `needs_review`;
   - the share of reports routed invalid. A jump here often means a new intake channel or format.
4. **Clock-breach alerting.**
   - For every case routed expedited, alert when days remaining fall to 5, and again at 2, while sign-off is still pending.
   - Alert immediately on any expedited case with no receipt timestamp.
   - The deadline is legal, so this alert goes to a person, not a dashboard.
5. **Sampled QC of auto-committed cases.** Clean non-serious cases commit without review. Sample a fixed percentage for a second-person check, so silent errors in the unreviewed stream are still measured.
6. **Corrections become test cases.**
   - Every reviewer correction is saved in dataset-example format.
   - After a second reviewer confirms it, it is added to a new version of the dataset, as new test examples.
   - It is never added to dev for tuning without a DEV_LOG entry.
   - The next model or prompt change must not regress on them.
7. **Change control.** A new model, prompt or label version is only deployed after re-running the offline suite: dev first, then the held-out test.
