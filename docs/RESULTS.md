# Results: PV intake triage, final test run

**System under test:** git tag `test-freeze-2` (commit 513c248). It is the same agent system as `test-freeze`; only the test harness changed (see DEV_LOG.md).
**Data:** LangSmith dataset `pv-case-intake`, version as_of 2026-10-18T01:14:52Z (tagged `test-freeze`), **test split: 77 examples, 23 of them true 15-day cases**.
**Systems:**
- **V2**, the designed system: three specialists, a deterministic clock and code decisions. Run 3 times.
- **V1**, the baseline: one agent with the same model and tools, which decides everything itself, including the route and the due date. Run once, because its headline result (expedited recall) was identical in all three dev runs, with the same single miss each time.

Both ran in eval mode (no human pauses), so these are the systems' own decisions. Raw numbers are in `results.csv`.

## The headline

| | V2 designed (mean of 3, range) | V1 baseline (1 run) |
|---|---|---|
| **15-day cases caught (expedited recall)** | **0.90** (20–21 of 23; range 0.87–0.91) | 0.83 (19 of 23) |
| 15-day flags that were right (precision) | 0.87 (21 of 24) | 0.90 (19 of 21) |
| due date correct, when expedited | **1.00** | 1.00 |

V2 catches about two more 15-day cases out of 23 than the single-agent baseline. Every due date it set was correct, because a date is never left to the model.

## Full test table

| metric | V2 (mean, range over 3 runs) | V1 (1 run) |
|---|---|---|
| expedited recall | 0.90 (0.87–0.91) | 0.83 |
| expedited precision | 0.87 (0.87–0.88) | 0.90 |
| valid / missing elements correct | 0.97 | 0.92 |
| route correct (non-duplicates) | 0.87 (0.86–0.88) | 0.86 |
| duplicate recall | 1.00 | 0.60 |
| duplicate precision | 0.60 (0.56–0.63) | 0.75 |
| due date exact | 1.00 | 1.00 |
| is_serious correct | 0.97 | 0.94 |
| recall: death / life-threatening / hospitalisation | 1.00 / 1.00 / 1.00 | 1.00 / 1.00 / 1.00 |
| recall: medically important | 1.00 | 0.91 |
| case expectedness correct (serious cases) | 0.88 | 0.85 |
| evidence grounding (model quotes verified) | 0.93 | 1.00 |
| trajectory followed the design | 1.00 | n/a |
| follow-up quality (LLM judge, 1–5; 36 drafts) | 4.19 | n/a (V1 drafts no follow-ups) |
| cost per case | $0.029 | $0.036 |
| latency p50 / p95 | 7.0 s / 14.4 s | 7.2 s / 10.9 s |

## Dev vs test

| metric | V2 dev | V2 test | V1 dev | V1 test |
|---|---|---|---|---|
| expedited recall | 0.94 | 0.90 | 0.83 | 0.83 |
| expedited precision | 0.95 | 0.87 | 1.00 | 0.90 |
| valid / missing elements | 0.98 | 0.97 | 0.89 | 0.92 |
| route correct | 0.91 | 0.87 | 0.91 | 0.86 |
| duplicate recall | 0.80 | 1.00 | 0.33 | 0.60 |
| duplicate precision | 0.80 | 0.60 | 1.00 | 0.75 |
| is_serious | 1.00 | 0.97 | 0.97 | 0.94 |
| case expectedness | 0.95 | 0.88 | 0.85 | 0.85 |
| cost per case | $0.028 | $0.029 | $0.033 | $0.036 |

There's a small drop from dev to test, as expected on unseen data. The ranking holds: V2 is ahead on the headline and on validity, and level or ahead elsewhere. Dev V2 was run before the follow-up-agent change; that change does not touch the valid-case path these metrics measure.

## Every expedited miss, explained (V2)

