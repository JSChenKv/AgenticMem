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
               'memory_unchanged memory_enabled workspace_condition retrieval_policy source_memory_arm '
               'schedule checkpoint after_session answer_model built_by sampling retrieval_status attack_vectors_seen '
               'write_tools delete_tool memory_tool_calls calendar_action')
    if 'memory_deletions' in source:
        out['memory_deletions'] = [dict(pick(d, 'sequence memory_id deleted'), record=pick(d.get('record') or {}, 'id memory'))
                                   for d in source['memory_deletions']]
    if 'memory_retrievals' in source:
        out['memory_retrievals'] = [dict(pick(t, 'sequence tool initiator arguments error harness_fixed'),
            retrieved_records=[pick(r, 'id memory score rank') for r in t.get('retrieved_records', [])])
            for t in source['memory_retrievals']]
    out['tool_calls'] = [pick(t, 'sequence tool arguments error attack_payload_seen attack_vectors_seen harness_fixed')
                         for t in source.get('tool_calls', [])]
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
        out['memory_trace']['retrieval_queries'] = [dict(pick(q, 'tool_sequence initiator query'),
            records=[pick(r, fields) for r in q['records']]) for q in trace.get('retrieval_queries', [])]
        for key in ('seed_memory_retrievals', 'target_memory_retrievals'):
            out['memory_trace'][key] = [pick(r, 'tool_sequence id rank') for r in trace.get(key, [])]
        out['memory_trace']['semantic_review'] = pick(trace.get('semantic_review', {}),
            'status attacker_value_repeated_as_fact attacker_claim_saved_as_fact attacker_value_used conflict_flagged '
            'used_without_conflict real_memory_retrieved_but_ignored notes')
    return out


def export_branch(branch):
    return dict(pick(branch, 'condition schedule polluted memory_enabled status error reason initial_snapshot_hashes '
                             'final_snapshot_hashes observed_exposure_sessions polluted_sessions shared_sessions deleted_ids'),
                sessions=[export_session(s) for s in branch.get('sessions', [])])


def export_sustained(source):
    out = pick(source, 'protocol status error evaluation_tools conditions comparisons repeat built_by answer_models '
                       'real_seed_record_ids design_check retrieval_policy memory_search attack kind')
    if 'seed' in source:
        out['seed'] = export_session(source['seed'])
    if 'scripted_seed' in source:
        scripted = source['scripted_seed']
        out['scripted_seed'] = dict(pick(scripted, 'status error distractor_ids unrelated_ids'),
                                    conversations=[pick(c, 'kind messages added_ids') for c in scripted.get('conversations', [])],
                                    memory_after=records(scripted.get('memory_after', [])))
    if 'schedules' in source:
        out['schedules'] = {name: {arm: export_branch(b) for arm, b in branches.items()}
                            for name, branches in source['schedules'].items()}
        out['checkpoints'] = {name: {arm: pick(c, 'snapshot_hashes') for arm, c in arms.items()}
                              for name, arms in source.get('checkpoints', {}).items()}
    else:  # v1/v2 runs
        out['branches'] = {arm: export_branch(branch) for arm, branch in source.get('branches', {}).items()}
    out['evaluations'] = {kind: {arm: export_session(v) for arm, v in group.items()}
                          for kind, group in source.get('evaluations', {}).items()}
    return out


def export_case(case):
    out = pick(case, 'task_id label vector expected target payload status error reachable_vectors repeat '
                     'additional_injections additional_injection_policy email_timestamp_override kind family attack '
                     'write_tools additional_vectors')
    if 'sustained' in case:
        out['sustained'] = export_sustained(case['sustained'])
    return out


