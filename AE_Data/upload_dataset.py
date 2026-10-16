#!/usr/bin/env python3
"""
Sync the eval dataset to LangSmith from local files.

Local files are the source of truth; never edit the dataset in the UI. Each
example has a deterministic id (uuid5 of its key), so a re-run updates the
same dataset in place -- new examples created, changed ones updated, removed
ones deleted -- which LangSmith records as a new dataset version. Unchanged
examples are left alone, so a no-op re-run makes no version. The new version
is tagged with the git commit it was built from.

    python upload_dataset.py

Reads, under data/:
    narratives.jsonl          77 real cases (inputs)
    cases_labeled.json        their answer keys
    split.json                their dev/test split
    constructed_cases.jsonl   invalid / duplicate / near_miss cases, with answer keys and splits

Records still marked needs_review are NOT uploaded: unreviewed text is not ground truth.
"""

import json
import os
import subprocess
import uuid
from collections import Counter
from pathlib import Path

from dotenv import load_dotenv
from langsmith import Client

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
load_dotenv(ROOT.parent / ".env")

DATASET = "pv-case-intake"
DESCRIPTION = (
    "PV adverse-event intake triage. Inputs: intake header + narrative (synthesised wording, "
    "real FAERS facts). Reference outputs: validity, seriousness, per-reaction and case "
    "expectedness, reporting route, due date, duplicate_of. Built by AE_Data/upload_dataset.py; "
    "do not edit in the UI."
)
ID_NAMESPACE = uuid.UUID("6f1c2a4e-9d3b-4c1e-8a57-2b0f3e9d7c11")  # fixed: ids stay stable across runs


def example_id(key):
    return str(uuid.uuid5(ID_NAMESPACE, key))


def real_examples():
    labeled = {(c["safety_report_id"], c["target_drug"]): c for c in json.loads((DATA / "cases_labeled.json").read_text())}
    split = json.loads((DATA / "split.json").read_text())
    splits = {tuple(k): s for s in ("dev", "test") for k in split[s]}

    out = []
    for r in map(json.loads, (DATA / "narratives.jsonl").open()):
        key = (r["safety_report_id"], r["target_drug"])
        case = labeled[key]
        out.append({
            "key": f"{key[0]}-{key[1]}",
            "needs_review": r.get("needs_review", False),
            "split": splits[key],
            "inputs": {"header": r["header"], "narrative": r["narrative"]},
            "outputs": {
                "valid": True,
                "missing_element": None,
                "is_serious": case["is_serious"],
                "seriousness_criteria": case["seriousness_criteria"],
                "reaction_expectedness": [
                    {"term": x["term"], "expectedness": x["expectedness"]} for x in case["reaction_expectedness"]
                ],
                "case_expectedness": case["expectedness"],
                "reporting_route": case["reporting_route"],
                "due_date": case["due_date"],
                "duplicate_of": None,
            },
            "metadata": {
                "safety_report_id": key[0],
                "target_drug": key[1],
                "source_type": r["source_type"],
                "constructed": "none",
                "prompt_version": r["prompt_version"],
                "reviewed_by": r.get("reviewed_by", "automated_checks"),
                "manual_edit": r.get("manual_edit", False),
                "label_effective_time": case["label_effective_time"],
            },
        })
    return out


def constructed_examples():
    path = DATA / "constructed_cases.jsonl"
    if not path.exists():
        return []
    out = []
    for r in map(json.loads, path.open()):
        key = r["answer_key"]
        out.append({
            "key": r["example_id"],
            "needs_review": r.get("needs_review", False),
            "split": r["split"],
            "inputs": {"header": r["header"], "narrative": r["narrative"]},
            "outputs": {
                "valid": key["valid"],
                "missing_element": key["missing_element"],
                "is_serious": key["is_serious"],
                "seriousness_criteria": key["seriousness_criteria"],
                "reaction_expectedness": key["reaction_expectedness"],
                "case_expectedness": key["case_expectedness"],
                "reporting_route": key["reporting_route"],
                "due_date": key["due_date"],
                "duplicate_of": key["duplicate_of"],
            },
            "metadata": {
                "safety_report_id": r["safety_report_id"],
                "target_drug": r["target_drug"],
                "source_type": r["source_type"],
                "constructed": r["constructed"],
                "prompt_version": r["prompt_version"],
                "reviewed_by": r.get("reviewed_by", "automated_checks"),
                "manual_edit": r.get("manual_edit", False),
                "label_effective_time": key["label_effective_time"],
                "source_case": "-".join(r["source_case"]),
                "near_miss_of": "-".join(r["near_miss_of"]) if r.get("near_miss_of") else None,
            },
        })
    return out


