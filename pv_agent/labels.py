"""Drug names from the pinned labels, for product normalization."""

from pv_agent import config
from pv_agent.data_access import labels as load_labels


def name_index():
    """[(lowercase name, drug, source)] for every generic, brand and alias, longest first."""
    names = []
    for drug, label in load_labels().items():
        names.append((drug, drug, "label_generic"))
        names += [(n.lower(), drug, "label_generic") for n in label.get("generic_names", [])]
        names += [(n.lower(), drug, "label_brand") for n in label.get("brand_names", [])]
        names += [(n.lower(), drug, "brand_alias") for n in config.BRAND_ALIASES.get(drug, [])]
    return sorted(set(names), key=lambda x: -len(x[0]))
