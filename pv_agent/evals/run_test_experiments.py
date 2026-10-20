"""FINAL test-split run. Runs once, on the frozen system.

    python -m pv_agent.evals.run_test_experiments            # V2 x3, V1 x1, judge, table
    python -m pv_agent.evals.run_test_experiments --table-only

Refuses to run unless the working tree is clean and HEAD carries the
`test-freeze` tag. Experiment names carry "test" and the tag. On the first
credit/API error every later call stops WITHOUT contacting the API, and the
number of completed runs is reported. Writes runtime/eval_results/test_*.json
and docs/results.csv.
"""

import argparse
import csv
import functools
import json
import subprocess
import threading

from langsmith import Client

from pv_agent import config
from pv_agent.dataset import DATASET
from pv_agent.evals import judge as judge_mod
from pv_agent.evals import run_dev_experiments as dev
from pv_agent.evals.evaluators import EXP, failed

TAG = "test-freeze-2"  # test-freeze (782ff94) failed before any API call: wrapper hid the target signature
RUNS = {"v2": 3, "v1": 1}
STOP = {"error": None, "completed": 0}
LOCK = threading.Lock()


def git(*args):
    return subprocess.check_output(["git", *args], cwd=config.REPO, text=True).strip()


def check_frozen():
    if git("status", "--porcelain", "--untracked-files=no"):
        raise SystemExit("refusing: working tree has uncommitted changes")
    if TAG not in git("tag", "--points-at", "HEAD").split():
        raise SystemExit(f"refusing: HEAD is not tagged {TAG}")
    return f"{TAG}-{git('rev-parse', '--short', 'HEAD')}"


def stop_on_api_error(fn):
    @functools.wraps(fn)  # keep the signature: LangSmith requires a named `inputs` parameter
    def wrapped(*args, **kwargs):
        if STOP["error"]:
            raise RuntimeError(f"aborted, no API call: earlier error {STOP['error']}")
        try:
            out = fn(*args, **kwargs)
        except Exception as e:
            msg = str(e)
            if "credit balance" in msg or "Error code:" in msg or type(e).__module__.startswith(("anthropic", "langchain_anthropic")):
                with LOCK:
                    STOP["error"] = STOP["error"] or msg[:200]
            raise
        if fn.__name__ in ("run_v1", "run_v2"):
            with LOCK:
                STOP["completed"] += 1
        return out
    return wrapped


def test_examples(client):
    examples = list(client.list_examples(dataset_name=DATASET, splits=["test"]))
    bad = [e.metadata.get("example_key") for e in examples if (e.metadata.get("dataset_split") or [None])[0] != "test"]
    if bad or not examples:
        raise SystemExit(f"refusing: non-test examples {bad}")
    return examples


def dataset_version(client):
    v = next(client.list_dataset_versions(dataset_name=DATASET, limit=1))
    return {"as_of": v.as_of.isoformat(), "tags": v.tags}


def cause(o, r):
    """One line on why an expedited call differs from the reference."""
    if failed(o):
        return "run failed"
    if o["valid"] != r["valid"]:
        return f"validity: agent valid={o['valid']} {o['missing_elements']}, ref valid={r['valid']}"
    if o.get("duplicate_of") and not r.get("duplicate_of"):
        return f"false merge with {o['duplicate_of']}"
    if o.get("is_serious") != r.get("is_serious"):
        got = [k for k, v in (o.get("seriousness_criteria") or {}).items() if v["met"]]
        want = [k for k, v in (r.get("seriousness_criteria") or {}).items() if v]
        return f"seriousness: agent {got or 'not serious'}, ref {want or 'not serious'}"
    if o.get("case_expectedness") != r.get("case_expectedness"):
        got = [f"{x['reaction']}={x['expectedness']}" for x in o.get("reactions") or []]
        want = [f"{x['term']}={x['expectedness']}" for x in r.get("reaction_expectedness") or []]
        return f"expectedness: agent {got}; ref {want}"
    return "other"


def misses(saved):
    out = []
    for row in sorted(saved["rows"], key=lambda x: (x["repetition"], x["key"])):
        o, r = row["outputs"], row["reference"]
        if r.get("duplicate_of"):
            continue
        ref_e, got_e = r["reporting_route"] == EXP, (o or {}).get("route") == EXP
        if ref_e != got_e:
            out.append((row["repetition"], "FN" if ref_e else "FP", row["key"], cause(o, r)))
    return out


def export_csv(dev_saved, test_saved, path):
    rows = []
    for split, saved_by_system in (("dev", dev_saved), ("test", test_saved)):
        for system, saved in saved_by_system.items():
            metrics, dropped = dev.per_rep_metrics(saved)
            names = next(iter(metrics.values()))[0].keys() if metrics else []
            for name in names:
                vals = [m[name] for m, _ in metrics.values() if m[name] is not None]
                rows.append({"split": split, "system": system, "metric": name, "n_runs": len(vals),
                             "mean": sum(vals) / len(vals) if vals else "", "min": min(vals) if vals else "",
                             "max": max(vals) if vals else ""})
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["split", "system", "metric", "n_runs", "mean", "min", "max"])
        w.writeheader()
        w.writerows(rows)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--table-only", action="store_true")
    args = parser.parse_args()
    client = Client()
    path = {s: dev.RESULTS / f"test_{s}.json" for s in RUNS}

    if not args.table_only:
        version = check_frozen()
        examples = test_examples(client)
        ds = dataset_version(client)
        print(f"TEST examples: {len(examples)}; system {version}; dataset version {ds}", flush=True)
        # stop-on-error guards around every API-calling function used by the run
        import pv_agent.evals.baseline_v1 as v1
        import pv_agent.evals.target_v2 as v2
        v1.run_v1, v2.run_v2 = stop_on_api_error(v1.run_v1), stop_on_api_error(v2.run_v2)
        judge_mod.judge_followup = stop_on_api_error(judge_mod.judge_followup)

        for system in ("v2", "v1"):
            if STOP["error"]:
                print(f"skipping {system}: stopped on API error")
                break
            dev.REPS = RUNS[system]
            prefix = dev.SYSTEMS[system][0]
            dev.SYSTEMS[system] = (f"{prefix}-test", *dev.SYSTEMS[system][1:])
            saved = dev.run_system(client, system, examples, version, out_name=f"test_{system}")  # dev files untouched
            saved["dataset_version"] = ds
            path[system].write_text(json.dumps(saved, indent=1, default=str))
            print(f"{system}: {saved['experiment']}, completed so far {STOP['completed']}", flush=True)
        if STOP["error"]:
            print(f"\nSTOPPED ON API ERROR after {STOP['completed']} completed runs: {STOP['error']}")

    test_saved = {s: json.loads(p.read_text()) for s, p in path.items() if p.exists()}
    dev_saved = {s: json.loads((dev.RESULTS / f"{s}.json").read_text()) for s in RUNS if (dev.RESULTS / f"{s}.json").exists()}
    dev.REPS = 3
    print(f"\n=== TEST (dataset version {next(iter(test_saved.values())).get('dataset_version')}) ===")
    dev.print_table(test_saved)
    for s, saved in test_saved.items():
        print(f"\n{s} missed (FN) and false (FP) expedited, per run:")
        for rep, kind, key, why in misses(saved) or [(None, "-", "none", "")]:
            print(f"  run {rep} {kind} {key:28} {why}")
    export_csv(dev_saved, test_saved, config.REPO / "docs" / "results.csv")
    print("\nwrote docs/results.csv")
    if len(test_saved) > 1:
        print(f"comparison view: {dev.compare_link(client, test_saved)}")


if __name__ == "__main__":
    main()
