"""Fetching examples from the LangSmith dataset, for the run scripts (not the agent)."""

from langsmith import Client

from pv_agent import config  # noqa: F401  (loads .env)

DATASET = "pv-case-intake"


def examples(split=None):
    client = Client()
    return list(client.list_examples(dataset_name=DATASET, splits=[split] if split else None))


def example_by_key(key):
    for e in examples():
        if e.metadata.get("example_key") == key or str(e.id) == key:
            return e
    raise KeyError(f"no example {key!r} in {DATASET}")


def split_of(example):
    return (example.metadata.get("dataset_split") or ["?"])[0]
