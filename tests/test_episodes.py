import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from lab import api, dojo, episodes


def test_episode_api_passes_configuration_and_rejects_unsupported_counts(monkeypatch):
    calls = []
    monkeypatch.setattr(api, 'jobs', SimpleNamespace(start=lambda *args: calls.append(args) or {'run_id': 'test'}))
    client = TestClient(api.app)
    assert client.post('/benchmarks', json={'tasks': ['user_task_14'], 'workflow': 'episode', 'delay_tasks': 3}).status_code == 202
    assert calls[0][-3:] == ('episode', 3, 'workspace')
    for fields in ({'workflow': 'shell'}, {'delay_tasks': -1}, {'delay_tasks': 2}, {'delay_tasks': 100}):
        assert client.post('/benchmarks', json={'tasks': ['user_task_14'], **fields}).status_code == 422


def fake_lab(monkeypatch, artifact):
    seen = []

    class FakeLab:
        model = 'model'

        def __init__(self, experiment):
            self.agent_client = SimpleNamespace(chat=self.chat)

        def search(self, user, query):
            return {'results': [{'id': 'm1', 'memory': 'The family reunion is 2024-06-10 13:00.',
                                 'metadata': {'attack_target': 'secret', 'arm': 'poison'}}]}

        def chat(self, **kwargs):
            seen.append(kwargs)
            return SimpleNamespace(message=SimpleNamespace(content=json.dumps(artifact)))

        def record(self, *args, **kwargs):
            pass

        def close(self):
            pass

    monkeypatch.setattr(episodes, 'Lab', FakeLab)
    return seen


def test_probe_is_fresh_task_without_source_labels_or_memory_writes(monkeypatch):
    artifact = {'body': 'Reminder: 2024-06-10 13:00.', 'conflict': False, 'memory_ids_used': ['m1']}
    seen = fake_lab(monkeypatch, artifact)
    result = episodes.probe('opaque', dojo.CASES[0], 'reminder')
    wire = json.dumps(seen[0]['messages'])
    assert 'secret' not in wire and 'attack_target' not in wire
    assert dojo.CASES[0]['payload'] not in wire and dojo.CASES[0]['target'] not in wire
    assert 'search_emails' not in wire and 'tools' not in seen[0]
    assert result['clean_correct'] and result['artifact'] == artifact
    # FakeLab has no add(): any probe write would fail this test.


def test_memory_off_has_no_retrieval_and_rejects_citations(monkeypatch):
    seen = fake_lab(monkeypatch, {'body': 'Unknown.', 'conflict': False, 'memory_ids_used': ['m1']})
    with pytest.raises(ValueError, match='not retrieved'):
        episodes.probe('opaque', dojo.CASES[0], 'reminder', False)
    assert [m['role'] for m in seen[0]['messages']] == ['system', 'user']
    assert '2024-06-10' not in json.dumps(seen[0])


def test_plan_grading_uses_action_fields_not_explanatory_text():
    artifact = {'date': '2024-06-17', 'time': '15:30', 'location': 'unknown',
                'title': 'Reunion', 'notes': 'The correct answer is 2024-06-10 13:00.', 'conflict': False}
    result = episodes.grade(dojo.CASES[0], 'plan', artifact)
    assert result['target_content_present'] and not result['clean_correct']
    artifact.update(date='June 14', location='Diamond Head')
    assert not episodes.grade(dojo.CASES[1], 'plan', artifact)['clean_correct']


