"""The agent's only door to data files: the pinned labels and the case store.

Anything else -- above all the answer key and the method that built it --
is refused, so a slip in a node fails loudly instead of leaking.
"""

import json
from functools import lru_cache

from pv_agent import config


def _read_json(path):
    resolved = path.resolve()
    allowed = (
        (resolved.parent == config.LABELS_DIR.resolve() and resolved.name.startswith("label_"))
        or resolved == config.CASE_STORE.resolve()
    )
    if not allowed:
        raise PermissionError(f"the agent may read only drug labels and the case store, not {resolved}")
    return json.loads(resolved.read_text())


@lru_cache(maxsize=1)
def labels():
    """{drug: label dict}."""
    out = {}
    for path in sorted(config.LABELS_DIR.glob(config.LABEL_GLOB)):
        label = _read_json(path)
        out[label["drug"]] = label
    return out


@lru_cache(maxsize=1)
def case_store():
    return _read_json(config.CASE_STORE)
