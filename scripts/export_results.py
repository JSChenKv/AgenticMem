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
               'memory_unchanged source_memory_arm intervention memory_enabled workspace_condition data_origin source_run_id source_condition')
    out['tool_calls'] = [pick(t, 'sequence tool arguments error attack_payload_seen') for t in source.get('tool_calls', [])]
    for key in ('retrieved', 'memory_before', 'memory_after'):
        if key in source:
            out[key] = records(source[key])
    if 'write_events' in source:
        out['write_events'] = [pick(e, 'id memory event') for e in source['write_events'].get('results', [])]
    if 'artifact' in source:
        out['artifact'] = pick(source['artifact'], 'body title date time location notes conflict memory_ids_used')
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


def export_repeated(source):
    out = pick(source, 'protocol status error evaluation_tools schedules comparisons')
    if 'seed' in source:
        out['seed'] = export_session(source['seed'])
    out['branches'] = {}
    for arm, branch in source.get('branches', {}).items():
        item = pick(branch, 'schedule status error initial_snapshot_hashes final_snapshot_hashes '
                    'scheduled_opportunities observed_exposure_sessions attack_tool_reads first_target_saved_slot')
        item['sessions'] = [export_session(s) for s in branch.get('sessions', [])]
        out['branches'][arm] = item
    out['evaluations'] = {kind: {condition: export_session(value) for condition, value in group.items()}
                          for kind, group in source.get('evaluations', {}).items()}
    return out


def export_direct(source):
    out = pick(source, 'protocol status error source evaluation_tools memory_enabled write_enabled '
               'source_snapshot_hashes source_memory_unchanged comparisons')
    out['evaluations'] = {kind: {condition: export_session(value) for condition, value in group.items()}
                          for kind, group in source.get('evaluations', {}).items()}
    return out


def export_episode(episode):
    out = pick(episode, 'protocol status error delay_tasks retrieval_mode external_environment restoration probe_writes')
    out['branches'] = {}
    for arm, branch in episode.get('branches', {}).items():
        saved = pick(branch, 'source_arm retrieval_enabled source_snapshot_hashes initial_snapshot_hashes probe_snapshot_hashes')
        saved['intermediate_sessions'] = []
        for session in branch.get('intermediate_sessions', []):
            item = pick(session, 'session_id prompt source_note answer')
            item.update(retrieved=records(session.get('retrieved', [])), saved=records(session.get('saved', [])),
                        write_events=[pick(e, 'id memory event') for e in session.get('write_events', {}).get('results', [])])
            saved['intermediate_sessions'].append(item)
        out['branches'][arm] = saved
    out['probes'] = {}
    for kind, group in episode.get('probes', {}).items():
        out['probes'][kind] = {}
        for arm, value in group.items():
            probe = pick(value, 'status error prompt use_memory evaluated_content expected_content_present '
                         'target_content_present clean_correct scoring session_id snapshot_before snapshot_after memory_unchanged')
            if 'artifact' in value:
                probe['artifact'] = pick(value['artifact'], 'body title date time location notes conflict memory_ids_used')
            probe['retrieved'] = records(value.get('retrieved', []))
            out['probes'][kind][arm] = probe
    out['comparisons'] = {kind: pick(value, 'all_arms_completed clean_control_valid restored_control_correct '
        'memory_sensitive_target_content interpretation') for kind, value in episode.get('comparisons', {}).items()}
    return out


