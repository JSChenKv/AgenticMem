from contextlib import asynccontextmanager
import importlib.metadata
import threading
from concurrent.futures import ThreadPoolExecutor

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from pydantic import BaseModel, Field, model_validator
from typing import Literal

from lab.core import Lab
from lab.benchmark import jobs
from lab.agents import agent_catalog, cli_path, cli_status, resolve_extraction
import os

lock = threading.RLock()
labs = {}
executor = ThreadPoolExecutor(max_workers=1)


@asynccontextmanager
async def lifespan(app):
    yield
    jobs.close()
    def close_all():
        for lab in labs.values():
            lab.close()
    executor.submit(close_all).result()
    executor.shutdown()


app = FastAPI(title='Local Mem0 Research Lab', version='1.0', lifespan=lifespan)
WEB = Path(__file__).parent / 'web'
app.mount('/assets', StaticFiles(directory=WEB), name='assets')


@app.get('/', include_in_schema=False)
def home():
    return FileResponse(WEB / 'index.html', headers={'Cache-Control': 'no-store'})


@app.get('/benchmark', include_in_schema=False)
def benchmark_page():
    return FileResponse(WEB / 'benchmark.html', headers={'Cache-Control': 'no-store'})


class ChatTurn(BaseModel):
    role: Literal['user', 'assistant']
    content: str = Field(min_length=1, max_length=12000)


class AgentSettings(BaseModel):
    agent_backend: Literal['ollama', 'codex', 'claude'] = 'ollama'
    agent_model: str = Field(default='', max_length=120, pattern=r'^([A-Za-z0-9][A-Za-z0-9._:/-]*)?$')
    memory_backend: Literal['follow', 'ollama', 'codex', 'claude'] = 'follow'
    memory_model: str = Field(default='', max_length=120, pattern=r'^([A-Za-z0-9][A-Za-z0-9._:/-]*)?$')

    @model_validator(mode='after')
    def consistent_extraction(self):
        resolve_extraction(self.agent_backend, self.agent_model, self.memory_backend, self.memory_model)
        return self


class Query(AgentSettings):
    experiment: str = Field(default='default', pattern=r'^[A-Za-z0-9_-]{1,80}$')
    user: str = Field(default='researcher', pattern=r'^[A-Za-z0-9_-]{1,80}$')
    text: str = Field(min_length=1, max_length=12000)
    mode: Literal['read', 'write', 'none'] = 'read'
    history: list[ChatTurn] = Field(default_factory=list, max_length=8)


def extraction_for(query):
    return resolve_extraction(query.agent_backend, query.agent_model, query.memory_backend, query.memory_model)


def check_cli(backend):
    if backend != 'ollama' and not cli_path(backend):
        raise HTTPException(status_code=400, detail=f'{backend} CLI not found. Configure its path on the server.')
    if backend != 'ollama' and cli_status(backend).get('logged_in') is False:
        raise HTTPException(status_code=400, detail=f'{backend} CLI is not logged in. Complete CLI login, then retry.')


def execution_options(query):
    if (query.agent_backend, query.agent_model, query.memory_backend, query.memory_model) == ('ollama', '', 'follow', ''):
        return {}
    return {key: getattr(query, key) for key in ('agent_backend', 'agent_model', 'memory_backend', 'memory_model')}


def run(query, action):
    return executor.submit(run_serial, query, action).result()


def run_serial(query, action):
    with lock:
        if jobs.running():
            raise HTTPException(status_code=409, detail='A benchmark is running. Chat and memory operations will be available when it finishes.')
        try:
            if query.experiment not in labs:
                labs[query.experiment] = Lab(query.experiment)
            return action(labs[query.experiment])
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get('/health')
def health():
    from ollama import Client
    from lab.core import os
    try:
        models = Client(host=os.getenv('OLLAMA_BASE_URL', 'http://127.0.0.1:11434'), timeout=5).list()
        return {'status': 'ok', 'mem0ai': importlib.metadata.version('mem0ai'), 'models': [m.model for m in models.models]}
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post('/chat')
def chat(query: Query):
    # Legacy callers omit history; the web client explicitly supplies its current session.
    options = execution_options(query)
    check_cli(query.agent_backend)
    if query.mode == 'write':
        check_cli(extraction_for(query)['backend'])
    return run(query, lambda lab: lab.ask(query.user, query.text, query.mode,
                                         history=[turn.model_dump() for turn in query.history], **options))


@app.post('/memories')
def remember(query: Query):
    extraction = extraction_for(query)
    check_cli(extraction['backend'])
    return run(query, lambda lab: lab.add(query.user, [{'role': 'user', 'content': query.text}], extraction=extraction))


@app.post('/search')
def search(query: Query):
    return run(query, lambda lab: lab.search(query.user, query.text))


@app.post('/ingest')
def ingest(query: Query):
    check_cli(query.agent_backend)
    check_cli(extraction_for(query)['backend'])
    return run(query, lambda lab: lab.ingest_document(query.user, query.text, **execution_options(query)))


@app.get('/memories')
def memories(experiment: str = 'default', user: str = 'researcher'):
    query = Query(experiment=experiment, user=user, text='list')
    return run(query, lambda lab: lab.memories(user))


class BenchmarkRequest(AgentSettings):
    tasks: list[Literal['user_task_14', 'user_task_30']] = Field(min_length=1, max_length=2)
    exposure_policy: Literal['reference', 'agent'] = 'reference'


@app.get('/agents')
def available_agents():
    return {'agents': agent_catalog(), 'memory_default': 'follow', 'embedding_model': os.getenv('EMBED_MODEL', 'bge-m3:latest'),
            'context_policy': 'task_only_v1'}


@app.get('/benchmarks')
def benchmark_runs():
    return {'runs': jobs.list(), 'active_run': jobs.active_run}


@app.post('/benchmarks', status_code=202)
def start_benchmark(query: BenchmarkRequest):
    with lock:
        try:
            return jobs.start(query.tasks, query.exposure_policy, query.agent_backend, query.agent_model,
                              query.memory_backend, query.memory_model)
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except OSError as exc:
            raise HTTPException(status_code=503, detail='Could not start the benchmark process: ' + str(exc)) from exc


def get_run(run_id):
    try:
        return jobs.get(run_id)
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=404, detail='Run not found') from exc


@app.get('/benchmarks/{run_id}')
def benchmark_run(run_id: str):
    return get_run(run_id)


@app.get('/benchmarks/{run_id}/report')
def benchmark_report(run_id: str):
    run = get_run(run_id)
    if not run['has_report']:
        raise HTTPException(status_code=404, detail='The report is not ready yet')
    return FileResponse(jobs.path(run_id) / 'report.md', filename=run_id + '.md')


@app.get('/benchmarks/{run_id}/evidence')
def benchmark_evidence(run_id: str):
    run = get_run(run_id)
    if not run['summary']:
        raise HTTPException(status_code=404, detail='Results are not ready yet')
    return FileResponse(jobs.path(run_id) / 'summary.json', filename=run_id + '.json')
