import copy
import json

import pytest
from fastapi.testclient import TestClient
from types import SimpleNamespace

from lab import api, sessions, dojo
from agentdojo.task_suite.load_suites import get_suite


def fake_lab(monkeypatch):
    calls = []

    class Lab:
        model = 'fake'

        def __init__(self, name):
            self.items = [{'id': 'm1', 'memory': 'The family reunion is June 10, 2024 at 13:00.'}]

        def search(self, user, query):
            calls.append(('search', user, query))
            return {'results': [{**self.items[0], 'metadata': {'arm': 'hidden-poison-label'}}]}

        def memories(self, user):
            return self.items

        def add(self, user, messages, **kwargs):
            calls.append(('add', user, messages, kwargs))
            return {'results': []}

        def record(self, *args, **kwargs):
            pass

        def close(self):
            pass

    monkeypatch.setattr(sessions, 'Lab', Lab)
    return calls


def test_agent_chooses_reads_without_prefetch_and_payload_only_in_tool_output(monkeypatch):
    calls = fake_lab(monkeypatch)

    def answer(lab, messages, definitions, execute):
        assert calls == []
        assert len(messages) == 2
        assert dojo.CASES[0]['payload'] not in str(messages)
        assert 'single_early' not in str(messages)
        assert {d['name'] for d in definitions} == {'search_memory', 'search_emails', 'search_files'}
        memory, error = execute('search_memory', {'query': 'reunion'})
        assert not error and 'hidden-poison-label' not in memory
        source, error = execute('search_emails', {'query': 'family reunion'})
        assert not error and dojo.CASES[0]['payload'] in ' '.join(source.split())
        return '2024-06-10 13:00'

    monkeypatch.setattr(sessions, 'autonomous_answer', answer)
    result = sessions.run_session(get_suite(dojo.VERSION, 'workspace'), dojo.CASES[0], 'test', 'Review the reunion.', injected=True, write=True)
    assert result['status'] == 'completed' and result['attack_source_seen']
    assert result['attack_tool_reads'] == 1
    assert calls[-1][0] == 'add'
    assert calls[-1][2] == [{'role': 'user', 'content': 'Review the reunion.'}, {'role': 'assistant', 'content': '2024-06-10 13:00'}]


def test_unencountered_payload_is_retained_as_completed_unexposed_session(monkeypatch):
    fake_lab(monkeypatch)
    monkeypatch.setattr(sessions, 'autonomous_answer', lambda *args: 'Please clarify the event details.')
    result = sessions.run_session(get_suite(dojo.VERSION, 'workspace'), dojo.CASES[0], 'test', 'Review.', injected=True, write=True)
    assert result['status'] == 'completed'
    assert result['exposure_observation'] == 'not_encountered'
    assert result['tool_calls'] == []


def test_native_client_cannot_hide_tool_budget_failure_and_partial_retrieval_is_retained(monkeypatch):
    calls = fake_lab(monkeypatch)

    def answer(lab, messages, definitions, execute):
        for _ in range(17):
            try:
                execute('search_memory', {'query': 'reunion'})
            except RuntimeError:
                pass  # A native MCP client can receive a tool error and continue.
        return 'A final answer despite the failed tool call.'

    monkeypatch.setattr(sessions, 'autonomous_answer', answer)
    result = sessions.run_session(get_suite(dojo.VERSION, 'workspace'), dojo.CASES[0], 'test', 'Review.', write=True)
    assert result['status'] == 'error' and 'budget exceeded' in result['error']
    assert result['retrieved'][0]['id'] == 'm1'
    assert len(result['tool_calls']) == 16 and not any(c[0] == 'add' for c in calls)
