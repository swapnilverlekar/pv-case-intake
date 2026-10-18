"""Quick check of routes on the dev split. Reads reference outputs to score;
the agent gets agent_inputs() only. Runs in eval_mode (no interrupts: the
agent's own decisions are scored, not a reviewer's). Not the real evaluator.

    python -m pv_agent.run_dev_route
"""

from collections import Counter

from pv_agent.config import MODEL
from pv_agent.dataset import examples
from pv_agent.graph import agent_inputs, build_graph, run_config

ROUTES = ["expedited_15_day", "periodic", "follow_up_required", "merge_with_existing"]
# agent criterion name -> reference criterion name
CRITERIA = {"death": "death", "life_threatening": "life_threatening", "hospitalization": "hospitalization",
            "disability": "disabling", "congenital_anomaly": "congenital_anomaly",
            "medically_important": "other_medically_important"}


def cause(ref, s):
    """One line on why the agent's route differs from the reference."""
    if s.get("valid") != ref["valid"]:
        return f"validity: ref valid={ref['valid']} {ref['missing_element'] or ''}, agent valid={s.get('valid')} {s.get('missing_elements')}"
    if not s.get("valid"):
        return "both invalid (route should match)"
    dup = s["duplicate"]["duplicate_of"]
    if (dup or None) != (ref["duplicate_of"] or None):
        return f"duplicate: ref {ref['duplicate_of']}, agent {dup} ({s['duplicate']['reasoning']})"
    if ref["is_serious"] is not None and s["seriousness"]["is_serious"] != ref["is_serious"]:
        got = [k for k, v in s["seriousness"]["criteria"].items() if v["met"]]
        want = [a for a, b in CRITERIA.items() if ref["seriousness_criteria"].get(b)]
        return f"seriousness: ref {want or 'not serious'}, agent {got or 'not serious'}"
    ref_unexp = ref["case_expectedness"] == "unexpected"
    if s["expectedness"]["any_unexpected"] != ref_unexp:
        ref_terms = [f"{r['term']}={r['expectedness']}" for r in ref["reaction_expectedness"]]
        got = [f"{r['reaction']}={r['expectedness']}" + ("*" if r["needs_review"] else "") for r in s["expectedness"]["reactions"]]
        return f"expectedness: ref {ref_terms}; agent {got}"
    return "other"


def main():
    dev = sorted(examples("dev"), key=lambda e: e.metadata["example_key"])
    states = build_graph().batch(
        [agent_inputs(e.inputs) for e in dev],
        config=[run_config(e.metadata["example_key"], e.metadata.get("safety_report_id"), eval_mode=True) for e in dev],
        max_concurrency=6,
    )
    pairs = [(e, e.outputs, s) for e, s in zip(dev, states)]
    n = len(pairs)

    # Route accuracy + confusion
    correct = sum(ref["reporting_route"] == s["route"] for _, ref, s in pairs)
    confusion = Counter((ref["reporting_route"], s["route"]) for _, ref, s in pairs)
    print(f"model {MODEL}; {n} dev examples\n")
    print(f"route accuracy: {correct}/{n} = {correct / n:.0%}\n")
    print("confusion (rows = reference, columns = agent):")
    print(f"  {'':20}" + "".join(f"{r[:12]:>14}" for r in ROUTES))
    for r in ROUTES:
        print(f"  {r:20}" + "".join(f"{confusion[(r, c)]:>14}" for c in ROUTES))

    # Expedited recall / precision (headline)
    tp = confusion[("expedited_15_day", "expedited_15_day")]
    ref_exp = sum(ref["reporting_route"] == "expedited_15_day" for _, ref, _ in pairs)
    got_exp = sum(s["route"] == "expedited_15_day" for _, _, s in pairs)
    print(f"\nEXPEDITED recall:    {tp}/{ref_exp} = {tp / ref_exp:.0%}" if ref_exp else "\nno expedited references")
    print(f"EXPEDITED precision: {tp}/{got_exp} = {tp / got_exp:.0%}" if got_exp else "EXPEDITED precision: n/a (none predicted)")

    # is_serious on examples where the reference has it and the agent assessed it
    ser = [(ref, s) for _, ref, s in pairs if ref["is_serious"] is not None and s.get("seriousness")]
    ser_ok = sum(s["seriousness"]["is_serious"] == ref["is_serious"] for ref, s in ser)
    print(f"\nis_serious accuracy: {ser_ok}/{len(ser)}")

    # due date exact match on reference-expedited cases the agent also expedited
    due = [(ref, s) for _, ref, s in pairs if ref["reporting_route"] == "expedited_15_day" and s["route"] == "expedited_15_day"]
    due_ok = sum(s["due_date"] == ref["due_date"] for ref, s in due)
    print(f"due_date exact match (expedited, both): {due_ok}/{len(due)}")

    # duplicate_of on duplicate / near_miss examples
    dup = [(e, ref, s) for e, ref, s in pairs if e.metadata["constructed"] in ("duplicate", "near_miss")]
    dup_ok = sum((s.get("duplicate") or {}).get("duplicate_of") == ref["duplicate_of"] for _, ref, s in dup)
    print(f"duplicate_of accuracy (duplicate/near_miss): {dup_ok}/{len(dup)}")
    for e, ref, s in dup:
        got = (s.get("duplicate") or {}).get("duplicate_of")
        if got != ref["duplicate_of"]:
            why = "agent did not run the duplicate check (invalid)" if not s.get("valid") else s["duplicate"]["reasoning"]
            print(f"  {e.metadata['example_key']:28} ref {ref['duplicate_of']} agent {got}: {why}")

    # Every route miss
    misses = [(e, ref, s) for e, ref, s in pairs if ref["reporting_route"] != s["route"]]
    print(f"\nroute misses ({len(misses)}):")
    for e, ref, s in misses:
        print(f"  {e.metadata['example_key']:28} ref {ref['reporting_route']:20} agent {s['route']:20} {cause(ref, s)}")

    flagged = [e.metadata["example_key"] for e, _, s in pairs if (s.get("expectedness") or {}).get("needs_review")]
    print(f"\nexpectedness needs_review flags: {len(flagged)} {flagged}")


if __name__ == "__main__":
    main()
