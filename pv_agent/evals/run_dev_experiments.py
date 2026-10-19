"""Dev experiments: V2 (designed graph, eval_mode) vs V1 (single-agent baseline).

    python -m pv_agent.evals.run_dev_experiments                 # both systems, 3 repetitions
    python -m pv_agent.evals.run_dev_experiments --systems v2    # one system
    python -m pv_agent.evals.run_dev_experiments --table-only    # reprint from saved results

DEV SPLIT ONLY: refuses to run if any example is not dev. Writes per-run
outputs to runtime/eval_results/ and the judge calibration sheet (V2 drafts).
"""

import argparse
import json
import random
import statistics
from collections import defaultdict

from langsmith import Client, evaluate

from pv_agent import config
from pv_agent.dataset import DATASET
from pv_agent.evals import evaluators as ev
from pv_agent.evals.common import git_version
from pv_agent.evals.judge import followup_quality, write_calibration

RESULTS = config.RUNTIME / "eval_results"
REPS = 3
SYSTEMS = {"v2": ("v2-designed", "pv_agent.evals.target_v2", "run_v2", 6),
           "v1": ("v1-baseline", "pv_agent.evals.baseline_v1", "run_v1", 4)}


def dev_examples(client):
    examples = list(client.list_examples(dataset_name=DATASET, splits=["dev"]))
    bad = [e.metadata.get("example_key") for e in examples if (e.metadata.get("dataset_split") or [None])[0] != "dev"]
    if bad or not examples:
        raise SystemExit(f"refusing to run: non-dev examples {bad}")
    return examples


def run_system(client, system, examples, version):
    prefix, module, fn, concurrency = SYSTEMS[system]
    target = getattr(__import__(module, fromlist=[fn]), fn)
    results = evaluate(
        target,
        data=examples,
        evaluators=ev.PER_EXAMPLE + [followup_quality],
        summary_evaluators=ev.SUMMARY,
        experiment_prefix=f"{prefix}-{version}",
        description=f"{prefix} on dev, {REPS} repetitions, model {config.MODEL}, commit {version}",
        metadata={"system": system, "git": version, "model": config.MODEL, "judge_model": config.JUDGE_MODEL,
                  "split": "dev", "repetitions": REPS},
        num_repetitions=REPS,
        max_concurrency=concurrency,
        client=client,
    )
    rows = []
    for r in results:
        ex, run = r["example"], r["run"]
        judge = next((x for x in r["evaluation_results"]["results"] if x.key == "followup_quality"), None)
        rows.append({"example_id": str(ex.id), "key": ex.metadata["example_key"], "inputs": ex.inputs,
                     "reference": ex.outputs, "outputs": run.outputs or {}, "start": str(run.start_time),
                     "error": run.error,
                     "judge": ({"score": judge.score, "detail": json.loads(judge.comment)} if judge and judge.score is not None else None)})
    # repetition index = order of a given example's runs
    seen = defaultdict(int)
    for row in sorted(rows, key=lambda x: x["start"]):
        row["repetition"] = seen[row["example_id"]]
        seen[row["example_id"]] += 1
    saved = {"experiment": results.experiment_name, "system": system, "version": version, "rows": rows}
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / f"{system}.json").write_text(json.dumps(saved, indent=1, default=str))
    return saved


def per_rep_metrics(saved):
    """Metrics per COMPLETE repetition. A repetition with any failed run is
    dropped (and reported), never scored on a subset."""
    by_rep, failed = defaultdict(list), defaultdict(int)
    for row in saved["rows"]:
        if row["error"]:
            failed[row["repetition"]] += 1
        else:
            by_rep[row["repetition"]].append((row["key"], row["inputs"], row["outputs"], row["reference"]))
    complete = {rep: ev.compute_metrics(rows) for rep, rows in sorted(by_rep.items()) if not failed.get(rep)}
    return complete, {rep: n for rep, n in failed.items() if n}


def fmt(values):
    vals = [v for v in values if v is not None]
    if not vals:
        return "n/a"
    m = statistics.mean(vals)
    spread = max(vals) - min(vals)
    if all(abs(v) <= 1 for v in vals):
        return f"{m:.2f} ±{spread / 2:.2f}"
    return f"{m:.3f} ±{spread / 2:.3f}"