def git_commit():
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, text=True).strip()
    except Exception:
        return "nogit"


def main():
    client = Client()
    examples = real_examples() + constructed_examples()
    held = [e for e in examples if e["needs_review"]]
    examples = [e for e in examples if not e["needs_review"]]
    if held:
        print(f"NOT uploading {len(held)} needs_review examples: {[e['key'] for e in held]}")
    keys = Counter(e["key"] for e in examples)
    assert max(keys.values()) == 1, f"duplicate example keys: {[k for k, n in keys.items() if n > 1]}"

    if client.has_dataset(dataset_name=DATASET):
        dataset = client.read_dataset(dataset_name=DATASET)
    else:
        dataset = client.create_dataset(DATASET, description=DESCRIPTION)
        print(f"created dataset {DATASET}")

    existing = {str(e.id): e for e in client.list_examples(dataset_id=dataset.id)}
    wanted = {example_id(e["key"]): e for e in examples}

    def payload(eid, e):
        return {"id": eid, "inputs": e["inputs"], "outputs": e["outputs"],
                "metadata": {**e["metadata"], "example_key": e["key"]}, "split": e["split"]}

    def unchanged(eid, e):
        old = existing[eid]
        old_split = (old.metadata or {}).get("dataset_split") or []
        return (old.inputs == e["inputs"] and old.outputs == e["outputs"]
                and {k: v for k, v in (old.metadata or {}).items() if k != "dataset_split"}
                == {**e["metadata"], "example_key": e["key"]}
                and list(old_split) == [e["split"]])

    to_create = [payload(eid, e) for eid, e in wanted.items() if eid not in existing]
    to_update = [payload(eid, e) for eid, e in wanted.items() if eid in existing and not unchanged(eid, e)]
    to_delete = [eid for eid in existing if eid not in wanted]

    if to_create:
        client.create_examples(dataset_id=dataset.id, examples=to_create)
    if to_update:
        client.update_examples(dataset_id=dataset.id, updates=to_update)
    if to_delete:
        client.delete_examples(to_delete)
    print(f"sync: {len(to_create)} created, {len(to_update)} updated, {len(to_delete)} deleted, "
          f"{len(wanted) - len(to_create) - len(to_update)} unchanged")

    # Tag the current version with the commit the local files came from. On a
    # no-op run this just adds the new commit's tag to the existing version.
    latest = next(client.list_dataset_versions(dataset_id=dataset.id, limit=1))
    tag = f"git-{git_commit()}"
    client.update_dataset_tag(dataset_id=dataset.id, as_of=latest.as_of, tag=tag)
    changed = bool(to_create or to_update or to_delete)
    print(f"{'new' if changed else 'no changes, same'} dataset version {latest.as_of.isoformat()}, tagged {tag!r}")

    # Counts as uploaded.
    print(f"\ndataset: {DATASET}  ({len(wanted)} examples)")
    print(f"url: {getattr(dataset, 'url', None) or client._host_url + '/datasets/' + str(dataset.id)}")
    by = Counter((e["split"], e["outputs"]["reporting_route"]) for e in examples)
    routes = ["expedited_15_day", "periodic", "follow_up_required"]
    print(f"  {'split':6} " + " ".join(f"{r:>19}" for r in routes) + f" {'total':>7}")
    for split in ("dev", "test"):
        print(f"  {split:6} " + " ".join(f"{by[(split, r)]:>19}" for r in routes)
              + f" {sum(by[(split, r)] for r in routes):>7}")
    kinds = Counter((e["split"], e["metadata"]["constructed"]) for e in examples)
    print("  by constructed type:", dict(sorted(kinds.items())))


if __name__ == "__main__":
    main()
