"""Quick check: run all dev examples, compare valid / missing_element with the
references. This script reads reference outputs to score; the agent never
sees them -- it gets agent_inputs() only. Not the real evaluator.

    python -m pv_agent.run_dev_validity
"""

from pv_agent.config import MODEL
from pv_agent.dataset import examples
from pv_agent.graph import agent_inputs, build_graph, run_config


def main():
    dev = sorted(examples("dev"), key=lambda e: e.metadata["example_key"])
    graph = build_graph()
    states = graph.batch(
        [agent_inputs(e.inputs) for e in dev],
        config=[run_config(e.metadata["example_key"], e.metadata.get("safety_report_id"), eval_mode=True) for e in dev],
        max_concurrency=6,
    )

    rows, valid_ok, missing_ok = [], 0, 0
    for e, s in zip(dev, states):
        ref_valid = e.outputs["valid"]
        ref_missing = [e.outputs["missing_element"]] if e.outputs["missing_element"] else []
        v_ok = s["valid"] == ref_valid
        m_ok = s["missing_elements"] == ref_missing
        valid_ok += v_ok
        missing_ok += m_ok
        rows.append((e.metadata["example_key"], e.metadata["constructed"], ref_valid, s["valid"],
                     ",".join(ref_missing) or "-", ",".join(s["missing_elements"]) or "-",
                     s.get("target_drug"), v_ok and m_ok))

    print(f"model {MODEL}; {len(dev)} dev examples\n")
    print(f"{'example':34} {'type':10} {'ref valid':9} {'got':5} {'ref missing':26} {'got missing':40} {'target':13}")
    for key, kind, rv, gv, rm, gm, target, ok in rows:
        if not ok:
            print(f"{key:34} {kind:10} {str(rv):9} {str(gv):5} {rm:26} {gm:40} {str(target):13}")
    if all(r[-1] for r in rows):
        print("(no mismatches)")
    n = len(dev)
    print(f"\nvalid accuracy:           {valid_ok}/{n} = {valid_ok / n:.0%}")
    print(f"missing_element accuracy: {missing_ok}/{n} = {missing_ok / n:.0%}")
    for kind in ("none", "duplicate", "invalid"):
        sub = [r for r in rows if r[1] == kind]
        if sub:
            print(f"  {kind:10} {sum(r[-1] for r in sub)}/{len(sub)} fully correct")


if __name__ == "__main__":
    main()
