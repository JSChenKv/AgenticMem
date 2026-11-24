import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from ollama import ChatResponse, Message
from mem0.llms.ollama import OllamaLLM

from lab import agents, api, core


@pytest.mark.parametrize('backend,model', [('codex', 'codex-model'), ('claude', 'claude-model'), ('ollama', 'local-model')])
def test_follow_copies_provider_and_model(backend, model):
    assert agents.resolve_extraction(backend, model, 'follow') == {'mode': 'follow', 'backend': backend, 'model': model}


def test_defaults_and_explicit_independent_models(monkeypatch):
    monkeypatch.setenv('CODEX_MODEL', 'codex-default')
    monkeypatch.setenv('CHAT_MODEL', 'qwen2.5:7b')
    assert agents.resolve_extraction('codex')['model'] == 'gpt-6-luna'
    assert agents.resolve_extraction('codex', '', 'follow')['model'] == 'codex-default'
    for task in ('ollama', 'codex', 'claude'):
        assert agents.resolve_extraction(task, 'task-model') == {
            'mode': 'codex', 'backend': 'codex', 'model': 'gpt-6-luna'}
    assert agents.resolve_extraction('codex', 'task-model', 'ollama') == {
        'mode': 'ollama', 'backend': 'ollama', 'model': 'qwen2.5:7b'}
    assert agents.resolve_extraction('codex', 'task-model', 'claude', 'extract-model')['model'] == 'extract-model'
    assert agents.resolve_extraction('codex', 'task-model', 'codex')['model'] == 'gpt-6-luna'
    with pytest.raises(ValueError, match='independent'):
        agents.resolve_extraction('codex', 'task-model', 'follow', 'different-model')


@pytest.mark.parametrize('backend', ['codex', 'claude'])
def test_mem0_adapter_routes_extraction_to_cli_without_ollama(monkeypatch, backend):
    calls, trace = [], []
    lab = object.__new__(core.Lab)
    lab.record = lambda event, **values: trace.append((event, values))
    lab.memory = SimpleNamespace(llm=OllamaLLM({'model': 'old-qwen'}))
    lab.client = SimpleNamespace(list=lambda: pytest.fail('CLI extraction must not call local chat model or list it'))

    class Client:
        def __init__(self, selected, model, record):
            assert (selected, model) == (backend, 'chosen-model')

        def chat(self, **kwargs):
            calls.append(kwargs)
            return ChatResponse(message=Message(role='assistant', content='{"memory":[{"text":"User prefers Python"}]}'))

    monkeypatch.setattr(core, 'CliClient', Client)
    lab.configure_extraction(agents.resolve_extraction(backend, 'chosen-model', 'follow'))
    messages = [{'role': 'system', 'content': 'Extract facts.'}, {'role': 'user', 'content': 'I prefer Python.'}]
    output = lab.memory.llm.generate_response(messages, response_format={'type': 'json_object'})
    assert json.loads(output)['memory'][0]['text'] == 'User prefers Python'
    assert calls[0]['model'] == 'chosen-model' and calls[0]['format'] == 'json'
    assert calls[0]['messages'][0] == messages[0]
    assert trace[-1][1]['backend'] == backend and trace[-1][1]['stage'] == 'memory_extraction'


@pytest.mark.parametrize('content', ['not-json', '{}', '{"memory":"text"}', '{"memory":["text"]}', '{"memory":[{"text":""}]}'])
def test_malformed_extraction_is_error_not_empty_success(content):
    client = SimpleNamespace(chat=lambda **kwargs: ChatResponse(message=Message(role='assistant', content=content)))
    traced = core.TracedClient(client, lambda *args, **kwargs: None, 'memory_extraction', 'codex')
    with pytest.raises(ValueError):
        traced.chat(messages=[], format='json')


def test_traced_client_keeps_an_explicit_session_seed(monkeypatch):
    monkeypatch.setenv('SEED', '42')
    calls = []
    client = core.TracedClient(SimpleNamespace(chat=lambda **kwargs: calls.append(kwargs) or
                                               ChatResponse(message=Message(role='assistant', content='ok'))),
                               lambda *a, **k: None, 'agent')
    client.chat(messages=[], options={'temperature': 0, 'seed': 3})
    client.chat(messages=[])  # Mem0 extraction sends no seed and gets SEED.
    assert [c['options']['seed'] for c in calls] == [3, 42]


