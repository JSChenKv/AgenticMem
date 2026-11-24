import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

from lab import agents, dojo


def test_memory_visibility_is_allowlisted_not_blacklisted():
    records = [{'id': 'id-1', 'memory': 'June 13: Diamond Head',
                'metadata': {'source': 'poison', 'expected': 'answer', 'task_id': 'user_task_30'},
                'score': 0.8, 'explanation': 'benchmark', 'new_private_field': 'secret'}]
    assert agents.public_memories(records) == [{'id': 'id-1', 'memory': 'June 13: Diamond Head'}]


def test_cli_launch_has_no_history_or_project_tools(tmp_path):
    work = tmp_path / 'workspace'
    private = tmp_path / 'context'
    work.mkdir()
    private.mkdir()
    codex = agents.codex_command('codex.exe', work, private, 'chosen-model', None)
    assert '--ephemeral' in codex and '--ignore-user-config' in codex
    assert 'project_doc_max_bytes=0' in codex and 'features.shell_tool=false' in codex
    assert 'features.plugins=false' in codex and 'features.apps=false' in codex
    assert 'resume' not in codex and '--dangerously-bypass-approvals-and-sandbox' not in codex
    claude = agents.claude_command('claude.exe', work, private, '', None)
    assert claude[claude.index('--tools') + 1] == ''
    assert '--restricted' in claude and '--strict-mcp-config' in claude
    assert '--no-session-persistence' in claude and '--bare' not in claude
    assert 'resume' not in claude and '--dangerously-skip-permissions' not in claude
    assert json.loads((private / 'mcp.json').read_text()) == {'mcpServers': {}}


def test_stdio_mcp_roundtrip_only_exposes_allowlisted_tools():
    calls = []
    definitions = [{'name': 'search_emails', 'description': 'Search email', 'inputSchema': {'type': 'object'}}]

    def execute(name, arguments):
        calls.append((name, arguments))
        return 'Meeting at 13:00', None

    messages = [
        {'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {'protocolVersion': '2024-11-05'}},
        {'jsonrpc': '2.0', 'method': 'notifications/initialized'},
        {'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list'},
        {'jsonrpc': '2.0', 'id': 3, 'method': 'tools/call', 'params': {'name': 'search_emails', 'arguments': {'query': 'meeting'}}},
        {'jsonrpc': '2.0', 'id': 4, 'method': 'tools/call', 'params': {'name': 'send_email', 'arguments': {}}},
    ]
    with agents.tool_broker(definitions, execute) as spec:
        response = subprocess.run([spec['command'], *spec['args']], input='\n'.join(map(json.dumps, messages)) + '\n',
                                  capture_output=True, text=True, encoding='utf-8', env={**agents.os.environ, **spec['env']}, timeout=10)
    replies = [json.loads(line) for line in response.stdout.splitlines()]
    assert len(replies) == 4
    assert replies[1]['result']['tools'] == definitions
    assert replies[2]['result']['content'][0]['text'] == 'Meeting at 13:00'
    assert 'error' in replies[3]
    assert calls == [('search_emails', {'query': 'meeting'})]


def test_cli_runner_uses_empty_cwd_and_stdin_without_config_secrets(monkeypatch):
    monkeypatch.setattr(agents, 'cli_path', lambda backend: 'codex.exe')
    monkeypatch.setenv('OPENAI_API_KEY', 'must-not-be-forwarded')
    monkeypatch.setenv('CODEX_THREAD_ID', 'previous-chat')
    captured = []

    def run(command, prompt, cwd, env, timeout):
        captured.append(prompt)
        assert not list(cwd.iterdir())
        assert 'OPENAI_API_KEY' not in env and 'CODEX_THREAD_ID' not in env
        assert 'D:\\AgenticMem' not in str(cwd)
        Path(command[command.index('-o') + 1]).write_text('Done', encoding='utf-8')
        return 0, '', ''

    monkeypatch.setattr(agents, 'run_process', run)
    result = agents.CliClient('codex').chat(messages=[{'role': 'system', 'content': 'Help the user.'}, {'role': 'user', 'content': 'Hello'}])
    assert result.message.content == 'Done'
    assert captured == ['Hello']


def test_native_cli_pipeline_executes_real_official_tools(monkeypatch, tmp_path):
    captured = []

    def run(self, messages, definitions, handler):
        captured.append((messages, definitions))
        output, error = handler('search_emails', {'query': 'family reunion'})
        assert not error and 'Grandma' in output
        return SimpleNamespace(message=SimpleNamespace(content='2024-06-10 13:00'))

    monkeypatch.setattr(agents.CliClient, 'run', run)
    suite = dojo.get_suite(dojo.VERSION, 'workspace')
    task = suite.get_user_task_by_id('user_task_14')
    pipeline = dojo.CliWorkspacePipeline(tmp_path / 'trace.jsonl', 'codex', '')
    utility, _ = suite.run_task_with_pipeline(pipeline, task, injection_task=None, injections={})
    assert utility and pipeline.last['tools'][0]['tool'] == 'search_emails'
    visible = json.dumps(captured)
    for forbidden in ('user_task_14', 'baseline', 'benchmark', 'poison', 'research assistant'):
        assert forbidden not in visible
    assert {d['name'] for d in captured[0][1]} == {'search_emails', 'search_files'}


@pytest.mark.parametrize('model', ['--help', 'x;calc', 'a\nb', '../secret', 'x y'])
def test_models_cannot_be_flags_or_commands(model):
    with pytest.raises(ValueError):
        agents.validate_agent('codex', model)


def test_claude_failure_is_not_an_answer(monkeypatch):
    monkeypatch.setattr(agents, 'cli_path', lambda backend: 'claude.exe')
    monkeypatch.setattr(agents, 'run_process', lambda *args: (0, json.dumps({'is_error': True, 'result': 'Login required'}), ''))
    with pytest.raises(RuntimeError, match='did not complete'):
        agents.CliClient('claude').chat(messages=[{'role': 'user', 'content': 'Hello'}])


def test_web_forwards_agent_selection_and_rejects_option_injection(monkeypatch):
    from fastapi.testclient import TestClient
    from lab import api
    calls = []
    monkeypatch.setattr(api, 'jobs', SimpleNamespace(start=lambda *args: calls.append(args) or {'run_id': 'test'}))
    client = TestClient(api.app)
    response = client.post('/benchmarks', json={'tasks': ['user_task_14'], 'agent_backend': 'codex', 'agent_model': 'chosen-model'})
    assert response.status_code == 202
    # v6 defaults: fixed Codex/gpt-6-luna extractor, 3 repeats, all three models answer the memory-only Final.
    assert calls == [(['user_task_14'], 'agent', 'codex', 'chosen-model', 'codex', '', 'sustained', 'workspace',
                      3, ['ollama', 'codex', 'claude'], False, False)]
    for body in ({'agent_backend': 'shell'}, {'agent_model': '--help'}, {'agent_model': 'x;calc'}):
        assert client.post('/benchmarks', json={'tasks': ['user_task_14'], **body}).status_code == 422


def test_unlogged_cli_does_not_launch_a_job(monkeypatch, tmp_path):
    from lab import benchmark
    monkeypatch.setattr(benchmark, 'cli_path', lambda backend: 'claude.exe')
    monkeypatch.setattr(benchmark, 'cli_status', lambda backend: {'logged_in': False})
    manager = benchmark.BenchmarkJobs(tmp_path)
    with pytest.raises(ValueError, match='not logged in'):
        manager.start(['user_task_14'], 'agent', 'claude')
    assert not manager.runs.exists()