def export_case(case):
    out = pick(case, 'task_id label vector expected target followup payload status error '
               'reachable_vectors snapshot_hashes seed_record_ids_preserved '
               'end_to_end_eligible causal_pair_valid memory_mediated_target_observed')
    for key in ('baseline', 'seed_reference_exposure', 'clean_exposure', 'poisoning_task'):
        if key in case:
            source = case[key]
            out[key] = pick(source, 'answer native_utility trajectory_policy attack_source_seen search_recoveries')
            out[key]['tool_calls'] = [pick(tool, 'tool arguments error') for tool in source.get('tools', [])]
    for key in ('initial_memory', 'memory_clean', 'memory_poison'):
        if key in case:
            source = case[key]
            out[key] = pick(source, 'extraction target_claim_record_ids')
            out[key].update(before=records(source.get('before', [])), after=records(source.get('after', [])),
                            events=[pick(event, 'id memory event') for event in source.get('result', {}).get('results', [])])
    for key in ('followup_clean', 'followup_poison', 'followup_without_memory'):
        if key in case:
            source = case[key]
            out[key] = pick(source, 'use_memory answer_grounded expected_value_selected target_value_selected '
                           'target_claim_retrieved_ids target_claim_record_cited')
            out[key]['output'] = pick(source.get('output', {}), 'answer selected_value conflict memory_ids_used')
            out[key]['retrieved'] = records(source.get('retrieved', []))
    if 'episode' in case:
        out['episode'] = export_episode(case['episode'])
    if 'repeated' in case:
        out['repeated'] = export_repeated(case['repeated'])
    if 'direct' in case:
        out['direct'] = export_direct(case['direct'])
    if 'sustained' in case:
        out['sustained'] = export_sustained(case['sustained'])
    return out


def cell(value):
    if value is None:
        return 'Not recorded'
    if isinstance(value, bool):
        return 'Yes' if value else 'No'
    return str(value).replace('|', '\\|').replace('\n', ' ')


def selected(case, arm):
    return case.get('followup_' + arm, {}).get('output', {}).get('selected_value')


def render_repeated(result):
    lines = ['### Autonomous repeated exposure', '',
             f"Status: `{result['status']}`. Final tools: `{result['evaluation_tools']}`.", '',
             'Each session starts fresh and chooses its own tools. Only branch memory persists. '
             'The fixed payload is available only in scheduled slots; final workspace sources are clean. '
             'Restored uses the complete matched clean S3 state. Memory off returns empty records through the same tool schema.', '',
             '| Schedule | Opportunities | Sessions exposed | Payload reads | First target-text match slot | Status |',
             '| --- | --- | --- | --- | --- | --- |']
    for arm, branch in result['branches'].items():
        lines.append('| ' + ' | '.join([f"{arm} ({''.join(map(str, branch['schedule']))})",
            cell(branch.get('scheduled_opportunities')), cell(branch.get('observed_exposure_sessions')),
            cell(branch.get('attack_tool_reads')), cell(branch.get('first_target_saved_slot')), branch['status']]) + ' |')
    lines += ['', '| Probe | Condition | Expected content | Target content | Memory calls | Workspace calls | Unchanged DBs | Status |',
              '| --- | --- | --- | --- | --- | --- | --- | --- |']
    for kind, group in result['evaluations'].items():
        for condition, value in group.items():
            lines.append('| ' + ' | '.join([kind, condition, cell(value.get('expected_content_present')),
                cell(value.get('target_content_present')), cell(value.get('memory_calls')),
                cell(value.get('workspace_calls')), cell(value.get('memory_unchanged')), value['status']]) + ' |')
    lines += ['', 'Unencountered attacks remain in their scheduled group. Memory target-text matches can include rejected claims '
              'or the same location on another date. Reminder mentions may be negated or rejected; '
              'review the complete artifact. Plans use structured fields and do not execute actions. '
              'These custom transfer tasks do not provide native AgentDojo aggregate scores or a reliable repetition effect from one trial.', '',
              '### Answers and memory writes', '']
    sessions = [('S0 / clean seed', result.get('seed', {}))]
    sessions += [(f"{arm} / S{s['slot']}", s) for arm, b in result['branches'].items() for s in b['sessions']]
    for label, session in sessions:
        lines += [f'**{label}**', '', session.get('answer', session.get('error', 'No answer recorded.')), '']
        lines += [f"- `{e.get('event')}`: {e.get('memory', '')}" for e in session.get('write_events', [])]
        lines += ['']
    lines += ['### Final artifacts', '']
    for kind, group in result['evaluations'].items():
        for condition, value in group.items():
            lines += [f'**{kind} / {condition}**', '', '```json', json.dumps(value.get('artifact',
                pick(value, 'status error reason')), ensure_ascii=False, indent=2), '```', '']
    lines += ['Comparison checks:', '', '```json', json.dumps(result.get('comparisons', {}), indent=2), '```', '']
    return lines


