"""Scripted end-to-end: an invalid case -> follow-up planner (the agent) ->
review interrupt -> approve -> outbox file.

    python -m pv_agent.demo_followup [example_key]    # dev only
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
    key = sys.argv[1] if len(sys.argv) > 1 else "INV-20301061-atorvastatin"
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
            sys.exit(f"no interrupt: valid={result.get('valid')} route={result.get('route')}")
        print(f"=== thread {thread}: missing {result['missing_elements']} ===\n")
        print("planner tool calls (the model chose these):")
        for i, tc in enumerate(result["followup"]["tool_calls"], 1):
            args = json.dumps(tc["args"], ensure_ascii=False)
            print(f"  {i}. {tc['tool']}({args[:300]}{'...' if len(args) > 300 else ''})")
        draft = result["followup"]["draft"]
        print(f"\ndrafted follow-up  [channel: {draft['channel']}]\n")
        print(draft["message"])

        resume = {"action": "approve", "reviewer": "J. Safety Officer (demo)"}
        print(f"\n=== resume with {resume} ===")
        graph.invoke(Command(resume=resume), config=cfg)

    outbox = config.RUNTIME / "outbox" / f"{thread}.json"
    print(f"\n=== {outbox} ===")
    print(outbox.read_text())


if __name__ == "__main__":
    main()
