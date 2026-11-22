"""Local, process-isolated web jobs for the pinned AgentDojo pilot."""
from datetime import datetime, timezone
import importlib.metadata
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import threading
import uuid
import portalocker

from lab.core import ROOT
from lab.agents import validate_agent, cli_path, cli_status, resolve_extraction

TASKS = {'user_task_14': 'Family reunion · Email', 'user_task_30': 'Hawaii itinerary · Document'}
RUN_PATTERN = re.compile(r'^dojo_\d{8}_\d{6}_[a-f0-9]{6}$')


def read_json(path):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None


class BenchmarkJobs:
    def __init__(self, root=ROOT):
        self.root = Path(root)
        self.guard = threading.RLock()
        self.process = None
        self.active_id = None
        self.worker = None

    @property
    def runs(self):
        return self.root / 'data' / 'agentdojo_runs'

    def path(self, run_id):
        if not RUN_PATTERN.fullmatch(run_id):
            raise ValueError('Invalid run ID')
        directory = (self.runs / run_id).resolve()
        if not directory.is_relative_to(self.runs.resolve()) or not directory.is_dir():
            raise FileNotFoundError('Run not found')
        return directory

    def running(self):
        return self.active_run is not None

    @property
    def active_run(self):
        with self.guard:
            if self.active_id:
                return self.active_id
            gate = self.root / 'data' / 'benchmark.lock'
            if not gate.exists():
                return None
            try:
                with portalocker.Lock(str(gate), timeout=0):
                    return None
            except portalocker.exceptions.LockException:
                # Also recognize a surviving child after a web-server restart.
                owner = read_json(self.root / 'data' / 'benchmark-owner.json') or {}
                return owner.get('run_id', 'external')

    def start(self, tasks, policy, agent_backend='ollama', agent_model='', memory_backend='follow', memory_model='', workflow='sustained', delay_tasks=0, evaluation_tools='workspace', source_run_id=''):
        if workflow not in ('pilot', 'episode', 'autonomous', 'direct', 'sustained') or type(delay_tasks) is not int or delay_tasks not in (0, 1, 3):
            raise ValueError('Invalid episode configuration')
        if evaluation_tools not in ('workspace', 'memory_only'):
            raise ValueError('Invalid final evaluation tools')
        if workflow == 'sustained' and evaluation_tools != 'workspace':
            raise ValueError('Sustained exposure requires workspace tools at Final')
        if workflow in ('autonomous', 'direct', 'sustained'):
            policy, delay_tasks = 'agent', 0
        if workflow == 'direct':
            from lab.direct import load_source, protocol
            selected, reference, archived = load_source(self.root, source_run_id, tasks)
            protocol(selected, reference, archived)
            if evaluation_tools != 'workspace':
                raise ValueError('Direct-source comparison requires workspace tools')
        elif source_run_id:
            raise ValueError('Source run is only used by the direct-source supplement')
        validate_agent(agent_backend, agent_model)
        extraction = resolve_extraction(agent_backend, agent_model, memory_backend, memory_model)
        if agent_backend != 'ollama' and not cli_path(agent_backend):
            raise ValueError(f'{agent_backend} CLI not found. Configure {agent_backend.upper()}_CLI_PATH on the server.')
        if agent_backend != 'ollama' and cli_status(agent_backend).get('logged_in') is False:
            raise ValueError(f'{agent_backend} CLI is not logged in. Complete its CLI login, then retry.')
        if workflow != 'direct' and extraction['backend'] != 'ollama':
            if not cli_path(extraction['backend']) or cli_status(extraction['backend']).get('logged_in') is False:
                raise ValueError(f"Memory extractor {extraction['backend']} is unavailable or not logged in.")
        if not tasks or len(tasks) != len(set(tasks)) or any(t not in TASKS for t in tasks):
            raise ValueError('Select one or both supported tasks, without duplicates')
        if policy not in ('reference', 'agent'):
            raise ValueError('Invalid exposure policy')
        try:
            version = importlib.metadata.version('agentdojo')
        except importlib.metadata.PackageNotFoundError as exc:
            raise ValueError('Install requirements-benchmark.txt before starting a run') from exc
        if version != '0.1.35':
            raise ValueError('This pilot requires agentdojo==0.1.35')
        with self.guard:
            if self.running():
                raise RuntimeError('A benchmark is already running. Wait for it to finish.')
            run_id = 'dojo_' + datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S') + '_' + uuid.uuid4().hex[:6]
            self.runs.mkdir(parents=True, exist_ok=True)
            directory = self.runs / run_id
            directory.mkdir()
            job = {'run_id': run_id, 'status': 'starting', 'tasks': tasks, 'exposure_policy': policy,
                   'started_at': datetime.now(timezone.utc).isoformat(),
                   'agent': {'backend': agent_backend, 'model': agent_model or ('local default' if agent_backend == 'ollama' else 'CLI default')},
                   'extraction': extraction, 'workflow': workflow, 'delay_tasks': delay_tasks, 'evaluation_tools': evaluation_tools,
                   'source_run_id': source_run_id}
            self._write(directory / 'web-job.json', job)
            command = [sys.executable, '-m', 'lab.dojo', '--run-id', run_id, '--tasks', *tasks,
                       '--exposure-policy', policy, '--agent-backend', agent_backend, '--memory-backend', memory_backend,
                       '--workflow', workflow, '--delay-tasks', str(delay_tasks), '--evaluation-tools', evaluation_tools]
            if source_run_id:
                command += ['--source-run-id', source_run_id]
            if agent_model:
                command += ['--agent-model', agent_model]
            if memory_model:
                command += ['--memory-model', memory_model]
            env = {**os.environ, 'PYTHONUTF8': '1', 'PYTHONUNBUFFERED': '1'}
            try:
                with (directory / 'console.log').open('wb') as log:
                    process = subprocess.Popen(command, cwd=self.root, env=env, stdout=log,
                                               stderr=subprocess.STDOUT,
                                               creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            except Exception as exc:
                job.update(status='error', error=str(exc))
                self._write(directory / 'web-job.json', job)
                raise
            self.process, self.active_id = process, run_id
            job.update(status='running', pid=process.pid)
            self._write(directory / 'web-job.json', job)
            self.worker = threading.Thread(target=self._watch, args=(process, directory, job), daemon=True)
            self.worker.start()
            return self.get(run_id)

    @staticmethod
    def _write(path, value):
        temporary = path.with_suffix('.tmp')
        temporary.write_text(json.dumps(value, indent=2), encoding='utf-8')
        temporary.replace(path)

    def _watch(self, process, directory, job):
        code = process.wait()
        with self.guard:
            summary = read_json(directory / 'summary.json') or {}
            job.update(status=(summary.get('status', 'error') if code == 0 else 'error'),
                       exit_code=code, finished_at=datetime.now(timezone.utc).isoformat())
            if job['status'] == 'running':
                job['status'] = 'error'
            self._write(directory / 'web-job.json', job)
            if self.process is process:
                self.process, self.active_id = None, None

    def close(self):
        # Only terminate the child we launched; never kill arbitrary model/server processes.
        with self.guard:
            process, worker = self.process, self.worker
        if process and process.poll() is None:
            if os.name == 'nt':
                # Windows venv launchers may have a real Python child. Stop that
                # owned tree as well so closing the API cannot leave a worker behind.
                subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               creationflags=subprocess.CREATE_NO_WINDOW, timeout=10, check=False)
            else:
                process.terminate()
        if worker:
            worker.join(timeout=10)

    def get(self, run_id):
        directory = self.path(run_id)
        job = read_json(directory / 'web-job.json') or {}
        summary = read_json(directory / 'summary.json') or {}
        progress = read_json(directory / 'progress.json')
        active = self.active_run == run_id
        status = job.get('status', summary.get('status', 'incomplete'))
        if not active and status in ('running', 'starting'):
            # A server restart/crash must not present a stale job as live.
            status = summary.get('status', 'interrupted')
            if status in ('running', 'starting'):
                status = 'interrupted'
        try:
            with (directory / 'console.log').open('rb') as stream:
                stream.seek(max(0, (directory / 'console.log').stat().st_size - 16000))
                console = stream.read().decode('utf-8', errors='replace')
        except OSError:
            console = ''
        return {'run_id': run_id, 'status': status, 'active': active, 'progress': progress,
                'workflow': summary.get('workflow', job.get('workflow', 'pilot')),
                'delay_tasks': summary.get('delay_tasks', job.get('delay_tasks', 0)),
                'evaluation_tools': summary.get('evaluation_tools', job.get('evaluation_tools', 'workspace')),
                'source_run_id': summary.get('source_run_id', job.get('source_run_id', '')),
                'agent': summary.get('agent', job.get('agent', {'backend': 'ollama', 'model': 'qwen2.5:7b'})),
                'memory_model': summary.get('memory_model', 'qwen2.5:7b'),
                'extraction': summary.get('extraction', job.get('extraction', {
                    'mode': 'legacy', 'backend': 'ollama', 'model': summary.get('memory_model', 'qwen2.5:7b')})),
                'tasks': job.get('tasks', [c['task_id'] for c in summary.get('cases', [])]),
                'exposure_policy': job.get('exposure_policy', summary.get('exposure_policy', 'unknown')),
                'started_at': job.get('started_at'), 'error': job.get('error'),
                'summary': summary or None, 'console': console,
                'has_report': (directory / 'report.md').is_file()}

    def list(self):
        if not self.runs.exists():
            return []
        result = []
        for directory in sorted(self.runs.iterdir(), reverse=True):
            if not RUN_PATTERN.fullmatch(directory.name) or not directory.is_dir():
                continue
            run = self.get(directory.name)
            result.append({key: run[key] for key in ('run_id', 'status', 'active', 'tasks', 'exposure_policy', 'started_at', 'agent', 'extraction', 'workflow', 'delay_tasks')})
            if len(result) == 50:
                break
        return result


jobs = BenchmarkJobs()
