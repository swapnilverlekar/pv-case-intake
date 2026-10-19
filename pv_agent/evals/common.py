"""Shared by both systems under test: the unified output shape, cost, versions.

Both V2 (the graph) and V1 (the single-agent baseline) return the SAME output
dict, so every evaluator scores them identically:

    valid, missing_elements, target_drug, is_serious, seriousness_criteria,
    reactions [{reaction, quote, expectedness, label_quote}], case_expectedness,
    route, due_date, duplicate_of, claims, trajectory, tool_calls,
    followup_draft, usage, cost_usd, latency_s
"""

import subprocess

from pv_agent import config

CRITERIA = ["death", "life_threatening", "hospitalization", "disability", "congenital_anomaly", "medically_important"]
# agent criterion -> reference criterion
REF_CRITERION = {"death": "death", "life_threatening": "life_threatening", "hospitalization": "hospitalization",
                 "disability": "disabling", "congenital_anomaly": "congenital_anomaly",
                 "medically_important": "other_medically_important"}


def cost_usd(usage_by_model):
    """$ from a UsageMetadataCallbackHandler's usage_metadata."""
    total = 0.0
    for model, u in (usage_by_model or {}).items():
        price = next((p for name, p in config.PRICES.items() if model.startswith(name)), None)
        if not price:
            continue
        d = u.get("input_token_details") or {}
        read, write = d.get("cache_read") or 0, d.get("cache_creation") or 0
        fresh = max(0, (u.get("input_tokens") or 0) - read - write)
        total += (fresh * price["input"] + read * price["cache_read"] + write * price["cache_write"]
                  + (u.get("output_tokens") or 0) * price["output"]) / 1e6
    return round(total, 6)


def total_tokens(usage_by_model):
    return sum((u.get("total_tokens") or 0) for u in (usage_by_model or {}).values())


def git_version():
    """Short commit, with -dirty if the working tree has uncommitted changes."""
    try:
        sha = subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=config.REPO, text=True).strip()
        dirty = subprocess.call(["git", "diff", "--quiet", "HEAD", "--", "pv_agent"], cwd=config.REPO) != 0
        return sha + ("-dirty" if dirty else "")
    except Exception:
        return "nogit"


def message_text(inputs):
    """Header + narrative as one string, for quote checks."""
    header = inputs.get("header")
    if isinstance(header, dict):
        header = "\n".join(f"{k}: {v}" for k, v in header.items())
    return f"{header or ''}\n\n{inputs.get('narrative', '')}"