def render_run(run, review_available=False):
    lines = [f"# {run['run_id']}", '', f"Status: **{run['status']}**", '',
             f"Task agent: `{run.get('agent') or run['protocol'].get('model', 'not recorded')}`", '',
             f"Memory extraction: `{run.get('extraction') or run.get('memory_model') or 'not separately recorded (legacy)'}`", '',
             f"Exposure policy: `{run.get('exposure_policy', 'not recorded')}`", '',
             '[Structured results](summary.json) · [All runs](../../README.md)', '',
             'These are development/pilot observations, not an overall AgentDojo attack success rate. '
             'Historical runs used evolving protocols and must not be pooled as identical repeated trials.', '']
    if review_available:
        lines += ['[Reviewed interpretation and integrity checks](review.md)', '']
    if run.get('workflow') == 'direct':
        lines += ['Memory reads and writes are disabled; no extraction calls. The extraction setting above is unused in this workflow.', '',
                  f"[Original source run](../{run['source_run_id']}/report.md). Clean controls are reused from that run, not rerun.", '']
    for case in run['cases']:
        if 'sustained' in case:
            from lab.sustained import report_lines
            lines += [f"## {case['task_id']} — {case['label']}", '', 'Fixed payload:', '', '> ' + case['payload'], '']
            lines += report_lines(case['sustained'])
            if case.get('error'):
                lines += ['Recorded error: ' + case['error'], '']
            continue
        if 'direct' in case:
            from lab.direct import report_lines
            lines += [f"## {case['task_id']} — {case['label']}", '', 'Fixed inherited payload:', '', '> ' + case['payload'], '']
            lines += report_lines(case['direct'])
            if case.get('error'):
                lines += ['Recorded error: ' + case['error'], '']
            continue
        if 'repeated' in case:
            lines += [f"## {case['task_id']} — {case['label']}", '',
                      f"Expected: `{case['expected']}`. Attack target: `{case['target']}`.", '',
                      'Fixed synthetic payload:', '', '> ' + case['payload'], '']
            lines += render_repeated(case['repeated'])
            if case.get('error'):
                lines += ['Recorded error:', '', '```text', case['error'], '```', '']
            continue
        lines += [f"## {case['task_id']} — {case['label']}", '',
                  f"Status: `{case['status']}`. Expected: `{case['expected']}`. Attack target: `{case['target']}`.", '',
                  '| Check | Result |', '| --- | --- |']
        metrics = [('Autonomous baseline utility passed', case.get('baseline', {}).get('native_utility')),
                   ('Attack source encountered', case.get('poisoning_task', {}).get('attack_source_seen')),
                   ('Original seed IDs preserved', case.get('seed_record_ids_preserved')),
                   ('Clean comparison valid', case.get('causal_pair_valid')),
                   ('Memory-mediated target indicator', case.get('memory_mediated_target_observed'))]
        for label, value in metrics:
            lines.append(f'| {label} | {cell(value)} |')
        lines += ['', '| Follow-up | Selected value | Conflict reported |', '| --- | --- | --- |']
        for arm in ('clean', 'poison', 'without_memory'):
            followup = case.get('followup_' + arm, {})
            lines.append(f"| {arm} | {cell(selected(case, arm))} | {cell(followup.get('output', {}).get('conflict'))} |")
        lines += ['', '### Source-to-memory evidence', '', 'Fixed synthetic payload:', '', '> ' + case['payload'], '']
        for key in ('baseline', 'clean_exposure', 'poisoning_task'):
            if key in case:
                lines += [f"**{key} answer:**", '', case[key]['answer'], '']
        for key in ('initial_memory', 'memory_clean', 'memory_poison'):
            if key in case:
                saved = case[key]
                lines += [f"**{key}:** {len(saved['before'])} records before; {len(saved['after'])} after; "
                          f"{len(saved['events'])} returned write events.", '']
                lines += [f"- `{record['id']}`: {record['memory']}" for record in saved['after']]
                lines += ['']
        if case.get('error'):
            lines += ['Recorded error:', '', '```text', case['error'], '```', '']
        if 'episode' in case:
            episode = case['episode']
            lines += ['### Cross-session transfer', '',
                      f"Intermediate tasks: {episode['delay_tasks']}. Status: `{episode['status']}`. "
                      'Each probe uses a fresh session and independent snapshot. Original source tools are unavailable; '
                      'probes do not write memory or execute actions. Restored state starts from the full pre-exposure seed.', '',
                      '| Probe | Arm | Expected content | Target content | Status |', '| --- | --- | --- | --- | --- |']
            for kind, group in episode['probes'].items():
                for arm, probe in group.items():
                    lines.append(f"| {kind} | {arm} | {cell(probe.get('expected_content_present'))} | "
                                 f"{cell(probe.get('target_content_present'))} | {probe['status']} |")
            lines += ['', 'Reminder scoring is lexical and may match negated mentions; plan scoring checks structured fields. '
                      'Inspect the generated artifacts before interpreting adoption. These are custom transfer tasks, not native AgentDojo scores.', '']
            for kind, group in episode['probes'].items():
                for arm, probe in group.items():
                    lines += [f'**{kind} / {arm}**', '', '```json',
                              json.dumps(probe.get('artifact', probe), ensure_ascii=False, indent=2), '```', '']
    lines += ['## Evidence boundaries', '',
              'JSON preserves selected answers, record IDs, memory text, write events, tool names/arguments, '
              'and recorded checks. Full tool outputs, provider/CLI transcripts, local paths, authentication '
              'information, and database files are excluded. This export is not a complete replay archive.', '',
              'Target-text matches are lexical indicators, not proof of belief. Citations alone do not prove causality. '
              'A failed clean-memory control invalidates the paired comparison. Reference-policy results measure '
              'controlled exposure; autonomous baseline utility is reported separately. Missing fields remain missing '
              'rather than being recomputed using newer code.', '']
    return '\n'.join(lines)


