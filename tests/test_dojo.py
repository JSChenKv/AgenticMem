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
        # Answer tasks: the expected answer; action tasks: the expected event start time.
        assert case['expected'] == (task._EVENT_START_TIME if case['kind'] == 'action' else task.GROUND_TRUTH_OUTPUT)
        assert case['vector'] in dojo.reachable_vectors(suite, task)


def test_hawaii_document_and_email_slots_preserve_other_content():
    suite = get_suite(dojo.VERSION, 'workspace')
    case = dojo.CASES[1]
    original = suite.load_and_inject_default_environment({})
    clean = dojo.case_environment(suite, case)
    injected = dojo.case_environment(suite, case, injected=True)
    assert clean.inbox.emails['32'].timestamp.isoformat() == '2024-06-01T10:00:00'
    assert clean.inbox.emails['32'].timestamp > original.cloud_drive.files['7'].last_modified
    assert clean.inbox.emails['32'].model_dump(exclude={'timestamp'}) == original.inbox.emails['32'].model_dump(exclude={'timestamp'})
    assert suite.load_and_inject_default_environment({}).inbox.emails['32'].timestamp.isoformat() == '2024-03-27T20:17:00'
    assert set(dojo.case_injections(case)) == {'drive_keywords_stuffing_injection', 'email_hiking_injection'}
    # AgentDojo's YAML loader collapses the template's blank lines; the words are identical.
    assert injected.inbox.emails['32'].body.split() == case['payload'].split()
    for key, email in clean.inbox.emails.items():
        if key == '32':
            assert email.model_dump(exclude={'body'}) == injected.inbox.emails[key].model_dump(exclude={'body'})
        else:
            assert email == injected.inbox.emails[key]
    for key, document in clean.cloud_drive.files.items():
        if key == '24':
            assert ' '.join(case['payload'].split()) in ' '.join(injected.cloud_drive.files[key].content.split())
            # AgentDojo derives size from the injected content.
            assert document.model_dump(exclude={'content', 'size'}) == injected.cloud_drive.files[key].model_dump(exclude={'content', 'size'})
        else:
            assert document == injected.cloud_drive.files[key]










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
