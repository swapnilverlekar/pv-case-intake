"""intake (code): capture the receipt timestamp -- the legal clock start.

Parsed once from the header's "Received:" line. No model touches it, and the
state reducer makes it write-once, so nothing downstream can recompute it.
"""

import re
from datetime import datetime


def header_text(header):
    """The header as the intake system sees it: 'Key: value' lines."""
    if isinstance(header, dict):
        return "\n".join(f"{k.capitalize()}: {v}" for k, v in header.items())
    return header or ""


def field(text, name):
    m = re.search(rf"^\s*{name}\s*:\s*(.+?)\s*$", text, re.IGNORECASE | re.MULTILINE)
    return m.group(1) if m else None


def intake(state):
    text = header_text(state.get("header"))
    errors = []

    received = field(text, "Received")
    timestamp = None
    if received is None:
        errors.append("no 'Received:' line in header")
    else:
        try:
            parsed = datetime.fromisoformat(received)
            if parsed.tzinfo is None:
                errors.append(f"receipt timestamp has no timezone: {received!r}")
            else:
                timestamp = parsed.isoformat()
        except ValueError:
            errors.append(f"unparseable receipt timestamp: {received!r}")

    return {
        "receipt_timestamp": timestamp,
        "source_type": field(text, "Source"),
        "ref": field(text, "Ref"),
        "intake_errors": errors,
    }
