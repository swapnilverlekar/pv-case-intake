"""Configuration. Every model choice and every data path the agent may touch lives here."""

import os
from pathlib import Path

from dotenv import load_dotenv

REPO = Path(__file__).resolve().parent.parent
load_dotenv(REPO / ".env")
os.environ.setdefault("LANGSMITH_PROJECT", "pv-case-intake")

MODEL = "claude-sonnet-5-5"
EFFORT = "high"
MAX_TOKENS = 16000

# The ONLY data the agent may read: the pinned drug labels and the case
# store. Never the answer key (cases_labeled.json, term_decisions.csv,
# my_review.csv, narratives/constructed jsonl, split.json), and never the
# answer-key method (derive_expectedness.py, expectedness_synonyms.json).
# data_access.py refuses any other path.
LABELS_DIR = REPO / "AE_Data" / "data" / "raw"
LABEL_GLOB = "label_*.json"
CASE_STORE = REPO / "AE_Data" / "data" / "case_store.json"

# Label sections the expectedness specialist reads. Not contraindications:
# those are pre-existing conditions, not reactions the drug causes.
EXPECTEDNESS_SECTIONS = ["adverse_reactions", "warnings", "warnings_and_cautions", "boxed_warning", "precautions"]

# Duplicate-check candidate pre-filter (code).
DUPLICATE_WINDOW_DAYS = 120
DUPLICATE_AGE_TOLERANCE_YEARS = 2

EXPEDITED_DAYS = 15  # 21 CFR 314.80(c)(1): serious AND unexpected -> 15 calendar days

STORY = 2

# Other US brand names for the same active ingredients (openFDA brand_name).
# The cached labels only carry their own brand (Zestril, Lipitor, ...), but a
# report names whatever product the patient had. Public reference data, not
# answer key.
BRAND_ALIASES = {
    "lisinopril": ["Prinivil", "Qbrelis"],
    "metformin": ["Glucophage", "Fortamet", "Glumetza", "Riomet"],
    "warfarin": ["Coumadin"],
    "sertraline": [],
    "atorvastatin": [],
    "levothyroxine": ["Levoxyl", "Unithroid", "Euthyrox", "Tirosint", "Thyquidity", "Levo-T"],
}

GRAPH_NAME = "pv_intake"
