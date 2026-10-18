"""Scripted end-to-end: a serious case -> sign-off interrupt -> reviewer
correction (expectedness_wrong) -> code recomputes the route -> audit log.

    python -m pv_agent.demo_signoff [example_key]     # dev only
"""

import json
import sys
import time

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command

from pv_agent import config
from pv_agent.dataset import example_by_key, split_of
from pv_agent.graph import agent_inputs, build_graph, run_config


def main():
    key = sys.argv[1] if len(sys.argv) > 1 else "20296644-sertraline"
    example = example_by_key(key)
    if split_of(example) != "dev":
        sys.exit(f"{key} is not a dev example")
    thread = f"{key}-{int(time.time())}"
    config.RUNTIME.mkdir(exist_ok=True)

    with SqliteSaver.from_conn_string(str(config.RUNTIME / "checkpoints.sqlite")) as saver:
        graph = build_graph(checkpointer=saver)
        cfg = run_config(key, example.metadata.get("safety_report_id"), thread_id=thread)

        result = graph.invoke(agent_inputs(example.inputs), config=cfg)
        if "__interrupt__" not in result:
            sys.exit(f"no interrupt: route {result.get('route')} was auto-committed")
        payload = result["__interrupt__"][0].value
        print(f"=== thread {thread}: paused for case sign-off ===")
        print(json.dumps(payload, indent=2, ensure_ascii=False))

        # Reviewer says every 'unexpected' reaction is in fact expected.
        flips = [{"index": r["index"], "expectedness": "expected"}
                 for r in payload["reactions"] if r["expectedness"] == "unexpected"]
        resume = {"action": "correct", "reviewer": "Dr A. Reviewer (demo)", "reason_code": "expectedness_wrong",
                  "note": "Demo correction: reviewer judges these reactions covered by the label.",
                  "corrections": {"reactions": flips}}
        print("\n=== resume with ===")
        print(json.dumps(resume, indent=2))
        final_state = graph.invoke(Command(resume=resume), config=cfg)

    print("\n=== after correction ===")
    print(f"agent route:   {payload['proposed_route']} (due {payload['due_date']})")
    print(f"final route:   {final_state['final']['route']} (due {final_state['final']['due_date']})")
    print(f"clock basis:   {final_state['final']['clock_basis']}")
    print(f"receipt timestamp (unchanged): {final_state['receipt_timestamp']}")
    print(f"decided by:    {final_state['final']['decided_by']}")

    print("\n=== audit log lines for this thread ===")
    for line in (config.RUNTIME / "audit_log.jsonl").open():
        row = json.loads(line)
        if row["thread_id"] == thread:
            print(json.dumps({k: row[k] for k in ("timestamp", "actor", "action", "reason_code", "label_effective_time")},
                             ensure_ascii=False))
            if row["action"] == "reviewer_corrected":
                print("   before:", json.dumps(row["before"]["route"]), "->", "after:", json.dumps(row["after"]["route"]))
    print(f"\ncorrection appended to {config.RUNTIME / 'corrections.jsonl'}; case record {config.RUNTIME / 'cases' / (thread + '.json')}")


if __name__ == "__main__":
    main()
