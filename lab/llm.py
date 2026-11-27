"""Chat backends for the development-phase payload search (lab.tap), never for trials.

Trials run fixed payloads only: a frozen file loaded by ``lab.dojo --tap-payloads``.

Supported specs:

- ``claude`` / ``codex``: the same CLIs the experiment uses for task agents and the memory-only
  Final. They keep their own sampling; temperature and seed cannot be set or reproduced.
- ``deepseek``: an OpenAI-compatible endpoint, so DeepSeek V4.1 flash can act as the TAP
  attacker and evaluator. ``DEEPSEEK_API_KEY``, optionally ``DEEPSEEK_BASE_URL`` and
  ``DEEPSEEK_MODEL`` come from the environment (``.env``, which is git-ignored).
- ``ollama``: the local service already used by every experiment session (loopback only).

Specs are ``backend`` or ``backend:model``. A spec never embeds a credential.
"""
import os
import re
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv

# Read the repo .env even when this module is used without lab.core (which does the same).
load_dotenv(Path(__file__).resolve().parents[1] / '.env')

BACKENDS = ('claude', 'codex', 'deepseek', 'ollama')
CLI_BACKENDS = ('claude', 'codex')
DEFAULT_MODELS = {'claude': '', 'codex': '', 'deepseek': 'deepseek-flash', 'ollama': 'qwen2.5:7b'}
SPEC = re.compile(r'(?P<backend>[a-z]+)(?::(?P<model>[A-Za-z0-9][A-Za-z0-9._:/-]{0,119}))?$')
MODEL = re.compile(r'[A-Za-z0-9][A-Za-z0-9._:/-]{0,119}')


class LlmError(ValueError):
    """A chat backend could not run, or its configuration is invalid."""


def default_model(backend):
    if backend == 'ollama':
        return os.getenv('CHAT_MODEL', DEFAULT_MODELS['ollama'])
    return os.getenv(backend.upper() + '_MODEL', DEFAULT_MODELS.get(backend, ''))


def parse_spec(spec, model=''):
    """Resolve a ``backend[:model]`` spec plus an optional model override."""
    text = (spec or '').strip()
    match = SPEC.fullmatch(text)
    if not match or match['backend'] not in BACKENDS:
        raise LlmError(f'Use a backend spec such as deepseek:{DEFAULT_MODELS["deepseek"]}, claude or ollama:qwen2.5:7b')
    backend = match['backend']
    resolved = model or match['model'] or default_model(backend)
    if resolved and not MODEL.fullmatch(resolved):
        raise LlmError('Invalid model name')
    if not resolved and backend not in CLI_BACKENDS:
        raise LlmError(f'{backend} needs a model name')
    return {'backend': backend, 'model': resolved, 'spec': f'{backend}:{resolved}' if resolved else backend,
            'sampling': 'cli_default' if backend in CLI_BACKENDS else 'temperature_seed'}


def describe(llm):
    """A JSON-safe description; never includes a credential."""
    return {'backend': llm['backend'], 'model': llm['model'] or 'CLI default',
            'spec': llm['spec'], 'sampling': llm.get('sampling')}


def require_available(llm):
    """Fail before any query if a selected backend is missing or logged out."""
    backend = llm['backend']
    if backend == 'deepseek' and not os.getenv('DEEPSEEK_API_KEY', '').strip():
        raise LlmError('DEEPSEEK_API_KEY is not set. Add it to .env (git-ignored) before a TAP search.')
    if backend in CLI_BACKENDS:
        from lab.agents import cli_path, cli_status
        if not cli_path(backend):
            raise LlmError(f'{backend} CLI not found. Set {backend.upper()}_CLI_PATH on the server.')
        if cli_status(backend).get('logged_in') is False:
            raise LlmError(f'{backend} CLI is not logged in')
    if backend == 'ollama':
        parsed = urlparse(os.getenv('OLLAMA_BASE_URL', 'http://127.0.0.1:11434'))
        if parsed.scheme != 'http' or parsed.hostname not in ('localhost', '127.0.0.1', '::1'):
            raise LlmError('Only local Ollama inference is permitted')
    return llm


