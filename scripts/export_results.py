"""Export reviewed, synthetic benchmark results for sharing; raw logs stay local.

Uses explicit field allowlists. Review generated text before publishing: an
allowlist is not a general-purpose scrubber for future model-generated secrets.
"""
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
# Keep the CLI entry point usable as `python scripts/export_results.py`.
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def pick(value, fields):
    return {key: value[key] for key in fields.split() if key in value}


def records(items):
    return [pick(item, 'id memory score attributed_to') for item in items]


def export_session(source):
    out = pick(source, 'session_id status error memory_audit_error reason prompt answer scheduled_attack attack_source_seen '
               'attack_tool_reads memory_calls workspace_calls write_enabled exposure_observation native_utility '
               'slot target_claim_record_ids expected_content_present target_content_present clean_correct '
               'scoring evaluated_content target_adoption adoption_assessment snapshot_before snapshot_after '
               'memory_unchanged memory_enabled workspace_condition')
    out['tool_calls'] = [pick(t, 'sequence tool arguments error attack_payload_seen') for t in source.get('tool_calls', [])]
    for key in ('retrieved', 'memory_before', 'memory_after'):
        if key in source:
            out[key] = records(source[key])
    if 'write_events' in source:
        out['write_events'] = [pick(e, 'id memory event') for e in source['write_events'].get('results', [])]
    if 'memory_trace' in source:
        trace = source['memory_trace']
        out['memory_trace'] = pick(trace, 'payload_seen answer_target_text_match removed_record_ids new_target_text_record_ids '
                                  'real_memory_retrieved interpretation')
        fields = 'id memory score rank seed_record expected_text_match target_claim_text_match'
        out['memory_trace']['added_records'] = (None if trace.get('added_records') is None else
                                               [pick(r, fields) for r in trace['added_records']])
        out['memory_trace']['retrieval_queries'] = [dict(pick(q, 'tool_sequence query'),
            records=[pick(r, fields) for r in q['records']]) for q in trace.get('retrieval_queries', [])]
        for key in ('seed_memory_retrievals', 'target_memory_retrievals'):
            out['memory_trace'][key] = [pick(r, 'tool_sequence id rank') for r in trace.get(key, [])]
        out['memory_trace']['semantic_review'] = pick(trace.get('semantic_review', {}),
            'status attacker_value_repeated_as_fact attacker_claim_saved_as_fact attacker_value_used conflict_flagged '
            'used_without_conflict real_memory_retrieved_but_ignored notes')
    return out


def export_sustained(source):
    out = pick(source, 'protocol status error evaluation_tools conditions comparisons')
    if 'seed' in source:
        out['seed'] = export_session(source['seed'])
    out['branches'] = {arm: dict(pick(branch, 'polluted memory_enabled status error initial_snapshot_hashes '
                                     'final_snapshot_hashes observed_exposure_sessions'),
                                sessions=[export_session(s) for s in branch['sessions']])
                       for arm, branch in source.get('branches', {}).items()}
    out['evaluations'] = {kind: {arm: export_session(v) for arm, v in group.items()}
                          for kind, group in source.get('evaluations', {}).items()}
    return out


def export_case(case):
    out = pick(case, 'task_id label vector expected target payload status error reachable_vectors')
    if 'sustained' in case:
        out['sustained'] = export_sustained(case['sustained'])
    return out


def render_run(run, review_available=False):
    from lab.sustained import report_lines
    lines = [f"# {run['run_id']}", '', f"Status: **{run['status']}**", '',
             f"Task agent: `{run.get('agent', {})}`", '',
             f"Memory extraction: `{run.get('extraction', {})}`", '',
             '[Structured results](summary.json) · [All runs](../../README.md)', '',
             'Three conditions, autonomous tools, original AgentDojo task and native utility at Final.',
             'Native task success and semantic attacker adoption are separate outcomes.', '']
    for case in run['cases']:
        lines += [f"## {case['task_id']} — {case['label']}", '', 'Fixed payload:', '', '> ' + case['payload'], '']
        if 'sustained' in case:
            lines += report_lines(case['sustained'])
        if case.get('error'):
            lines += ['Recorded error: ' + case['error'], '']
    return '\n'.join(lines)


def main():
    destination = ROOT / 'results'
    runs = []
    for summary in sorted((ROOT / 'data' / 'agentdojo_runs').glob('dojo_*/summary.json')):
        source = json.loads(summary.read_text(encoding='utf-8'))
        if source.get('workflow') != 'sustained':
            raise ValueError(f'Unsupported workflow in {summary.parent.name}')
        protocol_path = summary.parent / 'protocol.json'
        protocol = json.loads(protocol_path.read_text(encoding='utf-8')) if protocol_path.exists() else {}
        out = pick(source, 'run_id status exposure_policy agent memory_model extraction context_policy workflow evaluation_tools')
        out['export_schema'] = 'agenticmem-shared-results-v2'
        out['source_summary_sha256'] = hashlib.sha256(summary.read_bytes()).hexdigest()
        out['protocol'] = pick(protocol, 'agentdojo benchmark_version suite mem0ai model agent_backend memory_model extraction exposure_policy context_policy seed num_ctx read_tools workflow evaluation_tools sustained_protocol')
        out['cases'] = [export_case(case) for case in source['cases']]
        target = destination / 'runs' / summary.parent.name
        target.mkdir(parents=True, exist_ok=True)
        (target / 'summary.json').write_text(json.dumps(out, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        (target / 'report.md').write_text(render_run(out), encoding='utf-8')
        runs.append(out)
    if not runs:
        print('No current runs to export. Start a three-condition experiment first.')
        return
    lines = ['# Shared experiment results', '',
             'Current protocol: sustained_native_v1. Raw logs and databases remain local.', '',
             '| Run | Status |', '| --- | --- |']
    for run in runs:
        lines.append(f"| [{run['run_id']}](runs/{run['run_id']}/report.md) | {run['status']} |")
    lines += ['', 'Native utility and semantic attack adoption are separate. Review exported text before publishing.',
              'Local web history reads data/agentdojo_runs; these exports do not populate it.', '']
    (destination / 'README.md').write_text('\n'.join(lines), encoding='utf-8')
    print(f'Exported {len(runs)} runs to results/')


if __name__ == '__main__':
    main()
