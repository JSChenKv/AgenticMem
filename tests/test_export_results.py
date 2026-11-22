import json

from scripts import export_results


def test_failed_startup_export_uses_terminal_job_status_without_mutating_source(monkeypatch, tmp_path):
    folder = tmp_path / 'data' / 'agentdojo_runs' / 'dojo_20261122_003127_df05a9'
    folder.mkdir(parents=True)
    source = {'run_id': folder.name, 'status': 'running', 'workflow': 'sustained', 'cases': []}
    summary = folder / 'summary.json'
    summary.write_text(json.dumps(source))
    original = summary.read_bytes()
    (folder / 'web-job.json').write_text(json.dumps({'status': 'error', 'exit_code': 1, 'pid': 1234}))
    monkeypatch.setattr(export_results, 'ROOT', tmp_path)
    export_results.main()
    output = tmp_path / 'results' / 'runs' / folder.name
    saved = json.loads((output / 'summary.json').read_text())
    assert saved['status'] == 'error' and saved['source_status'] == 'running'
    assert saved['execution'] == {'status': 'error', 'exit_code': 1}
    assert summary.read_bytes() == original
    assert 'not an attack trial' in (output / 'report.md').read_text()
