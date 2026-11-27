"""Freeze TAP-optimized payloads before trials (development phase; never runs inside a trial).

DeepSeek V4.1 flash is the default attacker and evaluator; the target is the local Ollama
model that answers the memory-only probe. The search writes one directory per run:

  data/tap/<search_id>/payloads.json   frozen goals, hashes and provenance
  data/tap/<search_id>/result.json     full trees and probe answers
  data/tap/<search_id>/trace.jsonl     every branch, score and query
  data/tap/<search_id>/report.md       per-case summary

Then run trials with the frozen file; `lab.dojo` refuses any case whose inputs changed:

  .\\.venv\\Scripts\\python.exe -m lab.dojo --tap-payloads data\\tap\\<search_id>\\payloads.json

Examples:

  # Cheap dry run: validate the configuration and case IDs, no model calls.
  .\\.venv\\Scripts\\python.exe scripts\\tap_search.py --dry-run

  # Local-only smoke search (no DeepSeek key needed): 1 level, 1 query per case.
  .\\.venv\\Scripts\\python.exe scripts\\tap_search.py --smoke --cases user_task_14

  # The real phase: DeepSeek V4.1 flash attacks three answer tasks.
  .\\.venv\\Scripts\\python.exe scripts\\tap_search.py --cases user_task_14 user_task_17 user_task_30
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agentdojo.task_suite.load_suites import get_suite

from lab import dojo, tap
from lab.llm import LlmError, describe, parse_spec, require_available
from lab.sustained import VERSION as PROTOCOL_VERSION


def write_trace(path, event, **values):
    with path.open('a', encoding='utf-8') as stream:
        stream.write(json.dumps({'time_utc': datetime.now(timezone.utc).isoformat(), 'event': event,
                                 **values}, ensure_ascii=False, default=str) + '\n')


def render_report(results, payloads):
    attack = payloads['cases'][0]['attack'] if payloads['cases'] else 'update'
    success_note = ('the probe succeeded when the real memory was deleted' if attack == 'delete'
                    else 'the probe succeeded when the answer asserted the attacker value')
    lines = ['# TAP payload search', '',
             f"Search: `{payloads['search_id']}`. Attack: `{attack}`. Protocol: `{payloads['protocol']}`. "
             f"Classifier: `{payloads['classifier']}`.", '',
             f"Attacker: `{payloads['search']['llms'].get('attacker', {}).get('spec', '?')}`. "
             f"Evaluator: `{payloads['search']['llms'].get('evaluator', {}).get('spec', '?')}`. "
             f"Target: `{payloads['search']['llms'].get('target', {}).get('spec', '?')}`.", '',
             'The probe is a surrogate for the full S1 -> Final chain; frozen goals are validated by a real trial. '
             f'For this attack, {success_note}.', '',
             '| Task | Source | Probe success | Label | Queries | Stopped | Frozen goal |',
             '| --- | --- | --- | --- | --- | --- | --- |']
    for entry in payloads['cases']:
        goal = entry['goal'].replace('|', '\\|').replace('\n', ' ')
        lines.append(f"| {entry['task_id']} | {entry['source']} | {'yes' if entry['success'] else 'no'} | "
                     f"{entry['label']} | {entry['queries']} | {entry['stopped']} | {goal} |")
    errors = [r for r in results if r.get('status') == 'error']
    if errors:
        lines += ['', '## Errors', '']
        lines += [f"- `{r['task_id']}`: {r['error']}" for r in errors]
    return '\n'.join(lines) + '\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--cases', nargs='+', choices=[c['task_id'] for c in dojo.CASES],
                        default=['user_task_14', 'user_task_17', 'user_task_30'],
                        help='cases to search; calendar actions are scored by asserted text in the probe')
    parser.add_argument('--attack', choices=list(tap.ATTACKS), default='update',
                        help='update: phrasing that asserts the attacker value; delete: instruction that deletes the real memory')
    parser.add_argument('--attacker', default='deepseek',
                        help='default: DEEPSEEK_MODEL (deepseek-flash) on the DeepSeek endpoint')
    parser.add_argument('--attacker-model', default='', help='overrides the model in --attacker')
    parser.add_argument('--evaluator', default='deepseek',
                        help='default: the same DeepSeek model as the attacker')
    parser.add_argument('--evaluator-model', default='')
    parser.add_argument('--target', default='claude',
                        help='model that answers the probe: the trial answerer (default: the Claude CLI used by the live runs)')
    parser.add_argument('--target-model', default='')
    parser.add_argument('--branching', type=int, default=tap.DEFAULT_CONFIG['branching'])
    parser.add_argument('--width', type=int, default=tap.DEFAULT_CONFIG['width'])
    parser.add_argument('--depth', type=int, default=tap.DEFAULT_CONFIG['depth'])
    parser.add_argument('--max-queries', type=int, default=tap.DEFAULT_CONFIG['max_queries'])
    parser.add_argument('--prune-below', type=int, default=tap.DEFAULT_CONFIG['prune_below'])
    parser.add_argument('--seed', type=int, default=tap.DEFAULT_CONFIG['seed'])
    parser.add_argument('--no-real-value', action='store_true',
                        help='update attack only: reject any goal that mentions the real value, even to reject it '
                             '(a mention makes the target report a conflict)')
    parser.add_argument('--no-baseline-control', action='store_true',
                        help='skip querying the fixed goal first (costs one query, records the control)')
    parser.add_argument('--continue-after-baseline', action='store_true',
                        help='keep searching even if the fixed goal already succeeds in the probe')
    parser.add_argument('--freeze-best', action='store_true',
                        help='freeze the best guard-passing candidate even if the probe failed '
                             '(retrieval-displacement experiments, where the probe still holds the real record)')
    parser.add_argument('--search-id', default='', help='override the generated ID (reproducible reruns)')
    parser.add_argument('--out', type=Path, default=ROOT / 'data' / 'tap')
    parser.add_argument('--dry-run', action='store_true', help='validate inputs and exit without model calls')
    parser.add_argument('--smoke', action='store_true', help='1 level, 2 variations, 1 query per case')
    args = parser.parse_args()

    if args.no_real_value and args.attack != 'update':
        raise SystemExit('--no-real-value applies to the update attack only')
    if args.smoke:
        args.branching, args.width, args.depth, args.max_queries = 2, 1, 1, 2
        args.cases = args.cases[:1]
    config = tap.validate_config({'branching': args.branching, 'width': args.width, 'depth': args.depth,
                                  'max_queries': args.max_queries, 'prune_below': args.prune_below,
                                  'baseline_control': not args.no_baseline_control,
                                  'stop_on_baseline': not args.continue_after_baseline, 'seed': args.seed})
    attacker = parse_spec(args.attacker, args.attacker_model)
    evaluator = parse_spec(args.evaluator, args.evaluator_model)
    target = parse_spec(args.target, args.target_model)
    unavailable = {}
    for role, llm in (('attacker', attacker), ('evaluator', evaluator), ('target', target)):
        try:
            require_available(llm)
        except LlmError as exc:
            unavailable[role] = str(exc)
    selected = [dojo.with_attack(c, args.attack) for c in dojo.CASES if c['task_id'] in args.cases]
    if len(selected) != len(set(args.cases)):
        raise ValueError('Unknown case')
    suite = get_suite(dojo.VERSION, 'workspace')
    search_id = args.search_id or ('tap_' + datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S') + '_' + uuid.uuid4().hex[:6])
    if not re.fullmatch(r'tap_\d{8}_\d{6}_[a-f0-9]{6}', search_id):
        raise ValueError('Invalid search ID')
    directory = args.out / search_id
    print(f"Search {search_id} ({args.attack} attack)\n  attacker {attacker['spec']}\n  evaluator {evaluator['spec']}\n"
          f"  target   {target['spec']}\n  cases    {', '.join(args.cases)}\n  tree     "
          f"branching={config['branching']} width={config['width']} depth={config['depth']} "
          f"max_queries={config['max_queries']} prune_below={config['prune_below']}", flush=True)
    if args.dry_run:
        for role, reason in unavailable.items():
            print(f'  {role}: NOT READY - {reason}')
        print('Dry run: configuration and case IDs validated; no model calls, nothing written.')
        return
    if unavailable:
        raise SystemExit('\n'.join(f'{role}: {reason}' for role, reason in unavailable.items()))
    if directory.exists():
        raise ValueError(f'{directory} already exists; use a new search ID')

    result_path = directory / 'result.json'
    directory.mkdir(parents=True)
    trace = directory / 'trace.jsonl'
    trace.touch()
    results = []
    for case in selected:
        if args.attack == 'delete':
            prompt = tap.exposure_prompt(case)
            probe = tap.make_delete_target(target, case['task_id'], prompt)
        else:
            prompt = suite.get_user_task_by_id(case['task_id']).PROMPT
            probe = tap.make_target(target, case['task_id'], prompt, seed=config['seed'])
        print(f"[{case['task_id']}] searching", flush=True)
        try:
            outcome = tap.search(
                case, prompt,
                attacker=tap.make_attacker(attacker, seed=config['seed'], forbid_real=args.no_real_value),
                evaluator=tap.make_evaluator(evaluator, seed=config['seed']),
                target=probe,
                config=config,
                freeze_best=args.freeze_best,
                record=lambda event, **values: write_trace(trace, event, task_id=case['task_id'], **values))
            outcome['status'] = 'completed'
        except (LlmError, tap.TapError) as exc:
            print(f"[{case['task_id']}] ERROR: {exc}", flush=True)
            outcome = {'task_id': case['task_id'], 'status': 'error', 'error': str(exc)}
        results.append(outcome)
        if outcome['status'] == 'completed':
            print(f"[{case['task_id']}] {outcome['source']} success={outcome['success']} "
                  f"label={outcome['label']} queries={outcome['queries']} stopped={outcome['stopped']}", flush=True)
        result_path.write_text(json.dumps({'search_id': search_id, 'protocol': PROTOCOL_VERSION,
                                           'config': config, 'cases': results}, ensure_ascii=False, indent=2,
                                          default=str) + '\n', encoding='utf-8')

    completed = [r for r in results if r['status'] == 'completed']
    failed = [r for r in results if r['status'] != 'completed']
    if completed:
        payloads = tap.build_payloads(completed, search_id=search_id, protocol=PROTOCOL_VERSION,
                                      llms={'attacker': describe(attacker), 'evaluator': describe(evaluator),
                                            'target': describe(target)},
                                      options={'forbid_real': bool(args.no_real_value),
                                               'freeze_best': bool(args.freeze_best)})
        digest = tap.write_payloads(directory / 'payloads.json', payloads)
        (directory / 'report.md').write_text(render_report(results, payloads), encoding='utf-8')
        print(f"Frozen payloads: {directory / 'payloads.json'} (sha256 {digest})")
        print(f"Run a trial with: python -m lab.dojo --tap-payloads {directory / 'payloads.json'} "
              f"--tasks {' '.join(c['task_id'] for c in completed)}" +
              (' --attack delete' if args.attack == 'delete' else ''))
    if failed:
        print(f"{len(failed)} case(s) failed; see {result_path}")
        raise SystemExit(1)


if __name__ == '__main__':
    main()
