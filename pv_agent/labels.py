"""Read-only access to the pinned drug labels -- the only data file the agent reads."""

import json
from functools import lru_cache

from pv_agent import config


@lru_cache(maxsize=1)
def load_labels():
    """{drug: label dict}. Refuses anything outside LABELS_DIR."""
    labels = {}
    for path in sorted(config.LABELS_DIR.glob(config.LABEL_GLOB)):
        resolved = path.resolve()
        if resolved.parent != config.LABELS_DIR.resolve() or not resolved.name.startswith("label_"):
            raise PermissionError(f"agent may only read drug labels, not {resolved}")
        label = json.loads(resolved.read_text())
        labels[label["drug"]] = label
    return labels


def name_index():
    """[(lowercase name, drug, source)] for every generic, brand and alias, longest first."""
    names = []
    for drug, label in load_labels().items():
        names.append((drug, drug, "label_generic"))
        names += [(n.lower(), drug, "label_generic") for n in label.get("generic_names", [])]
        names += [(n.lower(), drug, "label_brand") for n in label.get("brand_names", [])]
        names += [(n.lower(), drug, "brand_alias") for n in config.BRAND_ALIASES.get(drug, [])]
    return sorted(set(names), key=lambda x: -len(x[0]))
