# Friction log

Rough edges hit while building this project, written as product feedback. Every entry is backed by evidence in DEV_LOG.md, CLAUDE.md, the git history, the saved run results or the code. **Deep Agents was not used in this project, so it has no entries.**

**Biggest frictions:** (1) a credit outage spoiled a LangSmith experiment, (4) changing a judge's rubric silently broke its calibration, (6) interrupt() re-runs a node on resume, so side effects had to move to a commit node.

## LangSmith

**1. A credit outage spoiled an experiment**
- *What happened:* in the V1 dev experiment, the third repetition failed on an Anthropic credit-balance error and had to be excluded (CLAUDE.md, f141a23). V1 was then re-run as a new, clean experiment, `v1-baseline-f141a23-0d05d78b` (CLAUDE.md, b607c8d).
- *Workaround:* evaluators return n/a on failed runs; the local table drops incomplete repetitions; test runs stop all API calls on the first error.
- *Suggestion:* an experiment-level "abort after N errors" option, a failed-run count in the summary header, and a way to mark an experiment superseded.

**2. `evaluate()` rejects a wrapped target**
- *What happened:* the first test run (tag `test-freeze`) failed at start-up with 0 runs and 0 API calls. My stop-on-error wrapper, `wrapped(*args, **kwargs)`, hid the target's signature, which LangSmith rejects (DEV_LOG, 513c248).
- *Workaround:* `functools.wraps`, then a re-freeze as `test-freeze-2` (DEV_LOG).
- *Suggestion:* accept `*args`, or say in the error that the check inspects the signature and that `functools.wraps` fixes it.

**3. The trace quota ran out mid-run**
- *What happened:* LangSmith's monthly trace limit was exceeded during the final test run of 308 runs; 91 trace uploads were rejected, while the runs themselves completed locally (DEV_LOG, cee5387).
- *Result:* the test experiments in the UI are missing traces; the numbers come from local results.
- *Suggestion:* a pre-flight estimate of the traces `evaluate()` will create against the remaining quota, and one summary of rejected uploads at the end of the run.

**4. Changing a judge's rubric silently breaks its calibration**
- *What happened:* one added rubric line changed the judge's agreement with human scores from 9/10 exact to 2/10 on the same drafts. After the human re-scored under the new rubric, it was 8/10.
- *Workaround:* the calibration set and its scores are versioned with the rubric, and the judge is re-run on every rubric change.
- *Suggestion:* link an LLM-as-judge evaluator to a calibration dataset, and flag "rubric changed since last calibration".

## Environment

**5. Anaconda's Brotli breaks the Anthropic SDK with a misleading error**
- *What happened:* Anaconda's Brotli 1.0.9 broke the Anthropic SDK's response decoding, and the failure surfaced as "Connection error" (CLAUDE.md, Conventions; 794faad).
- *Workaround:* send `Accept-Encoding: gzip`. The real fix is `pip install -U brotli`.
- *Suggestion:* the SDK could surface the decoder error instead of wrapping it as a connection error.

## Designed around (limitations I built workarounds for)

No failure was recorded for these; each is a limitation I had to design around, and the workaround in the repo is the evidence.

### LangGraph

**6. `interrupt()` re-runs the node on resume**
- *Limitation:* a node that pauses on `interrupt()` runs again from its first line when resumed, so side effects inside it can repeat.
- *Workaround:* nodes only collect audit events in state, and a single final `commit` node writes the case record and audit log (`pv_agent/nodes/review.py`; the design reason is recorded in CLAUDE.md).
- *Suggestion:* document this commit-node pattern in the interrupt docs.

**7. An interrupt's resume value has no schema**
- *Limitation:* `Command(resume=...)` accepts any value, so the expected shape has to be communicated and checked by hand.
- *Workaround:* every interrupt payload carries a `how_to_respond` block, and the node validates the response and re-interrupts with `errors_in_your_last_response` (`pv_agent/nodes/review.py`, `pv_agent/nodes/followup.py`).
- *Suggestion:* an optional resume schema on `interrupt()`, validated by the runtime and rendered as a form in Studio.

**8. Studio's input form is built from the full state schema**
- *Limitation:* because the graph is compiled as `StateGraph(CaseState)` without a separate input schema, Studio's input is the whole state rather than the two input fields (header and narrative).
- *Workaround:* `pv_agent/export_input.py` prints the two-field input for a dev example, and the README gives a sample input.
- *Suggestion:* in Studio, highlight the fields that no node writes, and mention `input_schema` in the Studio quickstart.

### LangSmith

**9. The node path isn't easily readable inside evaluators**
- *Limitation:* the evaluators score the target's outputs, so checking the path a run took needs the path in those outputs.
- *Workaround:* every node is wrapped by `on_path` to append its name to a `trajectory` state field, which the trajectory evaluator reads (`pv_agent/graph.py`, `pv_agent/evals/evaluators.py`).
- *Suggestion:* pass the run's node sequence to evaluators, or offer an opt-in "record node path" flag on `compile()`.

**10. No built-in sync from local files to a LangSmith dataset**
- *Limitation:* keeping local files as the source of truth and re-uploading after each answer-key change needs custom code.
- *Workaround:* `AE_Data/upload_dataset.py` assigns deterministic example ids (uuid5 of the case key), creates, updates or deletes only what changed, and tags the new version with the git commit.
- *Suggestion:* a `client.sync_dataset(examples, key=...)` that returns created/updated/deleted counts and the new version.

**11. Repetitions have no index in `evaluate()` results**
- *Limitation:* with `num_repetitions`, the results don't say which repetition a run belongs to.
- *Workaround:* the repetition is inferred from each example's runs in start-time order (`pv_agent/evals/run_dev_experiments.py`).
- *Suggestion:* expose `repetition` on each result row.
