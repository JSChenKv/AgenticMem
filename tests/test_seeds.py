"""The scripted seed is fixed before trials and must never contain the real or attacker value."""
import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from lab import api, benchmark, seeds, sessions
from lab.dojo import CASES
from lab.values import attacker_content, classify_detail

TASKS = [c['task_id'] for c in CASES]


@pytest.mark.parametrize('task_id', TASKS)
def test_scripted_texts_carry_no_task_value_in_any_framing(task_id):
    # Every scripted text is checked against both tasks: neither value may appear anywhere.
    for _, messages in seeds.conversations(task_id):
        for message in messages:
            for task in TASKS:
                detail = classify_detail(task, message['content'])
                assert detail['label'] is None and not attacker_content(task, message['content']), (task, message)


@pytest.mark.parametrize('task_id', TASKS)
def test_one_related_distractor_in_the_middle_and_no_research_words(task_id):
    items = seeds.conversations(task_id)
    kinds = [kind for kind, _ in items]
    assert kinds.count('distractor') == 1 and kinds[0] != 'distractor' and kinds[-1] != 'distractor'
    assert 5 <= kinds.count('unrelated') <= 10
    text = json.dumps([messages for _, messages in items]).casefold()  # Only what Mem0 sees.
    for word in ('attack', 'poison', 'experiment', 'benchmark', 'payload', 'research', 'memory test', 'distractor'):
        assert word not in text
    case = next(c for c in CASES if c['task_id'] == task_id)
    assert case['expected'].casefold() not in text and case['target'].casefold() not in text


def test_write_scripted_seed_uses_the_normal_add_path(monkeypatch):
    added = []

    class Lab:
        def __init__(self, name):
            self.operation = None
            self.store = []

        def add(self, user, messages, source='user', **kwargs):
            record = {'id': f'id{len(self.store)}', 'memory': messages[0]['content']}
            self.store.append(record)
            added.append((user, messages, source))
            return {'results': [{**record, 'event': 'ADD'}]}

        def memories(self, user):
            return list(self.store)

        def record(self, *args, **kwargs):
            pass

        def close(self):
            pass

    monkeypatch.setattr('lab.core.Lab', Lab)
    result = seeds.write_scripted_seed('seed', CASES[1])
    assert result['status'] == 'completed'
    assert len(added) == len(seeds.conversations('user_task_30'))
    assert all(user == 'researcher' and source == 'scripted_seed' and [m['role'] for m in messages] == ['user', 'assistant']
               for user, messages, source in added)
    assert len(result['distractor_ids']) == 1 and len(result['unrelated_ids']) == len(seeds.UNRELATED)
    assert len(result['memory_after']) == len(added)


def test_session_sampling_is_recorded_and_passed_to_ollama(monkeypatch):
    captured = []

    class Client:
        def __init__(self, **kwargs):
            pass

        def chat(self, **kwargs):
            captured.append(kwargs['options'])
            return SimpleNamespace(message=SimpleNamespace(content='Done.', tool_calls=None,
                                                           model_dump=lambda **k: {'role': 'assistant', 'content': 'Done.'}),
                                   model_dump=lambda **k: {})

    monkeypatch.setattr(sessions, 'Client', Client)
    monkeypatch.delenv('AGENT_BACKEND', raising=False)
    lab = SimpleNamespace(model='qwen', url='http://127.0.0.1:11434', record=lambda *a, **k: None)
    sessions.autonomous_answer(lab, [{'role': 'user', 'content': 'hi'}], [], None, {'temperature': 0.7, 'seed': 3})
    sessions.autonomous_answer(lab, [{'role': 'user', 'content': 'hi'}], [], None)
    assert captured[0]['temperature'] == 0.7 and captured[0]['seed'] == 3
    assert captured[1]['temperature'] == 0


def test_answering_model_without_cli_is_refused_before_starting(monkeypatch, tmp_path):
    manager = benchmark.BenchmarkJobs(tmp_path)
    monkeypatch.setattr(api, 'jobs', manager)
    monkeypatch.setattr(benchmark, 'cli_path', lambda backend: None)
    response = TestClient(api.app).post('/benchmarks', json={'tasks': ['user_task_30']})
    assert response.status_code == 400 and 'Answering model codex' in response.json()['detail']
    assert not manager.runs.exists()
