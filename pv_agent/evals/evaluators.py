"""Code evaluators (no LLM). Pure functions of (outputs, reference_outputs).

Per-example evaluators are passed to langsmith.evaluate(); `compute_metrics`
recomputes every metric from a list of rows so the comparison table and the
summary evaluators use the same code. A score of None means "does not apply
to this example".
"""

import statistics

from pv_agent.data_access import labels
from pv_agent.evals.common import REF_CRITERION, message_text
from pv_agent.llm import is_quote_of
from pv_agent.nodes.expectedness import label_text

EXP = "expedited_15_day"
SPECIALISTS = {"seriousness", "expectedness", "duplicate_check"}
PREFIX = ["intake", "extraction", "product_normalization", "validity_gate"]
TRACKED_CRITERIA = ["death", "life_threatening", "hospitalization", "medically_important"]


def is_dup_ref(ref):
    return ref.get("duplicate_of") is not None


def ref_missing(ref):
    m = ref.get("missing_element")
    return set(m if isinstance(m, list) else [m] if m else [])


# ---------------------------------------------------------- per example


def failed(outputs):
    """An errored run (e.g. an API error) has no outputs: scored n/a here, and
    reported as a run error, never silently mixed into a metric."""
    return not outputs or "route" not in outputs


def guard(fn):
    import functools
    keys = {"validity": ["valid_correct", "missing_elements_correct"], "cost_latency": ["cost_usd", "latency_s", "total_tokens"]}

    @functools.wraps(fn)
    def wrapped(*args, **kwargs):
        outputs = kwargs.get("outputs", args[1] if len(args) > 1 and fn.__code__.co_varnames[0] == "inputs" else args[0] if args else None)
        if failed(outputs):
            names = keys.get(fn.__name__, [fn.__name__])
            res = [{"key": k, "score": None, "comment": "run failed"} for k in names]
            return res if len(res) > 1 else res[0]
        return fn(*args, **kwargs)
    return wrapped


def validity(outputs, reference_outputs):
    return [
        {"key": "valid_correct", "score": int(outputs["valid"] == reference_outputs["valid"])},
        {"key": "missing_elements_correct", "score": int(set(outputs["missing_elements"] or []) == ref_missing(reference_outputs))},
    ]


def route_correct(outputs, reference_outputs):
    """Duplicates are scored on duplicate_of, not on route."""
    if is_dup_ref(reference_outputs):
        return {"key": "duplicate_of_correct", "score": int(outputs["duplicate_of"] == reference_outputs["duplicate_of"])}
    return {"key": "route_correct", "score": int(outputs["route"] == reference_outputs["reporting_route"])}


def due_date_exact(outputs, reference_outputs):
    """On cases the reference AND the system both route expedited: is the date right?"""
    if reference_outputs["reporting_route"] != EXP or outputs["route"] != EXP:
        return {"key": "due_date_exact", "score": None}
    return {"key": "due_date_exact", "score": int(outputs["due_date"] == reference_outputs["due_date"])}


def is_serious_correct(outputs, reference_outputs):
    if reference_outputs.get("is_serious") is None:
        return {"key": "is_serious_correct", "score": None}
    return {"key": "is_serious_correct", "score": int(outputs.get("is_serious") == reference_outputs["is_serious"])}


def case_expectedness_correct(outputs, reference_outputs):
    """Case-level unexpected vs expected, on serious valid cases."""
    r = reference_outputs
    if not (r.get("valid") and r.get("is_serious") and r.get("case_expectedness") in ("expected", "unexpected")):
        return {"key": "case_expectedness_correct", "score": None}
    return {"key": "case_expectedness_correct", "score": int(outputs.get("case_expectedness") == r["case_expectedness"])}


