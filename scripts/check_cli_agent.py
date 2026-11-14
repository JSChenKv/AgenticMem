"""Read-only live check of a CLI agent and the official workspace tool bridge."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lab.dojo import CliWorkspacePipeline, TASK_PROMPT, VERSION, get_suite
from agentdojo.functions_runtime import FunctionsRuntime

parser = argparse.ArgumentParser()
parser.add_argument('backend', choices=['codex', 'claude'])
parser.add_argument('--model', default='')
args = parser.parse_args()
root = Path(__file__).resolve().parents[1]
trace = root / 'logs' / (args.backend + '-integration-check.jsonl')
suite = get_suite(VERSION, 'workspace')
task = suite.get_user_task_by_id('user_task_14')
pipeline = CliWorkspacePipeline(trace, args.backend, args.model)
utility, _ = suite.run_task_with_pipeline(pipeline, task, injection_task=None, injections={})
result = {'backend': args.backend, 'official_utility': bool(utility), **pipeline.last}
(root / 'logs' / (args.backend + '-integration-check.json')).write_text(json.dumps(result, indent=2), encoding='utf-8')
print(json.dumps({'backend': args.backend, 'utility': bool(utility), 'answer': result['answer'], 'tools': [t['tool'] for t in result['tools']]}))
if not utility or not result['tools']:
    sys.exit(1)
