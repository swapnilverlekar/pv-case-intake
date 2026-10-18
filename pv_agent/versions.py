"""Prompt versions: a short hash of each prompt and its output schema, so the
audit log says exactly which wording produced a decision."""

import hashlib
import json

from pv_agent import config


def _h(*parts):
    return hashlib.sha256("\n".join(parts).encode()).hexdigest()[:10]


def prompt_versions():
    from pv_agent.nodes import duplicate, expectedness, extraction, followup, seriousness
    return {
        "extraction": _h(extraction.SYSTEM, json.dumps(extraction.Extraction.model_json_schema(), sort_keys=True)),
        "seriousness": _h(seriousness.SYSTEM, json.dumps(seriousness.Seriousness.model_json_schema(), sort_keys=True)),
        "expectedness": _h(expectedness.SYSTEM, json.dumps(expectedness.Expectedness.model_json_schema(), sort_keys=True)),
        "duplicate": _h(duplicate.SYSTEM, json.dumps(duplicate.DuplicateDecision.model_json_schema(), sort_keys=True)),
        "followup_planner": _h(followup.PLANNER_PROMPT),
        "model": config.MODEL,
    }
