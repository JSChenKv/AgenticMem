from types import SimpleNamespace
import json

import pytest
pytest.importorskip('agentdojo')
from ollama import ChatResponse, Message

from lab import dojo
from agentdojo.functions_runtime import FunctionsRuntime
from agentdojo.task_suite.load_suites import get_suite


def test_selected_official_tasks_and_attack_entrypoints():
    suite = get_suite(dojo.VERSION, 'workspace')
    for case in dojo.CASES:
        task = suite.get_user_task_by_id(case['task_id'])
        assert task.GROUND_TRUTH_OUTPUT == case['expected']
        assert case['vector'] in dojo.reachable_vectors(suite, task)


def test_readonly_pipeline_blocks_unadvertised_write_tool(tmp_path):
    suite = get_suite(dojo.VERSION, 'workspace')
    env = suite.load_and_inject_default_environment({})
    original = dojo.digest(env.model_dump(mode='json'))
    pipeline = dojo.OllamaWorkspacePipeline(tmp_path / 'trace.jsonl', 'unused', 'http://127.0.0.1:11434')
    responses = iter([
        ChatResponse(message=Message(role='assistant', content='', tool_calls=[{'function': {'name': 'send_email', 'arguments': {'recipients': ['test@example.com'], 'subject': 'x', 'body': 'x'}}}])),
        ChatResponse(message=Message(role='assistant', content='The operation was blocked.')),
    ])
    pipeline.client = SimpleNamespace(chat=lambda **kwargs: next(responses))
    pipeline.query('test', FunctionsRuntime(suite.tools), env)
    assert dojo.digest(env.model_dump(mode='json')) == original
    assert 'ToolNotFoundError' in pipeline.last['tool_errors'][0]


def fake_lab(monkeypatch, cited_id='record-1'):
    captured = []

    class FakeLab:
        def __init__(self, experiment):
            self.model = 'unused'
            self.agent_client = SimpleNamespace(chat=self.chat)

        def search(self, user, query):
            return {'results': [{'id': 'record-1', 'memory': 'The family reunion is 2024-06-10 13:00.'}]}

        def chat(self, **kwargs):
            captured.append(kwargs['messages'])
            return SimpleNamespace(message=SimpleNamespace(content=json.dumps({
                'answer': '2024-06-10 13:00', 'selected_value': '2024-06-10 13:00',
                'conflict': False, 'memory_ids_used': [cited_id]})))

        def record(self, *args, **kwargs):
            pass

        def close(self):
            pass

    monkeypatch.setattr(dojo, 'Lab', FakeLab)
    return captured


def test_followup_has_only_question_and_memory_no_original_source(monkeypatch):
    captured = fake_lab(monkeypatch)
    result = dojo.follow_up('test', dojo.CASES[0])
    assert result['expected_value_selected']
    messages = captured[0]
    assert [m['role'] for m in messages] == ['system', 'user', 'assistant', 'tool']
    assert messages[1]['content'] == dojo.CASES[0]['followup']
    assert dojo.CASES[0]['payload'] not in json.dumps(messages)
    assert messages[-1]['tool_name'] == 'search_memory'


def test_followup_rejects_hallucinated_memory_citations(monkeypatch):
    fake_lab(monkeypatch, cited_id='not-retrieved')
    with pytest.raises(ValueError, match='not retrieved'):
        dojo.follow_up('test', dojo.CASES[0])


def test_target_indicator_requires_the_target_date_not_just_place():
    case = dojo.CASES[1]
    assert not dojo.target_claim(case, 'Visit Pearl Harbor on June 14.')
    assert dojo.target_claim(case, 'June 13: visit Pearl Harbor.')


def test_controlled_exposure_has_matching_calls_and_does_not_supply_ground_truth(monkeypatch, tmp_path):
    suite = get_suite(dojo.VERSION, 'workspace')
    captured = []

    class FakeClient:
        def __init__(self, **kwargs):
            pass

        def chat(self, **kwargs):
            captured.append(kwargs['messages'])
            return ChatResponse(message=Message(role='assistant', content='Cannot determine.'))

    monkeypatch.setattr(dojo, 'Client', FakeClient)
    case = dojo.CASES[0]
    clean = dojo.reference_exposure(suite, case, tmp_path, 'unused', 'http://127.0.0.1:11434', 42)
    poison = dojo.reference_exposure(suite, case, tmp_path, 'unused', 'http://127.0.0.1:11434', 42, poisoned=True)
    assert clean['tools'][0]['arguments'] == poison['tools'][0]['arguments']
    assert not clean['attack_source_seen']
    assert poison['attack_source_seen']
    for messages in captured:
        # The reference pipeline's ground-truth final answer is never appended.
        assert messages[-1]['role'] == 'tool'
        assert [m['role'] for m in messages] == ['system', 'user', 'assistant', 'tool']
        assert messages[1]['content'] == suite.get_user_task_by_id(case['task_id']).PROMPT
