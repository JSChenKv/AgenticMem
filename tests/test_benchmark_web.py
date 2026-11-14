import json
import threading
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from lab import api, benchmark

RUN = 'dojo_20261019_020000_abcdef'


def saved_run(manager, status='completed'):
    directory = manager.runs / RUN
    directory.mkdir(parents=True)
    (directory / 'summary.json').write_text(json.dumps({'run_id': RUN, 'status': status, 'cases': [], 'exposure_policy': 'reference'}))
    (directory / 'report.md').write_text('# Saved report')
    return directory


def test_previous_cli_results_are_available_and_downloadable(monkeypatch, tmp_path):
    manager = benchmark.BenchmarkJobs(tmp_path)
    saved_run(manager)
    monkeypatch.setattr(api, 'jobs', manager)
    client = TestClient(api.app)
    assert client.get('/benchmarks').json()['runs'][0]['run_id'] == RUN
    run = client.get('/benchmarks/' + RUN).json()
    assert run['status'] == 'completed' and not run['active']
    assert client.get('/benchmarks/' + RUN + '/report').text == '# Saved report'
    evidence = client.get('/benchmarks/' + RUN + '/evidence')
    assert evidence.json()['run_id'] == RUN
    assert evidence.headers['content-disposition'].startswith('attachment;')


def test_job_inputs_cannot_inject_commands_or_arbitrary_tasks(monkeypatch, tmp_path):
    manager = benchmark.BenchmarkJobs(tmp_path)
    monkeypatch.setattr(api, 'jobs', manager)
    client = TestClient(api.app)
    for query in ({'tasks': []}, {'tasks': ['user_task_99']}, {'tasks': ['--help']},
                  {'tasks': ['user_task_14'], 'exposure_policy': 'shell'}):
        assert client.post('/benchmarks', json=query).status_code == 422
    assert client.post('/benchmarks', json={'tasks': ['user_task_14'] * 2}).status_code == 400
    for run_id in ('x', 'dojo_20261019_020000_abcdef.exe', '..%5C..%5C.env'):
        assert client.get('/benchmarks/' + run_id).status_code == 404
    assert not manager.runs.exists()


def test_jobs_run_in_isolated_child_and_serialize_model_access(monkeypatch, tmp_path):
    manager = benchmark.BenchmarkJobs(tmp_path)
    monkeypatch.setattr(api, 'jobs', manager)
    captured = []
    finished = threading.Event()

    class Process:
        pid = 12345

        def wait(self):
            assert finished.wait(5)
            return 0

    def launch(command, **kwargs):
        captured.append((command, kwargs))
        return Process()

    monkeypatch.setattr(benchmark.subprocess, 'Popen', launch)
    client = TestClient(api.app)
    try:
        response = client.post('/benchmarks', json={'tasks': ['user_task_14']})
        assert response.status_code == 202
        run = response.json()
        assert run['active'] and run['status'] == 'running'
        assert captured[0][0][:3] == [benchmark.sys.executable, '-m', 'lab.dojo']
        assert captured[0][1]['cwd'] == tmp_path
        assert captured[0][1]['env']['PYTHONUTF8'] == '1'
        assert (manager.path(run['run_id']) / 'web-job.json').exists()
        assert client.post('/benchmarks', json={'tasks': ['user_task_30']}).status_code == 409
        assert client.post('/chat', json={'text': 'hello'}).status_code == 409
        directory = manager.path(run['run_id'])
        (directory / 'summary.json').write_text(json.dumps({'status': 'completed_with_limitations', 'cases': []}))
    finally:
        finished.set()
        if manager.worker:
            manager.worker.join(5)
    assert not manager.running()
    assert manager.get(run['run_id'])['status'] == 'completed_with_limitations'


def test_failed_launch_is_persisted_without_blocking_future_jobs(monkeypatch, tmp_path):
    manager = benchmark.BenchmarkJobs(tmp_path)
    monkeypatch.setattr(api, 'jobs', manager)

    def fail(*args, **kwargs):
        raise OSError('launch failed')

    monkeypatch.setattr(benchmark.subprocess, 'Popen', fail)
    client = TestClient(api.app)
    assert client.post('/benchmarks', json={'tasks': ['user_task_14']}).status_code == 503
    assert not manager.running()
    assert manager.list()[0]['status'] == 'error'


def test_stale_jobs_and_partial_results_are_not_reported_as_success(tmp_path):
    manager = benchmark.BenchmarkJobs(tmp_path)
    directory = saved_run(manager, 'running')
    (directory / 'web-job.json').write_text(json.dumps({'status': 'running'}))
    (directory / 'console.log').write_text('failure details')
    run = manager.get(RUN)
    assert run['status'] == 'interrupted' and not run['active']
    assert run['console'] == 'failure details'
    assert run['summary']['status'] == 'running'
    (directory / 'summary.json').write_text(json.dumps({'status': 'completed', 'cases': []}))
    assert manager.get(RUN)['status'] == 'completed'


def test_surviving_worker_lock_blocks_a_second_run_and_is_visible(tmp_path):
    import portalocker
    manager = benchmark.BenchmarkJobs(tmp_path)
    directory = saved_run(manager, 'running')
    (directory / 'web-job.json').write_text(json.dumps({'status': 'running'}))
    (tmp_path / 'data' / 'benchmark-owner.json').write_text(json.dumps({'run_id': RUN}))
    with portalocker.Lock(str(tmp_path / 'data' / 'benchmark.lock'), timeout=0):
        assert manager.running() and manager.active_run == RUN
        assert manager.get(RUN)['active']
        with pytest.raises(RuntimeError, match='already running'):
            manager.start(['user_task_14'], 'reference')
    assert not manager.running()
    assert manager.get(RUN)['status'] == 'interrupted'


def test_stage_progress_is_atomic_and_has_no_answers(tmp_path):
    from lab.dojo import progress
    progress(tmp_path, 'user_task_14', 'poison', 0, 2)
    saved = json.loads((tmp_path / 'progress.json').read_text())
    assert saved['stage'] == 'poison' and saved['total_cases'] == 2
    assert 'expected' not in saved and not (tmp_path / 'progress.tmp').exists()