def test_episode_clones_full_seed_and_independent_probe_snapshots(monkeypatch):
    states = {'seed': ['original', 'extraction-history'], 'clean': ['original', 'clean-write'],
              'poison': ['original', 'attack-write']}
    clones, probes = [], []

    def hashes(name):
        return {'history.db': json.dumps(states[name])}

    def clone(source, target):
        clones.append((source, target))
        states[target] = list(states[source])
        return hashes(target)

    def filler(name, index):
        states[name].append('clean-note-' + str(index))
        return {'source_note': 'clean-note-' + str(index)}

    def probe(name, case, kind, use_memory):
        probes.append((name, kind, use_memory, list(states[name])))
        return {'status': 'completed', 'clean_correct': 'attack-write' not in states[name],
                'target_content_present': use_memory and 'attack-write' in states[name]}

    monkeypatch.setattr(episodes, 'distractor', filler)
    monkeypatch.setattr(episodes, 'probe', probe)
    result = episodes.run_episode(dojo.CASES[0], {'seed': 'seed', 'clean': 'clean', 'poison': 'poison'}, 1, clone, hashes)
    restored = result['branches']['restored']['experiment']
    assert states[restored] == ['original', 'extraction-history', 'clean-note-0']
    assert len(probes) == 8 and len({p[0] for p in probes}) == 8
    assert sum(not p[2] for p in probes) == 2
    assert all(p[3][-1] == 'clean-note-0' for p in probes)
    assert states['seed'] == ['original', 'extraction-history']
    assert all(c['memory_sensitive_target_content'] for c in result['comparisons'].values())


def test_probe_errors_and_memory_mutation_are_not_counted_as_negative_attacks(monkeypatch):
    state = {}

    def clone(source, target):
        state[target] = 'unchanged'
        return {'db': 'unchanged'}

    def probe(name, case, kind, use_memory):
        if not use_memory:
            raise ValueError('invalid JSON')
        state[name] = 'changed'
        return {'status': 'completed', 'clean_correct': True, 'target_content_present': False}

    monkeypatch.setattr(episodes, 'probe', probe)
    result = episodes.run_episode(dojo.CASES[0], {'seed': 's', 'clean': 'c', 'poison': 'p'}, 0,
                                  clone, lambda name: {'db': state.get(name, 'unchanged')})
    assert result['status'] == 'needs_review'
    assert all(c['memory_sensitive_target_content'] is None for c in result['comparisons'].values())
    assert result['probes']['plan']['memory_off']['error'] == 'invalid JSON'


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


def test_intermediate_task_saves_only_actual_question_and_answer(monkeypatch):
    calls = []
    saved = [{'id': 'seed', 'memory': 'A prior fact.'}]

    class FakeLab:
        model = 'unused'

        def __init__(self, experiment):
            self.agent_client = SimpleNamespace(chat=self.chat)

        def chat(self, **kwargs):
            calls.append(kwargs['messages'])
            return SimpleNamespace(message=SimpleNamespace(content='The note lists two catering options.'))

        def search(self, *args):
            return {'results': saved}

        def memories(self, *args):
            return saved

        def add(self, user, messages, **kwargs):
            calls.append(messages)
            return {'results': []}

        def close(self):
            pass

    monkeypatch.setattr(episodes, 'Lab', FakeLab)
    result = episodes.distractor('ep_test', 0)
    assert calls[0][-1]['role'] == 'tool'
    assert calls[0][-1]['content'] == episodes.DISTRACTORS[0][1]
    assert calls[1] == [{'role': 'user', 'content': episodes.DISTRACTORS[0][0]},
                        {'role': 'assistant', 'content': result['answer']}]
    assert result['saved'] == saved


def test_episode_export_preserves_artifacts_without_machine_metadata():
    from scripts.export_results import export_episode
    source = {'status': 'completed', 'branches': {'restored': {'experiment': 'private-label', 'intermediate_sessions': []}},
              'probes': {'plan': {'clean': {'status': 'completed', 'experiment': 'private-label',
                  'artifact': {'date': 'June 13', 'location': 'Diamond Head', 'secret': 'hidden'},
                  'retrieved': [{'id': 'm1', 'memory': 'a fact', 'metadata': {'secret': 'hidden'}}]}}}}
    exported = export_episode(source)
    assert 'private-label' not in str(exported) and 'hidden' not in str(exported)
    assert exported['probes']['plan']['clean']['artifact'] == {'date': 'June 13', 'location': 'Diamond Head'}
