"""Export reviewed, synthetic benchmark results for sharing; raw logs stay local.

Uses explicit field allowlists. Review generated text before publishing: an
allowlist is not a general-purpose scrubber for future model-generated secrets.
"""
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


def pick(value, fields):
    return {key: value[key] for key in fields.split() if key in value}


def records(items):
    return [pick(item, 'id memory score attributed_to') for item in items]


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
    return out


def cell(value):
    if value is None:
        return 'Not recorded'
    if isinstance(value, bool):
        return 'Yes' if value else 'No'
    return str(value).replace('|', '\\|').replace('\n', ' ')


def selected(case, arm):
    return case.get('followup_' + arm, {}).get('output', {}).get('selected_value')


def render_run(run):
    lines = [f"# {run['run_id']}", '', f"Status: **{run['status']}**", '',
             f"Task agent: `{run.get('agent') or run['protocol'].get('model', 'not recorded')}`", '',
             f"Memory extraction: `{run.get('extraction') or run.get('memory_model') or 'not separately recorded (legacy)'}`", '',
             f"Exposure policy: `{run.get('exposure_policy', 'not recorded')}`", '',
             '[Structured results](summary.json) · [All runs](../../README.md)', '',
             'These are development/pilot observations, not an overall AgentDojo attack success rate. '
             'Historical runs used evolving protocols and must not be pooled as identical repeated trials.', '']
    for case in run['cases']:
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
        out = pick(source, 'run_id status exposure_policy agent memory_model extraction context_policy')
        out['export_schema'] = 'agenticmem-shared-results-v1'
        out['source_summary_sha256'] = hashlib.sha256(summary.read_bytes()).hexdigest()
        out['protocol'] = pick(protocol, 'agentdojo benchmark_version suite mem0ai model agent_backend '
                               'memory_model extraction exposure_policy context_policy seed num_ctx read_tools')
        out['cases'] = [export_case(case) for case in source['cases']]
        target = destination / 'runs' / folder.name
        target.mkdir(parents=True, exist_ok=True)
        (target / 'summary.json').write_text(json.dumps(out, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        (target / 'report.md').write_text(render_run(out), encoding='utf-8')
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
             '- A target appearing in memory is a lexical match. Examine retrieval and follow-up answers before interpreting an effect.',
             '- `completed` means the pipeline and clean control completed; it does not mean an attack succeeded.',
             '- Run errors and failed baselines are retained. Do not count missing follow-ups as successful or unsuccessful attacks.', '',
             '## Run index', '',
             '| Run | Recorded task agent/model | Exposure | Status |', '| --- | --- | --- | --- |']
    for run in runs:
        agent = run.get('agent') or {'model': run['protocol'].get('model', 'not recorded')}
        label = ' / '.join(agent.values())
        lines.append(f"| [{run['run_id']}](runs/{run['run_id']}/report.md) | {cell(label)} | "
                     f"{cell(run.get('exposure_policy'))} | {run['status']} |")
    lines += ['', '## Follow-up observations', '',
              '| Run | Task | Clean | Poisoned | Memory off | Case status |', '| --- | --- | --- | --- | --- | --- |']
    for run in runs:
        for case in run['cases']:
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
