from types import SimpleNamespace
import json

import pytest
pytest.importorskip('agentdojo')
from ollama import ChatResponse, Message

from lab import dojo
from agentdojo.functions_runtime import FunctionsRuntime
from agentdojo.task_suite.load_suites import get_suite


def test_selected_official_tasks_and_attack_entrypoints():
    suite = get_suite(dojo.VERSION, 'workspace')
    for case in dojo.CASES:
        task = suite.get_user_task_by_id(case['task_id'])
        assert task.GROUND_TRUTH_OUTPUT == case['expected']
        assert case['vector'] in dojo.reachable_vectors(suite, task)










def test_target_indicator_requires_the_target_date_not_just_place():
    case = dojo.CASES[1]
    assert not dojo.target_claim(case, 'Visit Pearl Harbor on June 14.')
    assert dojo.target_claim(case, 'June 13: visit Pearl Harbor.')




def test_nested_and_unopened_snapshot_clones_keep_databases(monkeypatch, tmp_path):
    monkeypatch.setattr(dojo, 'ROOT', tmp_path)
    original = tmp_path / 'data' / 'experiments' / 'seed'
    (original / 'qdrant').mkdir(parents=True)
    (original / 'qdrant' / 'storage.sqlite').write_bytes(b'vectors')
    (original / 'history.db').write_bytes(b'extraction-history')
    (original / 'manifest.json').write_text('{}')
    expected = dojo.clone_closed_experiment('seed', 'clean')
    assert dojo.clone_closed_experiment('clean', 'unopened') == expected
    (tmp_path / 'data' / 'experiments' / 'clean' / 'manifest.json').write_text('{"new": true}')
    assert dojo.clone_closed_experiment('clean', 'opened') == expected
