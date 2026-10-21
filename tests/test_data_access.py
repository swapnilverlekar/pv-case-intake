"""The agent's file guard (data_access.py): only the pinned labels and the case store."""

import json
import os

import pytest

from pv_agent import config
from pv_agent.data_access import _read_json, case_store, labels

DATA = config.REPO / "AE_Data" / "data"


def test_the_pinned_labels_are_readable():
    assert set(labels()) == {"lisinopril", "metformin", "warfarin", "sertraline", "atorvastatin", "levothyroxine"}


def test_the_case_store_is_readable():
    assert isinstance(case_store(), list) and case_store()


@pytest.mark.parametrize("name", [
    "cases_labeled.json", "term_decisions.csv", "my_review.csv", "narratives.jsonl",
    "constructed_cases.jsonl", "split.json", "expectedness_synonyms.json", "eval_candidates.json",
])
def test_answer_key_files_are_refused(name):
    with pytest.raises(PermissionError):
        _read_json(DATA / name)


def test_the_answer_key_method_is_refused():
    with pytest.raises(PermissionError):
        _read_json(config.REPO / "AE_Data" / "derive_expectedness.py")


def test_a_non_label_file_in_the_labels_folder_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "LABELS_DIR", tmp_path)
    (tmp_path / "events_warfarin.jsonl").write_text("{}")
    with pytest.raises(PermissionError):
        _read_json(tmp_path / "events_warfarin.jsonl")


def test_path_traversal_out_of_the_labels_folder_is_refused():
    with pytest.raises(PermissionError):
        _read_json(config.LABELS_DIR / ".." / "cases_labeled.json")


def test_a_label_named_symlink_pointing_elsewhere_is_refused(tmp_path, monkeypatch):
    outside = tmp_path / "secret.json"
    outside.write_text(json.dumps({"answer": "key"}))
    labels_dir = tmp_path / "labels"
    labels_dir.mkdir()
    os.symlink(outside, labels_dir / "label_fake.json")
    monkeypatch.setattr(config, "LABELS_DIR", labels_dir)
    with pytest.raises(PermissionError):
        _read_json(labels_dir / "label_fake.json")


def test_a_file_named_like_a_label_outside_the_labels_folder_is_refused(tmp_path):
    (tmp_path / "label_warfarin.json").write_text("{}")
    with pytest.raises(PermissionError):
        _read_json(tmp_path / "label_warfarin.json")
