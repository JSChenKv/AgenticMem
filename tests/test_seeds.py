"""The scripted seed is fixed before trials and must never contain the real or attacker value."""
import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from lab import api, benchmark, seeds, sessions
from lab.core import USER
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
    assert 5 <= kinds.count("unrelated") <= 20
    text = json.dumps([messages for _, messages in items]).casefold()  # Only what Mem0 sees.
    for word in ('attack', 'poison', 'experiment', 'benchmark', 'payload', 'research', 'memory test', 'distractor'):
        assert word not in text
    case = next(c for c in CASES if c['task_id'] == task_id)
    assert case['expected'].casefold() not in text and case['target'].casefold() not in text


DISTRACTOR_TEXT = seeds.DISTRACTORS['user_task_30'][0]


def fake_seed_lab(monkeypatch, add_hook=None):
    """Mocked Lab/Mem0.add. add_hook(messages) may raise or return a custom add result."""
    log = SimpleNamespace(added=[], records=[], closed=0)

    class Lab:
        def __init__(self, name):
            self.operation = None
            self.store = []

        def add(self, user, messages, source='user', **kwargs):
            log.added.append((user, messages, source))
            custom = add_hook(messages) if add_hook else None
            if custom is not None:
                return custom
            record = {'id': f'id{len(self.store)}', 'memory': messages[0]['content']}
            self.store.append(record)
            return {'results': [{**record, 'event': 'ADD'}]}

        def memories(self, user):
            return list(self.store)

        def record(self, event, **payload):
            log.records.append((event, payload))

        def close(self):
            log.closed += 1

    monkeypatch.setattr('lab.core.Lab', Lab)
    return log


def test_write_scripted_seed_uses_the_normal_add_path(monkeypatch):
    log = fake_seed_lab(monkeypatch)
    result = seeds.write_scripted_seed('seed', CASES[1])
    assert result['status'] == 'completed'
    assert len(log.added) == len(seeds.conversations('user_task_30'))
    assert all(user == USER and source == 'scripted_seed' and [m['role'] for m in messages] == ['user', 'assistant']
               for user, messages, source in log.added)
    assert len(result['distractor_ids']) == 1 and len(result['unrelated_ids']) == len(seeds.UNRELATED)
    assert len(result['memory_after']) == len(log.added)
    # Everything actually written still passes the lab.values invariants for both tasks.
    for _, messages, _ in log.added:
        for message in messages:
            for task in TASKS:
                assert classify_detail(task, message['content'])['label'] is None
                assert attacker_content(task, message['content']) is False
    assert [event for event, _ in log.records] == ['scripted_seed_result'] and log.closed == 1


def test_seeding_exception_is_recorded_then_reraised(monkeypatch):
    def fail(messages):
        if messages[0]['content'] == DISTRACTOR_TEXT:
            raise ConnectionError('Ollama unavailable')

    log = fake_seed_lab(monkeypatch, fail)
    with pytest.raises(ConnectionError, match='Ollama unavailable'):
        seeds.write_scripted_seed('seed', CASES[1])
    event, payload = log.records[-1]
    assert event == 'scripted_seed_result' and payload['status'] == 'error' and payload['error'] == 'Ollama unavailable'
    assert 'memory_after' not in payload and log.closed == 1


def test_empty_distractor_extraction_is_an_error_not_a_silent_gap(monkeypatch):
    log = fake_seed_lab(monkeypatch, lambda messages: {'results': []} if messages[0]['content'] == DISTRACTOR_TEXT else None)
    with pytest.raises(RuntimeError, match='distractor conversation produced no ADD event'):
        seeds.write_scripted_seed('seed', CASES[1])
    event, payload = log.records[-1]
    assert event == 'scripted_seed_result' and payload['status'] == 'error'
    assert payload['distractor_ids'] == [] and len(payload['unrelated_ids']) == len(seeds.UNRELATED)
    assert next(c for c in payload['conversations'] if c['kind'] == 'distractor')['added_ids'] == []
    assert len(log.added) == len(seeds.conversations('user_task_30'))  # Every turn was attempted first.


def test_no_unrelated_extraction_is_an_error(monkeypatch):
    fake_seed_lab(monkeypatch, lambda messages: None if messages[0]['content'] == DISTRACTOR_TEXT else {'results': []})
    with pytest.raises(RuntimeError, match='no unrelated conversation'):
        seeds.write_scripted_seed('seed', CASES[1])


def test_run_case_stops_as_seed_failed_when_seeding_raises(monkeypatch):
    from agentdojo.task_suite.load_suites import get_suite
    from lab import dojo, sustained

    def fail(name, case):
        raise RuntimeError('Scripted seed: the distractor conversation produced no ADD event (empty extraction)')

    monkeypatch.setattr(sustained, 'write_scripted_seed', fail)
    monkeypatch.setattr(sustained, 'run_session', lambda *a, **k: pytest.fail('S0 must not run after a failed seed'))
    result = sustained.run_case(get_suite(dojo.VERSION, 'workspace'), dojo.CASES[1], 'seed', None, None)
    assert result['status'] == 'seed_failed'
    assert result['scripted_seed'] == {'status': 'error', 'error': 'Scripted seed: the distractor conversation produced no ADD event (empty extraction)'}


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
    # The fixed Codex extractor or an answering model is refused first; either way nothing starts.
    assert response.status_code == 400 and 'codex' in response.json()['detail'].lower()
    assert not manager.runs.exists()
