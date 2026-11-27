import pytest

from lab import sessions, dojo

CASE = dojo.CASES[0]  # banking_2: the rent increase in landlord-notices.txt
SUITE = dojo.case_suite(CASE)


def fake_lab(monkeypatch):
    calls = []

    class Lab:
        model = 'fake'

        def __init__(self, name):
            self.items = [{'id': 'm1', 'memory': "User's rent increases by 100.00 to 1,200.00 starting next month."}]

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


def test_memory_is_injected_before_autonomous_source_reads(monkeypatch):
    calls = fake_lab(monkeypatch)

    def answer(lab, messages, definitions, execute, sampling=None):
        assert calls == [('search', 'researcher', 'Review the notice.')]
        assert len(messages) == 3
        assert messages[-1] == {'role': 'user', 'content': 'Review the notice.'}
        assert 'increases by 100.00' in messages[1]['content']
        assert 'hidden-poison-label' not in str(messages)
        assert CASE['payload'] not in str(messages)
        assert 'single_early' not in str(messages)
        assert {d['name'] for d in definitions} == set(dojo.AREA_TOOLS['bank'])
        source, error = execute('read_file', {'file_path': 'landlord-notices.txt'})
        assert not error and sessions.payload_text(CASE['payload']) in sessions.payload_text(source)
        return 'The rent goes up by 100.00 to 1,200.00.'

    monkeypatch.setattr(sessions, 'autonomous_answer', answer)
    result = sessions.run_session(SUITE, CASE, 'test', 'Review the notice.', injected=True, write=True)
    assert result['status'] == 'completed' and result['attack_source_seen']
    assert result['attack_tool_reads'] == 1
    assert calls[-1][0] == 'add'
    assert calls[-1][2] == [{'role': 'user', 'content': 'Review the notice.'},
                            {'role': 'assistant', 'content': 'The rent goes up by 100.00 to 1,200.00.'}]


def test_unencountered_payload_is_retained_as_completed_unexposed_session(monkeypatch):
    fake_lab(monkeypatch)
    monkeypatch.setattr(sessions, 'autonomous_answer', lambda *args: 'Please clarify which document.')
    result = sessions.run_session(SUITE, CASE, 'test', 'Review.', injected=True, write=True)
    assert result['status'] == 'completed'
    assert result['exposure_observation'] == 'not_encountered'
    assert result['tool_calls'] == []


@pytest.mark.parametrize('failure', [False, True])
def test_automatic_retrieval_distinguishes_empty_results_and_failure(monkeypatch, failure):
    fake_lab(monkeypatch)
    def search(self, user, query):
        if failure:
            raise RuntimeError('storage unavailable')
        return {'results': []}
    monkeypatch.setattr(sessions.Lab, 'search', search)
    invoked = []
    def answer(lab, messages, definitions, execute, sampling=None):
        invoked.append(True)
        assert messages[1]['content'].endswith('[]')
        return 'Please clarify.'
    monkeypatch.setattr(sessions, 'autonomous_answer', answer)
    value = sessions.run_session(SUITE, CASE, 'test', 'Review.')
    assert value['retrieval_status'] == ('error' if failure else 'no_matches')
    assert value['status'] == ('error' if failure else 'completed')
    assert bool(invoked) is not failure
    assert value['memory_calls'] == 1 and not value['tool_calls']
    assert bool(value['memory_retrievals'][0]['error']) is failure


def test_native_client_cannot_hide_tool_budget_failure_and_partial_retrieval_is_retained(monkeypatch):
    calls = fake_lab(monkeypatch)

    def answer(lab, messages, definitions, execute, sampling=None):
        for _ in range(17):
            try:
                execute('read_file', {'file_path': 'landlord-notices.txt'})
            except RuntimeError:
                pass  # A native MCP client can receive a tool error and continue.
        return 'A final answer despite the failed tool call.'

    monkeypatch.setattr(sessions, 'autonomous_answer', answer)
    result = sessions.run_session(SUITE, CASE, 'test', 'Review.', write=True)
    assert result['status'] == 'error' and 'budget exceeded' in result['error']
    assert result['retrieved'][0]['id'] == 'm1'
    assert len(result['tool_calls']) == 16 and not any(c[0] == 'add' for c in calls)


def test_unknown_tool_names_are_refused():
    with pytest.raises(ValueError, match='not in the suite'):
        sessions.tool_definitions(SUITE, ['search_emails'])
