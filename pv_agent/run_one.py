"""Run one report through the graph and print the full final state.

    python -m pv_agent.run_one 20296644-sertraline                 # a dev example; pauses for review
    python -m pv_agent.run_one 20296644-sertraline --eval-mode     # no pauses: the agent's own decisions
    python -m pv_agent.run_one --file my_report.txt                # your own report
    python -m pv_agent.run_one --file my_report.txt --eval-mode

A --file is plain text: header lines first, then a blank line, then the narrative:

    Source: email from patient or family
    Received: 2026-10-18T09:30:00+00:00
    Ref: INBOX-TEST-1

    Hello, I'm writing about my mother...

Without --eval-mode the run pauses at case sign-off or follow-up review: the
reviewer payload is printed and you type the resume JSON (one line), e.g.
{"action": "approve", "reviewer": "Your Name"}. Records go to runtime/.
Dataset examples must be in the dev split: the test set is only for final numbers.
"""

import argparse
import json
import re
import sys
import time
from pathlib import Path

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command

from pv_agent import config
from pv_agent.dataset import example_by_key, split_of
from pv_agent.graph import agent_inputs, build_graph, run_config

HEADER_LINE = re.compile(r"^\s*(Source|Received|Ref)\s*:", re.IGNORECASE)


def read_report_file(path):
    """(header text, narrative) from a .txt: leading Source/Received/Ref lines, then the narrative."""
    lines = Path(path).read_text().splitlines()
    header = []
    while lines and (HEADER_LINE.match(lines[0]) or not lines[0].strip()):
        line = lines.pop(0)
        if line.strip():
            header.append(line.strip())
        elif header:
            break  # blank line after the header ends it
    if not any(l.lower().startswith("received") for l in header):
        print("warning: no 'Received:' line -- intake will record an error and no due date can be set\n")
    narrative = "\n".join(lines).strip()
    if not narrative:
        sys.exit(f"{path}: no narrative after the header lines")
    return "\n".join(header), narrative


def ask_resume(payload):
    print("\n" + "=" * 80)
    print("PAUSED FOR REVIEW -- payload:")
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    print("=" * 80)
    while True:
        text = input("\nresume JSON (one line)> ").strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            print(f"not valid JSON ({e}); try again")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("example_key", nargs="?", help="a dev example, e.g. 20296644-sertraline")
    parser.add_argument("--file", help="a .txt report: Source/Received/Ref lines, blank line, narrative")
    parser.add_argument("--eval-mode", action="store_true", help="skip both review pauses")
    args = parser.parse_args()
    if bool(args.example_key) == bool(args.file):
        parser.error("give exactly one of: an example key, or --file")

    if args.file:
        header, narrative = read_report_file(args.file)
        inputs, key, report_id = {"header": header, "narrative": narrative}, Path(args.file).stem, None
        label = f"file {args.file}"
    else:
        example = example_by_key(args.example_key)
        if split_of(example) != "dev":
            sys.exit(f"{args.example_key} is in the {split_of(example)} split; run_one only runs dev examples")
        inputs, key = agent_inputs(example.inputs), example.metadata["example_key"]
        report_id = example.metadata.get("safety_report_id")
        label = f"example {key} (dev, constructed={example.metadata.get('constructed')})"

    thread = f"{key}-{int(time.time())}"
    cfg = run_config(key, report_id, thread_id=thread, eval_mode=args.eval_mode)
    config.RUNTIME.mkdir(exist_ok=True)

    with SqliteSaver.from_conn_string(str(config.RUNTIME / "checkpoints.sqlite")) as saver:
        graph = build_graph(checkpointer=saver)
        state = graph.invoke(inputs, config=cfg)
        while "__interrupt__" in state:
            state = graph.invoke(Command(resume=ask_resume(state["__interrupt__"][0].value)), config=cfg)

    print(f"\n{label}   thread {thread}   eval_mode={args.eval_mode}\n")
    print(json.dumps({k: v for k, v in state.items() if k not in ("header", "narrative", "audit_events")},
                     indent=2, ensure_ascii=False))
    if not args.eval_mode:
        print(f"\nrecords: {config.RUNTIME / 'cases' / (thread + '.json')}, {config.RUNTIME / 'audit_log.jsonl'}")


if __name__ == "__main__":
    main()
