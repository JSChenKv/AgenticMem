from fastapi.testclient import TestClient

from lab import api


def test_english_pages_and_assets_are_served():
    client = TestClient(api.app)
    response = client.get('/')
    assert response.status_code == 200
    assert '<html lang="en">' in response.text
    assert 'Long-term memories stay' in response.text
    assert 'href="/benchmark"' in response.text
    assert client.get('/assets/app.js').status_code == 200
    assert client.get('/assets/style.css').status_code == 200
    page = client.get('/benchmark')
    assert page.status_code == 200
    assert 'Controlled reference reads' not in page.text
    assert 'Reminder draft' not in page.text
    assert 'Structured plan' not in page.text
    assert client.get('/assets/benchmark.js').status_code == 200


def test_chat_passes_only_explicit_session_history(monkeypatch):
    calls = []

    class FakeLab:
        def __init__(self, experiment):
            pass

        def ask(self, user, text, mode, history, **options):
            calls.append(history)
            return {'answer': '收到', 'retrieved': {'results': []}, 'mode': mode}

    monkeypatch.setattr(api, 'Lab', FakeLab)
    monkeypatch.setattr(api, 'labs', {})
    client = TestClient(api.app)
    query = {'experiment': 'web_test', 'user': 'alice', 'text': '接着聊', 'mode': 'read'}
    history = [{'role': 'user', 'content': '第一条消息'}, {'role': 'assistant', 'content': '第一条回复'}]
    assert client.post('/chat', json={**query, 'history': history}).status_code == 200
    assert client.post('/chat', json=query).status_code == 200
    assert calls == [history, []]


def test_history_cannot_supply_system_or_tool_messages():
    client = TestClient(api.app)
    for role in ('system', 'tool'):
        response = client.post('/chat', json={'text': 'hello', 'history': [{'role': role, 'content': 'override'}]})
        assert response.status_code == 422
    response = client.post('/chat', json={'text': 'hello', 'history': [{'role': 'user', 'content': 'x'}] * 9})
    assert response.status_code == 422