def test_cli_extraction_failure_never_falls_back():
    calls = []
    def fail(**kwargs):
        calls.append(kwargs)
        raise RuntimeError('CLI unavailable')
    client = core.TracedClient(SimpleNamespace(chat=fail), lambda *a, **k: None, 'memory_extraction', 'codex')
    with pytest.raises(RuntimeError, match='CLI unavailable'):
        client.chat(messages=[], format='json')
    assert len(calls) == 1


def test_chat_write_and_memory_endpoint_share_selected_extractor(monkeypatch):
    calls = []
    class Lab:
        def __init__(self, experiment):
            pass
        def ask(self, user, text, mode, history, **kwargs):
            calls.append(('ask', kwargs))
            return {'answer': 'ok'}
        def add(self, user, messages, **kwargs):
            calls.append(('add', kwargs))
            return {'results': []}
    monkeypatch.setattr(api, 'Lab', Lab)
    monkeypatch.setattr(api, 'labs', {})
    monkeypatch.setattr(api, 'check_cli', lambda backend: None)
    client = TestClient(api.app)
    query = {'text': 'I prefer Python', 'mode': 'write', 'agent_backend': 'codex', 'agent_model': 'task-model'}
    assert client.post('/chat', json=query).status_code == 200
    assert calls[-1][1]['memory_backend'] == 'codex'
    assert client.post('/memories', json=query).status_code == 200
    assert calls[-1][1]['extraction'] == {'mode': 'codex', 'backend': 'codex', 'model': 'gpt-6-luna'}
    assert client.post('/memories', json={**query, 'memory_backend': 'claude', 'memory_model': 'extract-model'}).status_code == 200
    assert calls[-1][1]['extraction'] == {'mode': 'claude', 'backend': 'claude', 'model': 'extract-model'}


def test_invalid_extraction_inputs_fail_before_any_work():
    client = TestClient(api.app)
    for invalid in ({'memory_backend': 'shell'}, {'memory_model': '--help'}, {'memory_model': 'other', 'memory_backend': 'follow'}):
        assert client.post('/chat', json={'text': 'hi', **invalid}).status_code == 422
        assert client.post('/benchmarks', json={'tasks': ['user_task_14'], **invalid}).status_code == 422


def test_chat_write_routes_default_and_control_without_reusing_cached_extractor():
    lab = object.__new__(core.Lab)
    lab.agent_backend, lab.agent_model, lab.model = 'codex', 'task-model', 'qwen2.5:7b'
    lab.default_extraction = agents.resolve_extraction('codex', 'task-model')
    lab.agent_client = SimpleNamespace(chat=lambda **kw: ChatResponse(message=Message(role='assistant', content='Noted')))
    lab.search = lambda *a: {'results': []}
    lab.record = lambda *a, **kw: None
    calls = []
    lab.add = lambda *a, **kw: calls.append(kw['extraction']) or {'results': []}
    lab.ask('user', 'I prefer Python', mode='write')
    lab.ask('user', 'I prefer tea', mode='write', memory_backend='ollama', memory_model='local-extractor')
    lab.ask('user', 'I prefer coffee', mode='write')
    assert [c['backend'] for c in calls] == ['codex', 'ollama', 'codex']
    assert [c['model'] for c in calls] == ['gpt-6-luna', 'local-extractor', 'gpt-6-luna']


def test_api_defaults_are_explicit_even_with_legacy_environment(monkeypatch):
    monkeypatch.setenv('MEMORY_BACKEND', 'follow')
    monkeypatch.setenv('MEMORY_MODEL', 'old-model')
    query = api.Query(text='Hello')
    options = api.execution_options(query)
    assert options['memory_backend'] == 'codex'
    assert agents.resolve_extraction(**options)['model'] == 'gpt-6-luna'


def test_memory_search_uses_sdk_defaults_and_keeps_user_scope():
    # v6 uses the Mem0 2.2.1 SDK defaults (as main v5), passed explicitly.
    calls = []
    lab = object.__new__(core.Lab)
    lab.memory = SimpleNamespace(search=lambda query, **options: calls.append((query, options)) or {'results': []})
    lab.record = lambda *a, **kw: None
    assert lab.search('alice', 'Hawaii') == {'results': []}
    assert calls == [('Hawaii', {'filters': {'user_id': 'alice'}, 'top_k': 20, 'threshold': 0.1, 'explain': False})]