def _ollama(llm, messages, temperature, seed, max_tokens, timeout):
    from ollama import Client
    url = os.getenv('OLLAMA_BASE_URL', 'http://127.0.0.1:11434')
    options = {'temperature': temperature, 'num_predict': max_tokens,
               'num_ctx': int(os.getenv('CONTEXT_LENGTH', '8192'))}
    if seed is not None:
        options['seed'] = int(seed)
    try:
        response = Client(host=url, timeout=timeout).chat(model=llm['model'], messages=messages, options=options)
    except Exception as exc:
        raise LlmError(f'ollama:{llm["model"]} failed: {type(exc).__name__}: {exc}') from exc
    return (response.message.content or '').strip()


def _cli(llm, messages):
    """The CLIs ignore temperature and seed; their sampling is recorded, not controlled."""
    from lab.agents import CliClient
    try:
        response = CliClient(llm['backend'], llm['model'], lambda *args, **kwargs: None).chat(messages=messages)
    except (ValueError, RuntimeError, OSError) as exc:
        raise LlmError(f'{llm["backend"]} CLI failed: {exc}') from exc
    text = (response.message.content or '').strip()
    if not text:
        raise LlmError(f'{llm["backend"]} CLI returned an empty reply')
    return text


def _deepseek(llm, messages, temperature, seed, max_tokens, timeout):
    key = os.getenv('DEEPSEEK_API_KEY', '').strip()
    if not key:
        raise LlmError('DEEPSEEK_API_KEY is not set. Add it to .env (git-ignored) before a TAP search.')
    base_url = os.getenv('DEEPSEEK_BASE_URL', 'https://api.deepseek.com').rstrip('/')
    if not base_url.startswith(('https://', 'http://')):
        raise LlmError('DEEPSEEK_BASE_URL must be an http(s) URL')
    try:
        from openai import OpenAI
    except ImportError as exc:  # pragma: no cover - openai ships with mem0ai
        raise LlmError('The openai package is required for the DeepSeek backend') from exc
    arguments = {'model': llm['model'], 'messages': messages, 'temperature': temperature, 'max_tokens': max_tokens}
    if seed is not None:
        arguments['seed'] = int(seed)
    client = OpenAI(api_key=key, base_url=base_url, timeout=timeout)
    finish = None
    # A long reasoning trace can consume the whole budget and leave the content empty, so retry
    # with a much larger budget before losing the branch. 3x growth clears observed traces.
    for budget in (max_tokens, min(max_tokens * 3, 16000), min(max_tokens * 9, 16000)):
        arguments['max_tokens'] = budget
        try:
            response = client.chat.completions.create(**arguments)
        except Exception as exc:
            # The SDK exception text can echo request headers; keep only the type and status.
            status = getattr(exc, 'status_code', None)
            raise LlmError(f'deepseek:{llm["model"]} failed: {type(exc).__name__}' + (f' (HTTP {status})' if status else '')) from exc
        choices = getattr(response, 'choices', None) or []
        text = ((choices[0].message.content if choices else None) or '').strip()
        finish = getattr(choices[0], 'finish_reason', None) if choices else None
        if text:
            return text
    raise LlmError(f'deepseek:{llm["model"]} returned an empty reply (finish_reason={finish})')


def chat(llm, messages, *, temperature=0.0, seed=None, max_tokens=1024, timeout=180):
    """One completion. ``messages`` is a list of {role, content} dicts."""
    if not isinstance(messages, list) or not messages:
        raise LlmError('messages must be a non-empty list')
    if llm['backend'] in CLI_BACKENDS:
        return _cli(llm, messages)
    if llm['backend'] == 'ollama':
        return _ollama(llm, messages, temperature, seed, max_tokens, timeout)
    return _deepseek(llm, messages, temperature, seed, max_tokens, timeout)
