import copy
import json

import pytest
from fastapi.testclient import TestClient
from types import SimpleNamespace

from lab import api, repeated, dojo
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

    monkeypatch.setattr(repeated, 'Lab', Lab)
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

    monkeypatch.setattr(repeated, 'autonomous_answer', answer)
    result = repeated.run_session(get_suite(dojo.VERSION, 'workspace'), dojo.CASES[0], 'test', 'Review the reunion.', injected=True, write=True)
    assert result['status'] == 'completed' and result['attack_source_seen']
    assert result['attack_tool_reads'] == 1
    assert calls[-1][0] == 'add'
    assert calls[-1][2] == [{'role': 'user', 'content': 'Review the reunion.'}, {'role': 'assistant', 'content': '2024-06-10 13:00'}]


def test_unencountered_payload_is_retained_as_completed_unexposed_session(monkeypatch):
    fake_lab(monkeypatch)
    monkeypatch.setattr(repeated, 'autonomous_answer', lambda *args: 'Please clarify the event details.')
    result = repeated.run_session(get_suite(dojo.VERSION, 'workspace'), dojo.CASES[0], 'test', 'Review.', injected=True, write=True)
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

    monkeypatch.setattr(repeated, 'autonomous_answer', answer)
    result = repeated.run_session(get_suite(dojo.VERSION, 'workspace'), dojo.CASES[0], 'test', 'Review.', write=True)
    assert result['status'] == 'error' and 'budget exceeded' in result['error']
    assert result['retrieved'][0]['id'] == 'm1'
    assert len(result['tool_calls']) == 16 and not any(c[0] == 'add' for c in calls)


def test_memory_off_keeps_schema_but_never_reads_storage_and_final_sources_are_clean(monkeypatch):
    calls = fake_lab(monkeypatch)

    def answer(lab, messages, definitions, execute):
        assert definitions[0] == repeated.MEMORY_TOOL
        assert execute('search_memory', {'query': 'reunion'}) == ('[]', None)
        source, error = execute('search_emails', {'query': 'family reunion'})
        assert dojo.CASES[0]['payload'] not in ' '.join(source.split())
        return json.dumps({'body': '2024-06-10 13:00', 'conflict': False, 'memory_ids_used': []})

    monkeypatch.setattr(repeated, 'autonomous_answer', answer)
    result = repeated.run_session(get_suite(dojo.VERSION, 'workspace'), dojo.CASES[0], 'test', 'Draft.', kind='reminder', memory_off=True)
    assert result['status'] == 'completed' and result['retrieved'] == []
    assert calls == []  # Neither storage retrieval nor add() was invoked.


def test_memory_only_rejects_workspace_tools_and_fabricated_citations(monkeypatch):
    fake_lab(monkeypatch)

    def answer(lab, messages, definitions, execute):
        assert [d['name'] for d in definitions] == ['search_memory']
        assert execute('search_files', {'query': 'x'})[1]
        return json.dumps({'body': 'Unknown', 'conflict': False, 'memory_ids_used': ['not-retrieved']})

    monkeypatch.setattr(repeated, 'autonomous_answer', answer)
    result = repeated.run_session(get_suite(dojo.VERSION, 'workspace'), dojo.CASES[0], 'test', 'Draft.', kind='reminder', evaluation_tools='memory_only')
    assert result['status'] == 'error' and 'not retrieved' in result['error']


def test_episode_schedules_and_clean_timeline_restoration(monkeypatch):
    states, visits, clones = {}, [], []

    def session(suite, case, name, prompt, **kwargs):
        visits.append((name, kwargs.copy()))
        states.setdefault(name, [])
        if kwargs.get('write'):
            states[name].append(bool(kwargs.get('injected')))
        return {'status': 'completed', 'native_utility': True, 'workspace_calls': 1,
                'memory_after': [{'id': 'seed'}], 'target_claim_record_ids': [],
                'attack_source_seen': bool(kwargs.get('injected')), 'attack_tool_reads': int(bool(kwargs.get('injected'))),
                'clean_correct': True, 'target_content_present': False}

    def hashes(name):
        return {'history.db': json.dumps(states[name])}

    def clone(source, destination):
        states[destination] = copy.deepcopy(states[source])
        clones.append((source, destination))
        return hashes(destination)

    monkeypatch.setattr(repeated, 'run_session', session)
    result = repeated.run_case(get_suite(dojo.VERSION, 'workspace'), dojo.CASES[0], 'seed', clone, hashes)
    assert len(visits) == 25  # S0 + 4 schedules * 3 slots + 6 conditions * 2 probes.
    assert result['status'] == 'completed'
    for arm, schedule in repeated.SCHEDULES.items():
        branch = result['branches'][arm]
        assert states[branch['experiment']] == [False, *map(bool, schedule)]
        assert branch['observed_exposure_sessions'] == sum(schedule)
    for group in result['evaluations'].values():
        assert len(group) == 6
        assert group['repeated_restored']['snapshot_before'] == result['branches']['clean']['final_snapshot_hashes']
        assert group['repeated_memory_off']['snapshot_before'] == result['branches']['repeated']['final_snapshot_hashes']
    assert sum(v.get('memory_off', False) for _, v in visits) == 2
    assert len({name for name, kwargs in visits if kwargs.get('kind')}) == 12