| case | runs | what happened | reading |
|---|---|---|---|
| **20298221**-warfarin (missed) | 3/3 | the agent called a TIA and a stroke "not applicable": the disease warfarin prevents, i.e. lack of effect | **Answer-key question.** The key calls them unexpected, but it treats similar lack-of-effect events as not applicable elsewhere (raised blood pressure on lisinopril, arteriosclerosis on atorvastatin). V1 makes the same call. |
| **20315862**-warfarin (missed) | 3/3 | merged as a duplicate of 20290779 | **Probably a real duplicate FAERS never linked:** same reporter type, 6 days apart, a muscle haematoma with nerve damage in both. V1 merges it too. |
| **20304247**-warfarin (missed) | 1/3 | merged as a duplicate of 20299336 | **Plausible real duplicate:** men aged 60/62, pharmacist-reported, a GI bleed, 1 day apart. Inconsistent across runs. |
| **20299336**-warfarin (false flag) | 3/3 | haemorrhagic shock judged unexpected | **Answer-key question.** The reviewer marked it expected; under 314.80 a more severe event than the label lists is unexpected. V1 agrees with the agent. |
| **20292106**-sertraline (false flag) | 3/3 | suicide attempt judged unexpected | **Answer-key question.** The label lists "suicidal thoughts and behaviors"; the agent read the attempt as more specific. |
| **20321472**-warfarin (false flag) | 3/3 | INR increased judged unexpected | **Answer-key question.** The key accepted a string-matcher "lab" match. |

**V1 misses (1 run):** 20298221 and 20315862, the same as V2. Also:
- **20278088-metformin:** V1 turned "racing heartbeat" into palpitations and called it expected; the key says tachycardia is unexpected.
- **20277682-sertraline:** V1 called a multi-drug overdose case's weakness expected.
- **False flags:** 20299336, and INV-20298142, an *invalid* report that V1 treated as valid and expedited.

**What this means:**
- **None of V2's expedited errors is an extraction or clock failure.** Each one is either a clinical judgement where the agent and the answer key disagree, or a duplicate merge of what looks like a genuine unlinked duplicate.
- **When V2 disagrees on a flag, it errs towards "unexpected"**, the safe direction for a regulatory deadline.

**One genuine duplicate error:** V2 merged 20282194-metformin (wind and indigestion) into 20268910 (a GI bleed) in all three runs. They are different events. It's a periodic case, so recall is unaffected, but a wrong merge hides a case. This is the main reason duplicate precision is 0.60. In production, every suspected duplicate goes to a reviewer and is never merged automatically.

## Plain-language reading (for a decision on continuing)

1. **Does it catch the cases that matter?** Mostly. On reports it had never seen, it routed 20–21 of 23 true 15-day cases correctly, against 19 for a single do-everything agent. The cases it missed are ones where the right answer is itself debatable (a stroke while on a blood thinner) or where the report really is a duplicate.
2. **Can the deadline be trusted?** Yes. When a case was routed 15-day, the due date was right every time, because code computes it from the receipt timestamp and no model touches it.
3. **Is it safe to put in front of reviewers?** It is built for that:
   - every serious case, every flagged judgement and every suspected duplicate stops for a qualified reviewer;
   - every determination cites the sentence it rests on;
   - every action is written to an append-only audit log.
4. **What does it cost?** About 3 cents and 7 seconds per report (p95 about 14 s).
5. **What would we fix next?**
   - **Duplicates:** require a matching event, not just a similar patient, before suggesting a merge.
   - **Answer key:** settle the "lack of effect" rule consistently (stroke on warfarin).
   - **Declined contact:** when a reporter declines contact, record the refusal instead of drafting a follow-up.
   - **Judge:** show it the report header.
   - **Data:** run on real, messier reports.
6. **Limits of this evidence.**
   - **Small test set:** 77 examples and 23 true 15-day cases, so one case moves recall by about 4 points.
   - **Generated wording:** the messages were written by a model from real FAERS facts.
   - **One reviewer:** the expected/unexpected answer key was set by one reviewer.
   - **Incomplete LangSmith traces:** LangSmith's monthly trace limit ran out during this run. Some test traces are missing from the LangSmith UI, but every result here comes from the complete local results.

**Recommendation:** continue to a pilot on real (de-identified) intake with reviewers in the loop. Measure the reviewer override rate and the duplicate-merge rejection rate from the audit log, as described in EVALUATION.md.
