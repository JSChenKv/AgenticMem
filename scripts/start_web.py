"""Start the local web app in the foreground; Ctrl+C stops the API cleanly."""
import argparse
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def available(url):
    try:
        with urllib.request.urlopen(url, timeout=2) as response:
            return response.status == 200
    except (OSError, urllib.error.URLError):
        return False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--no-browser', action='store_true')
    args = parser.parse_args()
    url = 'http://127.0.0.1:8000'
    if not available('http://127.0.0.1:11434/api/version'):
        executable = ROOT / '.tools' / 'ollama' / 'ollama.exe'
        if not executable.exists():
            raise RuntimeError('Local Ollama is missing. Run setup first.')
        environment = {**os.environ, 'OLLAMA_HOST': '127.0.0.1:11434',
                       'OLLAMA_MODELS': str(ROOT / 'data' / 'models'),
                       'OLLAMA_NUM_PARALLEL': '1', 'OLLAMA_MAX_LOADED_MODELS': '2',
                       'OLLAMA_CONTEXT_LENGTH': '8192', 'OLLAMA_NO_CLOUD': '1'}
        (ROOT / 'logs').mkdir(exist_ok=True)
        with (ROOT / 'logs' / 'ollama.out.log').open('a') as out, (ROOT / 'logs' / 'ollama.err.log').open('a') as err:
            subprocess.Popen([str(executable), 'serve'], cwd=ROOT, env=environment,
                             stdout=out, stderr=err, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        for _ in range(60):
            if available('http://127.0.0.1:11434/api/version'):
                break
            time.sleep(.5)
        else:
            raise RuntimeError('Ollama did not start; see logs/ollama.err.log.')
    if available(url) or available(url + '/health'):
        print('Local service is already running: ' + url)
        if not args.no_browser:
            webbrowser.open(url)
        return
    if not args.no_browser:
        def open_when_ready():
            for _ in range(60):
                if available(url):
                    webbrowser.open(url)
                    return
                time.sleep(.5)
        threading.Thread(target=open_when_ready, daemon=True).start()
    print('Open ' + url + ' for Memory Lab (Chat and Benchmark). Press Ctrl+C here to stop the web service.')
    import uvicorn
    uvicorn.run('lab.api:app', host='127.0.0.1', port=8000, workers=1)


if __name__ == '__main__':
    main()
