# Friction log

Rough edges hit while building this project, written as product feedback. Every entry happened here; the evidence is in DEV_LOG.md, the git history or the code. **Deep Agents was not used in this project, so it has no entries.**

## LangGraph

**1. Resuming after `interrupt()` re-runs the node from the start**
- *Trying to:* write an audit-log line when a reviewer approves or corrects a case.
- *Expected:* code after the interrupt to run once, on resume.
- *What happens:* the node re-executes from its first line on every resume. Any side effect placed before the interrupt, or in a node that interrupts more than once (we re-interrupt on an invalid reviewer response), would repeat.
- *Workaround:* nodes only collect audit events in state (an `operator.add` list). A single final `commit` node writes the files once per case (`pv_agent/nodes/review.py`).
- *Suggestion:* a "side effects after interrupt" section in the interrupt docs, with this commit-node pattern, or a lint warning when a node both calls `interrupt()` and does I/O.

**2. An interrupt carries no schema for its resume value**
- *Trying to:* let a reviewer resume from Studio or a script with `approve`, or `correct` plus a reason code.
- *Expected:* a way to declare the shape `Command(resume=...)` must have.
- *What happens:* the resume value is untyped, so the reviewer has to guess the JSON shape, and a malformed response reaches the node.
- *Workaround:* every interrupt payload includes a `how_to_respond` block with example JSON, and the node validates the response and re-interrupts with `errors_in_your_last_response`.
- *Suggestion:* an optional resume schema on `interrupt()`, validated by the runtime and rendered as a form in Studio.

**3. Studio's input form is built from the full state schema**
- *Trying to:* submit a report (header + narrative) in Studio.
- *What happens:* we compile `StateGraph(CaseState)` with no separate input schema, so the input is the whole state: around 27 fields that nodes write, not the 2 a user provides.
- *Workaround:* `pv_agent/export_input.py` prints the 2-field input, and the README gives a sample.
- *Suggestion:* in Studio, pre-fill or highlight the fields that have no writer node, and mention `input_schema` in the Studio quickstart.

**4. The evaluation needs the node path, which isn't in the state**
- *Trying to:* score whether each run followed the designed path (intake → … → specialists in parallel → clock).
- *What happens:* the path is in the LangSmith trace, but `evaluate()` evaluators see only the target's outputs.
- *Workaround:* every node is wrapped (`on_path` in `graph.py`) to append its name to a `trajectory` state field.
- *Suggestion:* an opt-in "record node path" flag on `compile()`, or pass the node sequence to LangSmith evaluators.

**5. Drawing the graph needs an undeclared extra**
- *What happened:* `get_graph().draw_ascii()` raised `ImportError: Install grandalf`.
- *Suggestion:* a `langgraph[draw]` extra, or fall back to Mermaid text when `grandalf` is missing.

## LangChain

**6. The default structured-output method doesn't work with the newest Claude models**
- *Trying to:* get typed outputs from `claude-sonnet-5-5`.
- *What happens:* `with_structured_output()` defaults to `method="function_calling"`, which forces a tool choice, and Sonnet 5.5 rejects forced tool choice. We checked the source before the first call, so this was a design constraint rather than a failure.
- *Workaround:* `method="json_schema"` on every structured call, and `response_format=ProviderStrategy(...)` for the `create_agent` baseline.
- *Suggestion:* pick the default per model capability, or raise a clear error naming the alternative method.

## LangSmith

**7. A credit outage silently spoiled an experiment**
- *What happened:* in the V1 dev experiment, 23 of 90 runs (almost all of one repetition) failed with "credit balance too low".
- *Then:* my evaluators raised `KeyError` on the empty outputs, the summary evaluators errored, and the experiment's UI summary mixed 67 good runs with 23 failures. We had to re-run as a new experiment, and the spoiled one still sits next to it.
- *Workaround:* evaluators return n/a on failed runs; the local table drops incomplete repetitions; test runs stop all API calls on the first error.
- *Suggestion:* an experiment-level "abort after N errors" option, a failed-run count in the summary header, and a way to mark an experiment superseded.