def print_table(saved_by_system):
    computed = {s: per_rep_metrics(saved) for s, saved in saved_by_system.items()}
    metrics = {s: c[0] for s, c in computed.items()}
    systems = list(saved_by_system)
    for s in systems:
        if computed[s][1]:
            print(f"{s}: repetitions dropped for failed runs {computed[s][1]} (rep: n failed)")
    names = list(next(m for m in metrics.values() if m)[next(iter(next(m for m in metrics.values() if m)))][0].keys())
    print(f"\n{'metric (mean ±half-range over complete runs)':48}" + "".join(f"{s + ' (n=' + str(len(metrics[s])) + ')':>18}" for s in systems))
    for name in names:
        cells = [fmt([m[name] for m, _ in metrics[s].values()]) for s in systems]
        print(f"{name:48}" + "".join(f"{c:>18}" for c in cells))
    for s in systems:
        for rep, (_, e) in metrics[s].items():
            print(f"  {s} rep {rep}: expedited TP={e['tp']} FN={e['fn']} FP={e['fp']} TN={e['tn']}  "
                  f"FN={e['fn_cases']}  FP={e['fp_cases']}")
        judged = [r["judge"]["score"] for r in saved_by_system[s]["rows"] if r.get("judge")]
        if judged:
            print(f"  {s} follow-up quality (judge, 1-5): mean {statistics.mean(judged):.2f} over {len(judged)} drafts")
        errors = [r["key"] for r in saved_by_system[s]["rows"] if r["error"]]
        if errors:
            print(f"  {s} run errors: {errors}")


def calibration_sheet(saved_v2, n=10):
    """10 V2 follow-up drafts from dev invalid cases: distinct cases first."""
    drafts = [r for r in saved_v2["rows"] if r["outputs"].get("followup_draft") and r.get("judge")]
    rng = random.Random(20261019)
    rng.shuffle(drafts)
    chosen, keys = [], set()
    for r in drafts:
        if r["key"] not in keys:
            chosen.append(r)
            keys.add(r["key"])
    chosen += [r for r in drafts if r not in chosen][: max(0, n - len(chosen))]
    chosen = chosen[:n]
    rows = [{
        "draft_id": f"D{i + 1:02d}", "example_key": r["key"], "repetition": r["repetition"],
        "missing": sorted(r["reference"].get("missing_element") or r["outputs"].get("missing_elements") or []),
        "report": r["inputs"]["narrative"], "channel": r["outputs"]["followup_draft"]["channel"],
        "message": r["outputs"]["followup_draft"]["message"], "judge": {"score": r["judge"]["score"], **r["judge"]["detail"]},
    } for i, r in enumerate(chosen)]
    return rows if write_calibration(rows) else []


def compare_link(client, saved_by_system):
    dataset = client.read_dataset(dataset_name=DATASET)
    ids = [str(client.read_project(project_name=s["experiment"]).id) for s in saved_by_system.values()]
    return f"{dataset.url}/compare?selectedSessions={','.join(ids)}"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--systems", default="v2,v1")
    parser.add_argument("--table-only", action="store_true")
    args = parser.parse_args()
    systems = [s.strip() for s in args.systems.split(",")]

    client = Client()
    if args.table_only:
        saved = {s: json.loads((RESULTS / f"{s}.json").read_text()) for s in systems}
    else:
        examples = dev_examples(client)
        version = git_version()
        print(f"dev examples: {len(examples)}; version {version}; {REPS} repetitions")
        saved = {s: run_system(client, s, examples, version) for s in systems}

    for s in saved.values():
        print(f"experiment {s['system']}: {s['experiment']}")
    print_table(saved)
    if "v2" in saved:
        sheet = calibration_sheet(saved["v2"])
        if sheet:
            print(f"\ncalibration sheet: {len(sheet)} drafts -> AE_Data/data/judge_calibration.csv (judge scores kept separately)")
    if len(saved) > 1:
        print(f"\ncomparison view: {compare_link(client, saved)}")


if __name__ == "__main__":
    main()