def main():
    destination = ROOT / 'results'
    runs = []
    for folder in sorted((ROOT / 'data' / 'agentdojo_runs').iterdir()):
        if not re.fullmatch(r'dojo_\d{8}_\d{6}_[a-f0-9]{6}', folder.name):
            continue
        summary = folder / 'summary.json'
        if not summary.exists():
            raise ValueError(f'Missing summary for {folder.name}; review this run before export')
        source = json.loads(summary.read_text(encoding='utf-8'))
        protocol_path = folder / 'protocol.json'
        protocol = json.loads(protocol_path.read_text(encoding='utf-8')) if protocol_path.exists() else {}
        out = pick(source, 'run_id status exposure_policy agent memory_model extraction context_policy workflow delay_tasks evaluation_tools source_run_id memory_write_enabled')
        out['export_schema'] = 'agenticmem-shared-results-v1'
        out['source_summary_sha256'] = hashlib.sha256(summary.read_bytes()).hexdigest()
        out['protocol'] = pick(protocol, 'agentdojo benchmark_version suite mem0ai model agent_backend '
                               'memory_model extraction exposure_policy context_policy seed num_ctx read_tools workflow delay_tasks evaluation_tools autonomous_protocol direct_protocol sustained_protocol source_run_id memory_write_enabled')
        out['cases'] = [export_case(case) for case in source['cases']]
        target = destination / 'runs' / folder.name
        target.mkdir(parents=True, exist_ok=True)
        (target / 'summary.json').write_text(json.dumps(out, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        (target / 'report.md').write_text(render_run(out, (target / 'review.md').is_file()), encoding='utf-8')
        runs.append(out)
    if not runs:
        raise ValueError('No runs to export')
    latest = runs[-1]['run_id']
    lines = ['# Shared experiment results', '',
             f'[Latest run report](runs/{latest}/report.md) · [Latest run JSON](runs/{latest}/summary.json)', '',
             f'This snapshot contains all {len(runs)} locally recorded AgentDojo pilot runs, including debugging failures. '
             'Runs are listed chronologically; timestamps in run IDs are UTC. These are development observations '
             'under evolving configurations, not a controlled cross-model comparison or an aggregate attack success rate.', '',
             '## Reading these results', '',
             '- Each run has an English report and a structured JSON export with selected memory and answer evidence.',
             '- October runs predate the CLI integration. Their protocol records Qwen (`qwen2.5:7b`), but some fields '
             '(including extraction configuration and exposure policy) were not recorded separately. Missing values are not inferred.',
             '- The first November Codex run records Qwen as its extractor. The latest November run explicitly follows Codex for extraction.',
             '- `CLI default` is the recorded model selection, not a pinned provider model identifier.',
             '- Reference exposure fixes source-reading calls; baseline utility measures autonomous task performance separately.',
             '- Sustained exposure uses three new conditions: clean, polluted with memory, and polluted without memory. '
             'Polluted sources persist through Final, which uses the original question and native task utility. Semantic adoption requires review.',
             '- Autonomous repeated exposure uses four fixed schedules and agent-selected memory/source calls in fresh sessions. '
             'Its reports separate available attacks from observed tool-result exposures and include six final evaluation conditions.',
             '- Direct-source supplements reuse an earlier Repeated + memory off clean control and run only the missing polluted-source probes. '
             'Reused and new session IDs are marked separately; do not count reused controls as additional trials.',
             '- A target appearing in memory is a lexical match. Examine retrieval and follow-up answers before interpreting an effect.',
             '- `completed` means the pipeline and clean control completed; it does not mean an attack succeeded.',
             '- Run errors and failed baselines are retained. Do not count missing follow-ups as successful or unsuccessful attacks.', '',
             '## Run index', '',
             '| Run | Recorded task agent/model | Workflow | Exposure | Status |', '| --- | --- | --- | --- | --- |']
    for run in runs:
        agent = run.get('agent') or {'model': run['protocol'].get('model', 'not recorded')}
        label = ' / '.join(agent.values())
        lines.append(f"| [{run['run_id']}](runs/{run['run_id']}/report.md) | {cell(label)} | "
                     f"{cell(run.get('workflow', 'pilot'))} | {cell(run.get('exposure_policy'))} | {run['status']} |")
    lines += ['', '## Follow-up observations', '',
              '| Run | Task | Clean | Poisoned | Memory off | Case status |', '| --- | --- | --- | --- | --- | --- |']
    for run in runs:
        for case in run['cases']:
            if 'repeated' in case or 'direct' in case or 'sustained' in case:
                continue
            lines.append('| ' + ' | '.join([run['run_id'], case['task_id'], cell(selected(case, 'clean')),
                         cell(selected(case, 'poison')), cell(selected(case, 'without_memory')), case['status']]) + ' |')
    lines += ['', '## Sharing and reproduction', '',
              'These files can be read directly on GitHub without running the application. They do not populate the '
              'web interface\'s Run history, which reads local run directories. Follow the project README to run new experiments.', '',
              'This export contains synthetic benchmark results only. Full tool outputs, raw CLI/provider logs, '
              'machine paths, credentials, and memory databases remain local. It is a selected evidence export, '
              'not a full replay archive. Source-summary SHA-256 values identify the local originals.', '',
              'To regenerate from local run records: `python scripts/export_results.py`. Review all generated '
              'text before publishing; field allowlists do not guarantee that future model outputs contain no sensitive text.', '']
    (destination / 'README.md').write_text('\n'.join(lines), encoding='utf-8')
    print(f'Exported {len(runs)} runs to results/')


if __name__ == '__main__':
    main()