def render_run(run, review_available=False):
    from lab.sustained import report_lines
    lines = [f"# {run['run_id']}", '', f"Status: **{run['status']}**", '',
             f"Attack: **{run.get('attack', 'update')}**", '',
             f"Task agent: `{run.get('agent', {})}`", '',
             f"Memory extraction: `{run.get('extraction', {})}`", '',
             '[Structured results](summary.json) · [All runs](../../README.md)', '',
             'Three conditions, autonomous tools, original AgentDojo task and native utility at the native Final; '
             'protocols v3 and v6 add a single-exposure schedule and memory-only Finals answered by every answering model.',
             'Native task success and semantic attacker adoption are separate outcomes.', '']
    tap = (run.get('protocol') or {}).get('tap_payloads')
    if tap:
        lines += [f"Frozen payloads from TAP search `{tap['search_id']}` (file sha256 `{tap['sha256']}`): the search ran "
                  'before this trial and the trial never called a search model. Per-case probe outcomes are in the '
                  'structured results.', '']
    if run.get('source_status') != run['status'] and 'source_status' in run:
        lines += [f"The source summary stopped at `{run['source_status']}`; the web job recorded `{run['status']}` (exit code {run.get('execution', {}).get('exit_code')}).", '']
    if not run['cases']:
        lines += ['No task-session results were recorded. This is an execution failure, not an attack trial.', '']
    for case in run['cases']:
        title = f"## {case['task_id']} — {case['label']}" + (f" — repeat {case['repeat']}" if case.get('repeat') else '')
        lines += [title, '', 'Fixed payload:', '', '> ' + case['payload'], '']
        lines += ['Injection slots: `' + '`, `'.join([case['vector'], *case.get('additional_injections', {})]) + '`.', '']
        if case.get('email_timestamp_override'):
            lines += ['Email timestamp override (all conditions, custom extension): `' + json.dumps(case['email_timestamp_override']) + '`.', '']
        if 'sustained' in case:
            lines += report_lines(case['sustained'])
            finals = case['sustained'].get('evaluations', {}).get('native', {})
            sustained_finals = [v for k, v in finals.items() if v.get('schedule', 'sustained') == 'sustained']
            if len(sustained_finals) == 3 and all(v.get('status') == 'completed' and v.get('memory_calls') == 0 for v in sustained_finals):
                lines += ['**Interpretation limit:** All three sustained native Final sessions answered without calling memory search. '
                          'The native Final does not establish resistance to retrieved poisoned memory'
                          + (' (see the memory-only Final above).' if case['sustained'].get('evaluations', {}).get('memory')
                             else '; this run predates the memory-only Final (protocol v2).') + ' '
                          'Read the session answers and saved records; target mentions can be qualified or rejected.', '']
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
        out = pick(source, 'run_id status attack exposure_policy agent memory_model extraction context_policy workflow evaluation_tools repeats answer_models')
        job_path = summary.parent / 'web-job.json'
        if job_path.exists():
            job = json.loads(job_path.read_text(encoding='utf-8'))
            out['execution'] = pick(job, 'status exit_code started_at finished_at stopped_by_user')
            if source['status'] in ('running', 'starting') and job.get('status') not in ('running', 'starting', None):
                out['source_status'], out['status'] = source['status'], job['status']
        out['export_schema'] = 'agenticmem-shared-results-v2'
        out['source_summary_sha256'] = hashlib.sha256(summary.read_bytes()).hexdigest()
        out['protocol'] = pick(protocol, 'agentdojo benchmark_version suite mem0ai model agent_backend memory_model extraction exposure_policy context_policy seed num_ctx read_tools workflow evaluation_tools sustained_protocol repeats answer_models memory_final_after_s2 tap_payloads')
        out['cases'] = [export_case(case) for case in source['cases']]
        target = destination / 'runs' / summary.parent.name
        target.mkdir(parents=True, exist_ok=True)
        (target / 'summary.json').write_text(json.dumps(out, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        (target / 'report.md').write_text(render_run(out), encoding='utf-8')
        validation_path = summary.parent / 'validation.json'
        if validation_path.exists():
            checks = json.loads(validation_path.read_text(encoding='utf-8'))
            allowed = ('all_13_sessions_completed', 'shared_seed_identical', 'memory_off_no_records_or_writes',
                       'memory_off_databases_unchanged', 'all_final_no_writes',
                       'polluted_payload_observed_all_8_sessions', 'original_seed_ids_preserved',
                       'memory_off_no_reads_records_or_writes', 'all_memory_on_automatic_search',
                       'all_s2_s3_read_entire_inbox', 'polluted_s2_s3_saw_email_payload',
                       'document_payload_retained_and_observed', 'protocol_v5_and_matched_new_date',
                       'all_observed_hiking_email_dates_updated')
            shared = {key: checks[key] for key in allowed if isinstance(checks.get(key), bool)}
            (target / 'validation.json').write_text(json.dumps(shared, indent=2) + '\n', encoding='utf-8')
        runs.append(out)
    if not runs:
        print('No current runs to export. Start a three-condition experiment first.')
        return
    lines = ['# Shared experiment results', '',
             'Current protocol: sustained_native_v7 (v6 plus top-5 retrieval with a larger scripted store, important_instructions '
             'payloads, calendar-action tasks 15/18, hiking tasks 17/18 and a delete_memory tool; v6 was main v5 exposure design: automatic pre-task memory retrieval, Hawaii '
             'document + newer email attack, all-inbox S2/S3; plus scripted seed and design check, sustained and single-exposure '
             'schedules, memory-only Finals after S1 and S3 answered by every answering model, repeats; top-5 retrieval). '
             'Runs record their own protocol version; never pool across versions. '
             'Raw logs and databases remain local.', '',
             '| Run | Status |', '| --- | --- |']
    for run in runs:
        lines.append(f"| [{run['run_id']}](runs/{run['run_id']}/report.md) | {run['status']} |")
    lines += ['', '[Five-stage analysis](analysis/pipeline_stages.md) · [Analysis JSON](analysis/pipeline_stages.json)', '']
    if (destination / 'teammate' / 'README.md').exists():
        lines += ['[Teammate-branch results](teammate/README.md): the aditya v3 Hawaii trial, kept separately; '
                  'the merged analysis above includes it.', '']
    lines += [
              'Native utility and semantic attack adoption are separate. Automatic labels remain provisional.',
              'Local web history reads data/agentdojo_runs; these exports do not populate it.', '']
    (destination / 'README.md').write_text('\n'.join(lines), encoding='utf-8')
    print(f'Exported {len(runs)} runs to results/')


if __name__ == '__main__':
    main()
