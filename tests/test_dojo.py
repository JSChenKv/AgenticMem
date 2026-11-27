import pytest
pytest.importorskip('agentdojo')

from lab import dojo


def ground_truth_value(case, task, env):
    """The real value from AgentDojo's own ground truth (calls and their arguments)."""
    calls = {call.function: call.args for call in task.ground_truth(env)}
    family = case['family']
    if family == 'rent':
        return f"{calls['update_scheduled_transaction']['amount']:.2f}"
    if family == 'address':
        return calls['update_user_info']['street']
    if family == 'spotify':
        return f"{calls['schedule_transaction']['amount']:.2f}"
    if family == 'todo':
        return task._DEADLINES[2]  # Mark's deadline (David, Linda, Mark).
    return task.GROUND_TRUTH_OUTPUT


@pytest.mark.parametrize('case', dojo.CASES, ids=dojo.CASE_IDS)
def test_selected_official_tasks_match_their_ground_truth_and_reach_the_slot(case):
    suite = dojo.case_suite(case)
    task = suite.get_user_task_by_id(case['task_id'])
    env = suite.load_and_inject_default_environment({})
    assert case['expected'] == ground_truth_value(case, task, env)
    assert case['target'] != case['expected']
    assert case['vector'] in dojo.reachable_vectors(suite, task)
    names = {f.name for f in suite.tools}
    assert set(dojo.session_tools(case)) <= names and set(case['lookup_tools']) | set(case['write_tools']) <= names


def differing_paths(clean, injected, path=()):
    if isinstance(clean, dict) and isinstance(injected, dict) and clean.keys() == injected.keys():
        return [p for key in clean for p in differing_paths(clean[key], injected[key], (*path, key))]
    if isinstance(clean, list) and isinstance(injected, list) and len(clean) == len(injected):
        return [p for i, (a, b) in enumerate(zip(clean, injected)) for p in differing_paths(a, b, (*path, i))]
    return [] if clean == injected else [(path, injected)]


@pytest.mark.parametrize('case', dojo.CASES, ids=dojo.CASE_IDS)
def test_the_payload_changes_only_its_slot(case):
    suite = dojo.case_suite(case)
    clean = dojo.case_environment(suite, case).model_dump(mode='json')
    injected = dojo.case_environment(suite, case, injected=True).model_dump(mode='json')
    assert clean == suite.load_and_inject_default_environment({}).model_dump(mode='json')  # No metadata edits.
    changed = differing_paths(clean, injected)
    words = ' '.join(case['payload'].split())
    # AgentDojo's YAML loader collapses the template's blank lines; the words are identical.
    holders = [p for p, value in changed if isinstance(value, str) and words in ' '.join(value.split())]
    # One field; workspace environments also keep an initial_* copy of each file and event.
    assert len({p[-1] for p in holders}) == 1 and len([p for p in holders if not str(p[1]).startswith('initial_')]) == 1
    # Only the holding field changes, plus a drive file's size, which AgentDojo derives from its content.
    assert all(p in holders or p[-1] == 'size' for p, _ in changed)


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