def test_repeated_api_fields_and_defaults(monkeypatch):
    calls = []
    monkeypatch.setattr(api, 'jobs', SimpleNamespace(start=lambda *args: calls.append(args) or {'run_id': 'test'}))
    client = TestClient(api.app)
    response = client.post('/benchmarks', json={'tasks': ['user_task_14'], 'workflow': 'autonomous', 'evaluation_tools': 'memory_only'})
    assert response.status_code == 202 and calls[0][-3:] == ('autonomous', 0, 'memory_only')
    assert client.post('/benchmarks', json={'tasks': ['user_task_14'], 'evaluation_tools': 'shell'}).status_code == 422


def test_claude_memory_tool_is_explicitly_allowed(tmp_path):
    from lab.agents import claude_command
    server = {'command': 'python', 'args': [], 'env': {}, 'allowed_tools': ['search_memory']}
    command = claude_command('claude', tmp_path, tmp_path, '', server)
    assert command[command.index('--allowedTools') + 1] == 'mcp__workspace__search_memory'
    config = json.loads((tmp_path / 'mcp.json').read_text())
    assert 'allowed_tools' not in config['mcpServers']['workspace']


def test_shared_export_retains_causal_checks_but_excludes_raw_tools_and_local_spaces():
    from scripts.export_results import export_repeated, render_repeated
    session = {'session_id': 's1', 'status': 'completed', 'slot': 1, 'answer': 'Use the original invitation.',
               'attack_source_seen': True, 'memory_calls': 1, 'workspace_calls': 1,
               'tool_calls': [{'tool': 'search_emails', 'arguments': {'query': 'reunion'},
                               'output': 'PRIVATE RAW OUTPUT', 'attack_payload_seen': True}],
               'memory_after': [{'id': 'm1', 'memory': 'June 10', 'metadata': {'private': 'hidden'}}],
               'write_events': {'results': [{'id': 'm1', 'memory': 'June 10', 'event': 'ADD'}]}}
    source = {'protocol': 'autonomous_repeated_v1', 'status': 'completed', 'evaluation_tools': 'workspace',
              'seed': session, 'branches': {'repeated': {'experiment': 'PRIVATE LOCAL SPACE', 'schedule': [1, 1, 1],
                'status': 'completed', 'sessions': [session], 'observed_exposure_sessions': 1,
                'initial_snapshot_hashes': {'history.db': 'seed-hash'}, 'final_snapshot_hashes': {'history.db': 'end-hash'}}},
              'evaluations': {'plan': {'repeated_restored': {**session, 'source_memory_arm': 'clean',
                'snapshot_before': {'history.db': 'clean-end-hash'}, 'memory_unchanged': True,
                'artifact': {'title': 'Reunion', 'date': '2024-06-10', 'time': '13:00', 'location': '',
                             'notes': '', 'conflict': False, 'memory_ids_used': ['m1']}}}}, 'comparisons': {}}
    exported = export_repeated(source)
    assert 'PRIVATE' not in json.dumps(exported) and 'metadata' not in json.dumps(exported)
    assert exported['branches']['repeated']['sessions'][0]['tool_calls'][0]['attack_payload_seen']
    assert exported['evaluations']['plan']['repeated_restored']['snapshot_before'] == {'history.db': 'clean-end-hash'}
    report = '\n'.join(render_repeated(exported))
    assert 'repeated (111)' in report and 'repeated_restored' in report and '2024-06-10' in report
    assert 'Use the original invitation.' in report


def test_partial_shared_export_reports_error_without_inventing_artifact():
    from scripts.export_results import export_repeated, render_repeated
    source = {'protocol': 'autonomous_repeated_v1', 'status': 'running', 'evaluation_tools': 'workspace',
              'branches': {}, 'evaluations': {'plan': {'repeated': {'status': 'error', 'error': 'Invalid JSON'}}}}
    exported = export_repeated(source)
    report = '\n'.join(render_repeated(exported))
    assert 'Invalid JSON' in report and 'artifact' not in exported['evaluations']['plan']['repeated']
