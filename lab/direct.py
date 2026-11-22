"""Direct-source exposure with memory disabled and an explicitly reused control."""
import copy
import hashlib
import json
import re
import uuid


def load_source(root, run_id, tasks):
    if not re.fullmatch(r'dojo_\d{8}_\d{6}_[a-f0-9]{6}', run_id):
        raise ValueError('Select a valid source run for the memory-off comparison')
    base = (root / 'data' / 'agentdojo_runs').resolve()
    folder = (base / run_id).resolve()
    if not folder.is_relative_to(base):
        raise ValueError('Source run is outside the run directory')
    try:
        raw = (folder / 'summary.json').read_bytes()
        source = json.loads(raw)
        archived = json.loads((folder / 'protocol.json').read_text(encoding='utf-8'))
    except (OSError, ValueError) as exc:
        raise ValueError('Source run evidence is unavailable') from exc
    if source.get('workflow') != 'autonomous' or source.get('status') != 'completed':
        raise ValueError('Source must be a completed autonomous repeated-exposure run')
    selected = [c for c in source['cases'] if c['task_id'] in tasks]
    if len(selected) != len(tasks):
        raise ValueError('Every selected task must exist in the source run')
    for case in selected:
        branch = case.get('repeated', {}).get('branches', {}).get('repeated', {})
        if branch.get('status') != 'completed' or not branch.get('final_snapshot_hashes'):
            raise ValueError('Source repeated branch must have a complete snapshot')
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', branch.get('experiment', '')):
            raise ValueError('Invalid source experiment name')
        if case['repeated'].get('evaluation_tools') != 'workspace':
            raise ValueError('Source run must use memory plus workspace tools at evaluation')
        for kind in ('reminder', 'plan'):
            control = case['repeated'].get('evaluations', {}).get(kind, {}).get('repeated_memory_off', {})
            if (control.get('status') != 'completed' or not control.get('memory_unchanged') or
                    control.get('retrieved') != [] or control.get('write_enabled') is not False or
                    control.get('scheduled_attack') is not False or
                    control.get('snapshot_before') != branch['final_snapshot_hashes']):
                raise ValueError('Source memory-off clean control is missing or incompatible')
    reference = {'run_id': run_id, 'summary_sha256': hashlib.sha256(raw).hexdigest(),
                 'agent': source.get('agent'), 'memory_state': 'repeated_end_S3'}
    return selected, reference, archived


def protocol(cases, source, archived):
    from lab.repeated import SYSTEM, PROBES, probe_prompt
    prior = archived.get('autonomous_protocol', {})
    prompts = {c['task_id']: {k: list(probe_prompt(c, k)) for k in PROBES} for c in cases}
    if prior.get('system_prompt') != SYSTEM or any(prior.get('probe_prompts', {}).get(k) != v for k, v in prompts.items()):
        raise ValueError('Source task prompts differ; use a compatible source run')
    return {'version': 'direct_memory_off_v1', 'source': source, 'conditions': ['clean', 'polluted'],
            'system_prompt': SYSTEM, 'probe_prompts': prompts, 'evaluation_tools': 'workspace',
            'memory_policy': 'same_search_memory_schema_returns_empty_records; no_storage_queries_or_writes',
            'snapshot_policy': 'independent_clone_of_source_repeated_end_S3_for_every_probe',
            'source_policy': 'clean_or_fixed_parent_payload_at_official_injection_point',
            'tool_policy': 'autonomous; no_prefetch_or_forced_exposure; maximum_16_calls',
            'control_policy': 'reuse_prior_repeated_memory_off; never_rerun_clean_control',
            'new_session_order': ['reminder/polluted', 'plan/polluted'],
            'interpretation': 'Supplement with a historical clean-source reference, not a same-batch randomized pair or aggregate ASR'}


