"""Production records under runtime/ (gitignored). Written only by the commit
node, once per case, and never in eval mode."""

import json
from datetime import datetime, timezone

from pv_agent import config


def now():
    return datetime.now(timezone.utc).isoformat()


def _append(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:      # append-only
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def append_audit(events):
    _append(config.RUNTIME / "audit_log.jsonl", events)


def append_correction(row):
    _append(config.RUNTIME / "corrections.jsonl", [row])


def write_case(thread_id, record):
    path = config.RUNTIME / "cases" / f"{thread_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, indent=2, ensure_ascii=False))
    return path


def write_outbox(thread_id, message):
    path = config.RUNTIME / "outbox" / f"{thread_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(message, indent=2, ensure_ascii=False))
    return path
