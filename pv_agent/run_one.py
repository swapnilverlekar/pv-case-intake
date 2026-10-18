"""Run one dev example through the graph and print the full final state.

    python -m pv_agent.run_one 20279004-metformin
    python -m pv_agent.run_one INV-20278030-levothyroxine

Refuses test-split examples: the test set is only for final numbers.
"""

import json
import sys

from pv_agent.dataset import example_by_key, split_of
from pv_agent.graph import agent_inputs, build_graph, run_config


def main():
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    example = example_by_key(sys.argv[1])
    if split_of(example) != "dev":
        sys.exit(f"{sys.argv[1]} is in the {split_of(example)} split; run_one only runs dev examples")

    meta = example.metadata
    state = build_graph().invoke(
        agent_inputs(example.inputs),
        config=run_config(meta.get("example_key"), meta.get("safety_report_id")),
    )
    print(f"example {meta['example_key']} ({split_of(example)}, constructed={meta.get('constructed')})\n")
    print(json.dumps({k: v for k, v in state.items() if k not in ("header", "narrative")}, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
