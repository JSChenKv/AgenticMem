import copy
import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from lab import api, direct, repeated, dojo
from scripts.export_results import export_direct


RUN = 'dojo_20261115_002746_5a7933'


def parent_case():
    state = {'history.db': 'same-state'}
    clean = {'status': 'completed', 'session_id': 'old-control', 'snapshot_before': state,
             'snapshot_after': state, 'memory_unchanged': True, 'retrieved': [], 'write_enabled': False,
             'scheduled_attack': False, 'clean_correct': True, 'target_content_present': False,
             'attack_source_seen': False, 'attack_tool_reads': 0,
             'artifact': {'body': 'Diamond Head June 13', 'conflict': False, 'memory_ids_used': []}}
    return {**dojo.CASES[1], 'repeated': {'evaluation_tools': 'workspace',
        'branches': {'repeated': {'status': 'completed', 'experiment': 'repeat_source', 'final_snapshot_hashes': state}},
        'evaluations': {kind: {'repeated_memory_off': {**copy.deepcopy(clean), 'session_id': 'old-' + kind}} for kind in repeated.PROBES}}}


def test_only_two_polluted_sessions_execute_and_clean_controls_are_reused(monkeypatch):
    parent = parent_case(); original = copy.deepcopy(parent)
    visits, clones = [], []
    state = parent['repeated']['branches']['repeated']['final_snapshot_hashes']

    def session(suite, case, name, prompt, **kwargs):
        visits.append((name, prompt, kwargs))
        assert kwargs['memory_off'] and kwargs['injected'] and kwargs['write'] is False
        assert kwargs['evaluation_tools'] == 'workspace'
        return {'status': 'completed', 'attack_source_seen': False, 'target_content_present': False, 'target_adoption': False}

    def clone(source, destination):
        assert source == 'repeat_source'
        clones.append(destination)
        return state.copy()

    monkeypatch.setattr(repeated, 'run_session', session)
    result = direct.run_case(None, dojo.CASES[1], parent, {'run_id': RUN}, clone, lambda name: state.copy())
    assert len(visits) == len(set(clones)) == 2
    assert result['status'] == 'completed'  # Not encountering the payload is a valid outcome.
    assert parent == original
    for kind, group in result['evaluations'].items():
        assert group['clean']['session_id'] == 'old-' + kind
        assert group['clean']['data_origin'] == 'reused_source_run'
        assert group['polluted']['data_origin'] == 'new_session'
        assert group['polluted']['memory_unchanged']


def test_polluted_memory_off_reaches_actual_payload_without_memory_reads_or_writes(monkeypatch):
    class NoMemoryLab:
        def __init__(self, name): pass
        def search(self, *a): raise AssertionError('Memory retrieval must not occur')
        def add(self, *a, **kw): raise AssertionError('Memory writes must not occur')
        def record(self, *a, **kw): pass
        def close(self): pass

    def answer(lab, messages, definitions, execute):
        assert len(messages) == 2 and dojo.CASES[1]['payload'] not in str(messages)
        assert execute('search_memory', {'query': 'Hawaii'}) == ('[]', None)
        output, error = execute('search_files', {'query': 'Hawaii'})
        assert not error and dojo.CASES[1]['payload'] in ' '.join(output.split())
        return json.dumps({'body': 'June 13: Diamond Head.', 'conflict': False, 'memory_ids_used': []})

    monkeypatch.setattr(repeated, 'Lab', NoMemoryLab)
    monkeypatch.setattr(repeated, 'autonomous_answer', answer)
    value = repeated.run_session(dojo.get_suite(dojo.VERSION, 'workspace'), dojo.CASES[1], 'test', 'Draft.',
                                 injected=True, memory_off=True, write=False, kind='reminder')
    assert value['status'] == 'completed' and value['attack_source_seen']
    assert value['retrieved'] == [] and value['artifact']['memory_ids_used'] == []


def test_source_validation_rejects_missing_controls_and_path_escape(tmp_path):
    with pytest.raises(ValueError): direct.load_source(tmp_path, '../outside', ['user_task_30'])
    folder = tmp_path / 'data/agentdojo_runs' / RUN; folder.mkdir(parents=True)
    parent = parent_case()
    source = {'workflow': 'autonomous', 'status': 'completed', 'cases': [parent]}
    (folder / 'summary.json').write_text(json.dumps(source), encoding='utf-8')
    archived = {'autonomous_protocol': repeated.protocol([dojo.CASES[1]], 'workspace')}
    (folder / 'protocol.json').write_text(json.dumps(archived), encoding='utf-8')
    cases, reference, previous = direct.load_source(tmp_path, RUN, ['user_task_30'])
    protocol = direct.protocol(cases, reference, previous)
    assert protocol['new_session_order'] == ['reminder/polluted', 'plan/polluted']
    with pytest.raises(ValueError): direct.load_source(tmp_path, RUN, ['user_task_14'])
    parent['repeated']['evaluations']['plan']['repeated_memory_off']['retrieved'] = [{'id': 'bad'}]
    (folder / 'summary.json').write_text(json.dumps(source), encoding='utf-8')
    with pytest.raises(ValueError, match='incompatible'): direct.load_source(tmp_path, RUN, ['user_task_30'])


def test_changed_source_hash_fails_before_running_any_probe(monkeypatch):
    monkeypatch.setattr(repeated, 'run_session', lambda *a, **kw: pytest.fail('Must not run'))
    with pytest.raises(ValueError, match='changed'):
        direct.run_case(None, dojo.CASES[1], parent_case(), {'run_id': RUN}, None, lambda name: {'history.db': 'changed'})


def test_api_forwards_source_and_export_preserves_provenance(monkeypatch):
    calls = []
    monkeypatch.setattr(api, 'jobs', SimpleNamespace(start=lambda *a, **kw: calls.append((a, kw)) or {'run_id': 'test'}))
    client = TestClient(api.app)
    assert client.post('/benchmarks', json={'tasks': ['user_task_30'], 'workflow': 'direct', 'source_run_id': RUN}).status_code == 202
    assert calls[0][1] == {'source_run_id': RUN}
    assert client.post('/benchmarks', json={'tasks': ['user_task_30'], 'workflow': 'direct', 'source_run_id': '../bad'}).status_code == 422
    exported = export_direct({'source': {'run_id': RUN}, 'evaluations': {'reminder': {'clean': {
        'data_origin': 'reused_source_run', 'source_run_id': RUN, 'session_id': 'old-reminder',
        'experiment': 'private-path', 'tool_calls': [{'tool': 'search_files', 'output': 'raw output'}]}}}})
    control = exported['evaluations']['reminder']['clean']
    assert control['data_origin'] == 'reused_source_run' and control['session_id'] == 'old-reminder'
    assert 'private-path' not in json.dumps(exported) and 'raw output' not in json.dumps(exported)