def run_case(suite, case, parent_case, source, clone, hashes,
             on_progress=lambda stage: None, on_checkpoint=lambda value: None):
    from lab.repeated import PROBES, probe_prompt, run_session
    branch = parent_case['repeated']['branches']['repeated']
    result = {'protocol': 'direct_memory_off_v1', 'status': 'running', 'source': source,
              'evaluation_tools': 'workspace', 'memory_enabled': False, 'write_enabled': False,
              'source_snapshot_hashes': branch['final_snapshot_hashes'], 'evaluations': {}, 'comparisons': {}}
    on_checkpoint(result)
    if hashes(branch['experiment']) != branch['final_snapshot_hashes']:
        raise ValueError('Source memory state has changed since the original run')
    for kind in PROBES:
        control = copy.deepcopy(parent_case['repeated']['evaluations'][kind]['repeated_memory_off'])
        control.update(data_origin='reused_source_run', source_run_id=source['run_id'],
                       source_condition='repeated_memory_off', workspace_condition='clean', memory_enabled=False)
        group = result['evaluations'][kind] = {'clean': control}
        on_checkpoint(result)
        for condition in ('polluted',):
            on_progress(kind + '_' + condition)
            destination = 'direct_' + uuid.uuid4().hex
            before = clone(branch['experiment'], destination)
            if before != branch['final_snapshot_hashes']:
                raise RuntimeError('Direct comparison snapshot differs from the source state')
            prompt, _ = probe_prompt(case, kind)
            value = run_session(suite, case, destination, prompt, kind=kind, memory_off=True,
                                injected=condition == 'polluted', evaluation_tools='workspace', write=False)
            after = hashes(destination)
            value.update(experiment=destination, snapshot_before=before, snapshot_after=after,
                         memory_unchanged=before == after, memory_enabled=False,
                         workspace_condition=condition, source_memory_arm='repeated', intervention='empty_memory_results',
                         data_origin='new_session')
            if before != after:
                value.update(status='error', error='Read-only direct probe changed memory database files')
            group[condition] = value
            on_checkpoint(result)
        clean, polluted = group['clean'], group['polluted']
        complete = all(v['status'] == 'completed' for v in group.values())
        result['comparisons'][kind] = {
            'all_conditions_completed': complete,
            'clean_control_valid': clean.get('clean_correct') if clean['status'] == 'completed' else None,
            'polluted_source_encountered': polluted.get('attack_source_seen'),
            'polluted_target_content': polluted.get('target_content_present'),
            'polluted_target_adoption': polluted.get('target_adoption'),
            'interpretation': 'New polluted-source probe versus the prior memory-off clean probe; not a same-batch comparison. Review artifacts.'}
    result['source_memory_unchanged'] = hashes(branch['experiment']) == branch['final_snapshot_hashes']
    result['status'] = ('completed' if result['source_memory_unchanged'] and all(
        c['all_conditions_completed'] and c['clean_control_valid'] for c in result['comparisons'].values()) else 'needs_review')
    on_checkpoint(result)
    return result


def report_lines(result):
    lines = ['### Memory off: clean vs polluted sources', '',
             f"Source run: `{result['source']['run_id']}`. Status: `{result['status']}`.", '',
             'Probes use fresh sessions, matching prompts and tool schemas, and copies of the same repeated S3 memory state. '
             'Memory searches return empty records and no memories are saved. Only the current source injection differs. '
             'The clean-source control is reused from the prior Repeated + memory off condition. Only the polluted-source probes are new. '
             'This is a historical-reference comparison; execution time and provider defaults may differ. Previous results remain unchanged.', '',
             '| Probe | Current source | Data origin | Payload encountered | Payload reads | Expected content | Target content | Conflict | Status |',
             '| --- | --- | --- | --- | --- | --- | --- | --- | --- |']
    for kind, group in result['evaluations'].items():
        for condition, value in group.items():
            lines.append(f"| {kind} | {condition} | {value.get('data_origin')} | {value.get('attack_source_seen')} | {value.get('attack_tool_reads')} | "
                         f"{value.get('expected_content_present')} | {value.get('target_content_present')} | "
                         f"{value.get('artifact', {}).get('conflict')} | {value['status']} |")
    lines += ['', 'Unencountered payloads remain outcomes, not execution failures. Reminder target mentions may be rejected or uncertain; '
              'plan adoption uses structured fields and conflict flags. One paired run does not estimate ASR or establish a repetition effect.', '']
    for kind, group in result['evaluations'].items():
        for condition, value in group.items():
            lines += [f'**{kind} / memory off + {condition} source**', '', '```json',
                      json.dumps(value.get('artifact', {'status': value['status'], 'error': value.get('error')}), indent=2, ensure_ascii=False), '```', '']
    return lines