def verify_claims(outputs, inputs):
    msg = message_text(inputs)
    label = label_text(outputs["target_drug"]) if outputs.get("target_drug") in labels() else ""
    results = []
    for c in outputs.get("claims") or []:
        if c["source"] == "label" and (c["quote"] or "").strip().upper() == "NOT FOUND":
            continue  # not a claim of support
        results.append(is_quote_of(c["quote"], label if c["source"] == "label" else msg))
    return results


def evidence_grounding(inputs, outputs):
    """Share of the model's quotes (used or rejected) that are verbatim in the message or label."""
    checked = verify_claims(outputs, inputs)
    return {"key": "evidence_grounding", "score": (sum(checked) / len(checked)) if checked else None}


def trajectory_ok(outputs):
    path = outputs.get("trajectory") or []
    if path == ["baseline_v1_agent"]:
        return {"key": "trajectory_ok", "score": None, "comment": "baseline has no node path"}
    problems = []
    if path[:4] != PREFIX:
        problems.append(f"prefix {path[:4]}")
    rest = path[4:]
    if outputs["valid"]:
        if set(rest[:3]) != SPECIALISTS:
            problems.append(f"specialists {rest[:3]}")
        if rest[3:4] != ["clock"]:
            problems.append("clock not after the three specialists")
        if "followup_planner" in rest:
            problems.append("follow-up planner ran on a valid case")
    else:
        if rest[:2] != ["followup_planner", "followup_review"]:
            problems.append(f"invalid branch {rest[:2]}")
        if SPECIALISTS & set(rest):
            problems.append("specialists ran on an invalid case")
        tools = [t["tool"] for t in outputs.get("tool_calls") or []]
        drafts = [i for i, t in enumerate(tools) if t in ("draft_followup_message", "draft_quality_referral")]
        if not drafts:
            problems.append("no draft")
        elif "get_missing_elements" not in tools or tools.index("get_missing_elements") > drafts[-1]:
            problems.append("drafted before get_missing_elements")
        elif drafts[-1] != len(tools) - 1:
            problems.append("a draft tool is not the final step")
    if path[-1:] != ["commit"]:
        problems.append("does not end at commit")
    return {"key": "trajectory_ok", "score": int(not problems), "comment": "; ".join(problems) or "ok"}


def cost_latency(outputs):
    return [{"key": "cost_usd", "score": outputs.get("cost_usd")},
            {"key": "latency_s", "score": outputs.get("latency_s")},
            {"key": "total_tokens", "score": outputs.get("total_tokens")}]


PER_EXAMPLE = [guard(f) for f in (validity, route_correct, due_date_exact, is_serious_correct,
                                   case_expectedness_correct, evidence_grounding, trajectory_ok, cost_latency)]


# ---------------------------------------------------------- whole experiment


def expedited_counts(rows):
    """rows: [(key, inputs, outputs, ref)]. Excludes duplicate examples."""
    tp = fn = fp = tn = 0
    fns, fps = [], []
    for key, _, o, r in rows:
        if is_dup_ref(r):
            continue
        ref_e, got_e = r["reporting_route"] == EXP, o["route"] == EXP
        if ref_e and got_e:
            tp += 1
        elif ref_e:
            fn += 1
            fns.append(key)
        elif got_e:
            fp += 1
            fps.append(key)
        else:
            tn += 1
    return {"tp": tp, "fn": fn, "fp": fp, "tn": tn, "fn_cases": fns, "fp_cases": fps,
            "recall": tp / (tp + fn) if tp + fn else None, "precision": tp / (tp + fp) if tp + fp else None}


def duplicate_counts(rows):
    """Over ALL examples: a false merge anywhere counts."""
    tp = fp = fn = 0
    for _, _, o, r in rows:
        ref, got = r.get("duplicate_of"), o.get("duplicate_of")
        if got and got == ref:
            tp += 1
        else:
            if got:
                fp += 1
            if ref:
                fn += 1
    return {"recall": tp / (tp + fn) if tp + fn else None, "precision": tp / (tp + fp) if tp + fp else None,
            "tp": tp, "fp": fp, "fn": fn}