**8. `evaluate()` rejects a wrapped target**
- *What happened:* the first test run failed at start-up, with 0 runs, because of my stop-on-error wrapper `wrapped(*args, **kwargs)`: "Target function must accept at least one positional argument (inputs)".
- *Workaround:* `functools.wraps`, then a re-freeze as `test-freeze-2` (DEV_LOG).
- *Suggestion:* accept `*args`, or say in the error that the check inspects the signature and that `functools.wraps` fixes it.

**9. Hitting the trace quota mid-run gives no early warning**
- *What happened:* during the final test run (308 runs), uploads hit "Monthly unique traces usage limit exceeded". 91 traces were rejected with HTTP 429, while the runs themselves completed locally.
- *Result:* the test experiments in the UI are missing traces; the numbers come from local results.
- *Suggestion:* a pre-flight estimate of the traces `evaluate()` will create against the remaining quota, and one clear warning instead of 91 repeated errors.

**10. Tracing turned on with no API key fails on every call**
- *What happened:* with `LANGSMITH_TRACING=true` and an empty `LANGSMITH_API_KEY`, every call logged a 401.
- *Workaround:* our scripts detect this once and switch tracing off with one warning.
- *Suggestion:* the SDK could do the same.

**11. No built-in "sync this local dataset"**
- *Trying to:* keep local files as the source of truth and re-upload after every answer-key change.
- *What happens:* there's no upsert.
- *Workaround:* `AE_Data/upload_dataset.py` (about 60 lines) does it:
  - assigns deterministic example ids (uuid5 of the case key);
  - diffs against the existing examples;
  - creates, updates or deletes only what changed;
  - tags the version with the git commit.
- *Rough edges:* adding one metadata field updated all 107 examples (a new version for no content change), and tagging needs `list_dataset_versions` plus `update_dataset_tag`.
- *Suggestion:* `client.sync_dataset(examples, key=...)` returning created/updated/deleted counts and the new version.

**12. Repetitions have no index**
- *What happens:* with `num_repetitions=3`, results don't say which repetition a run belongs to.
- *Workaround:* we inferred it from start-time order per example.
- *Suggestion:* expose `repetition` on each result row.

**13. Changing a judge's rubric silently breaks its calibration**
- *What happened:* one added rubric line changed the judge's agreement with human scores from 9/10 exact to 2/10 on the same drafts. After the human re-scored under the new rubric, it was 8/10.
- *Workaround:* the calibration set and its scores are versioned with the rubric, and the judge is re-run on every rubric change.
- *Suggestion:* link an LLM-as-judge evaluator to a calibration dataset, and flag "rubric changed since last calibration".

## Environment

**14. Anaconda's Brotli breaks the Anthropic SDK with a misleading error**
- *What happened:* every response failed with "Connection error". The real cause was `TypeError: process() takes no keyword arguments` in the `httpx2` Brotli decoder (Brotli 1.0.9).
- *Workaround:* send `Accept-Encoding: gzip`. The real fix is `pip install -U brotli`.
- *Suggestion:* the SDK could surface the decoder error instead of wrapping it as a connection error.

**15. Running a script outside the package**
- *What happened:* a one-off script run as `python /path/script.py` failed with `ModuleNotFoundError: pv_agent`.
- *Workaround:* every project script is run as `python -m pv_agent....`; the one-off used `PYTHONPATH`.

**16. Installing the LangGraph CLI changed shared dependencies**
- *What happened:* `pip install "langgraph-cli[inmem]"` upgraded `protobuf` and `cryptography`, which pip reported as conflicting with `streamlit` and `pyopenssl` in the base Anaconda environment.
- *Suggestion:* recommend a virtualenv in the CLI install docs.
