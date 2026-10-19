"""Print the LangGraph Studio input JSON for a dev example.

    python -m pv_agent.export_input 20296644-sertraline
    python -m pv_agent.export_input 20296644-sertraline --today

--today sets Received to now (UTC), so days remaining and the due date are
current. The duplicate check only sees cases received in the 120 days before
receipt, and the case store holds 2022 reports, so with --today no duplicate
candidates are found. Use the real date for duplicate testing.

Refuses test-split examples: the test set is only for final numbers.
"""

import argparse
import json
import sys
from datetime import datetime, timezone

from pv_agent.dataset import example_by_key, split_of
from pv_agent.graph import agent_inputs


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("example_id")
    parser.add_argument("--today", action="store_true", help="set Received to now (UTC)")
    args = parser.parse_args()

    example = example_by_key(args.example_id)
    if split_of(example) != "dev":
        sys.exit(f"refused: {args.example_id} is in the {split_of(example)} split (dev examples only)")

    inputs = agent_inputs(example.inputs)
    if args.today:
        header = dict(inputs["header"])
        header["received"] = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        inputs["header"] = header
    print(json.dumps(inputs, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