def criterion_recall(rows):
    out = {}
    for c in TRACKED_CRITERIA:
        hits = total = 0
        for _, _, o, r in rows:
            if (r.get("seriousness_criteria") or {}).get(REF_CRITERION[c]):
                total += 1
                hits += bool(((o.get("seriousness_criteria") or {}).get(c) or {}).get("met"))
        out[c] = (hits / total if total else None, total)
    return out


def mean_score(rows, fn, key=None):
    vals = []
    for _, i, o, r in rows:
        res = fn(**{k: v for k, v in (("inputs", i), ("outputs", o), ("reference_outputs", r))
                    if k in fn.__code__.co_varnames[:fn.__code__.co_argcount]})
        for x in (res if isinstance(res, list) else [res]):
            if (key is None or x["key"] == key) and x["score"] is not None:
                vals.append(x["score"])
    return (sum(vals) / len(vals) if vals else None), len(vals)


def compute_metrics(rows):
    """Every metric for one repetition of one system."""
    e, d = expedited_counts(rows), duplicate_counts(rows)
    m = {
        "expedited_recall": e["recall"], "expedited_precision": e["precision"],
        "valid_correct": mean_score(rows, validity, "valid_correct")[0],
        "missing_elements_correct": mean_score(rows, validity, "missing_elements_correct")[0],
        "route_correct": mean_score(rows, route_correct, "route_correct")[0],
        "duplicate_of_correct (dup examples)": mean_score(rows, route_correct, "duplicate_of_correct")[0],
        "duplicate_precision": d["precision"], "duplicate_recall": d["recall"],
        "due_date_exact": mean_score(rows, due_date_exact)[0],
        "is_serious_correct": mean_score(rows, is_serious_correct)[0],
        "case_expectedness_correct": mean_score(rows, case_expectedness_correct)[0],
        "evidence_grounding": mean_score(rows, evidence_grounding)[0],
        "trajectory_ok": mean_score(rows, trajectory_ok)[0],
    }
    for c, (v, _) in criterion_recall(rows).items():
        m[f"recall_{c}"] = v
    costs = [o.get("cost_usd") or 0 for _, _, o, _ in rows]
    lat = sorted(o.get("latency_s") or 0 for _, _, o, _ in rows)
    m["cost_per_case_usd"] = sum(costs) / len(costs) if costs else None
    m["latency_p50_s"] = statistics.median(lat) if lat else None
    m["latency_p95_s"] = lat[min(len(lat) - 1, round(0.95 * (len(lat) - 1)))] if lat else None
    return m, e


# Summary evaluators for langsmith.evaluate (same code as the table).
def _rows(runs, examples):
    return [(ex.metadata.get("example_key"), ex.inputs, run.outputs, ex.outputs)
            for run, ex in zip(runs, examples) if not failed(run.outputs)]


def expedited_summary(runs, examples):
    e = expedited_counts(_rows(runs, examples))
    return {"results": [
        {"key": "expedited_recall", "score": e["recall"], "comment": f"TP={e['tp']} FN={e['fn']} FP={e['fp']} TN={e['tn']}; FN: {e['fn_cases']}"},
        {"key": "expedited_precision", "score": e["precision"], "comment": f"FP: {e['fp_cases']}"},
    ]}


def duplicate_summary(runs, examples):
    d = duplicate_counts(_rows(runs, examples))
    return {"results": [{"key": "duplicate_precision", "score": d["precision"]},
                        {"key": "duplicate_recall", "score": d["recall"]}]}


def criterion_summary(runs, examples):
    return {"results": [{"key": f"recall_{c}", "score": v, "comment": f"n={n}"}
                        for c, (v, n) in criterion_recall(_rows(runs, examples)).items()]}


SUMMARY = [expedited_summary, duplicate_summary, criterion_summary]
