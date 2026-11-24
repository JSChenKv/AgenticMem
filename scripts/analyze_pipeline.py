"""Analyze current three-condition runs without model calls or changes to source runs.

Extends aditya/8183c91's five-stage analysis. The source evidence is never modified.
Reports contain per-session evidence and provisional classifications. Output:
results/analysis/pipeline_stages.{md,json} (the schema version is inside the files).
"""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from lab.pipeline import analyze_run, VERSION
from lab.values import VERSION as CLASSIFIER_VERSION

COLUMNS = [('task_id', 'Task'), ('repeat', 'Repeat'), ('schedule', 'Schedule'), ('condition', 'Condition'),
           ('stage', 'Session'), ('answer_model', 'Answered by'), ('saw_attack', 'Payload seen'),
           ('consulted', 'Consulted'), ('repeated_in_answer', 'Asserts attacker value'), ('saved_as_fact', 'Saved as fact'),
           ('attacker_content_saved', 'Attacker content saved (any framing)'),
           ('store_attacker_fact_records', 'Stored attacker-value records'), ('store_real_fact_records', 'Stored real-value records'),
           ('memory_search_count', 'Memory searches'), ('attacker_content_rank', 'Attacker content rank'),
           ('real_rank', 'Real rank'), ('native_utility', 'Native utility'), ('answer_time_outcome', 'Automatic outcome'),
           ('review_status', 'Review')]


def text(value):
    if isinstance(value, bool):
        return 'Yes' if value else 'No'
    return str(value).replace('|', '\\|').replace('\n', ' ')


def cell(row, key):
    """Say WHY a value is empty instead of printing one generic 'not recorded'."""
    value = row.get(key)
    if value is not None:
        return text(value)
    memory_off = row.get('memory_enabled') is False or 'memory_off' in str(row.get('condition'))
    if key in ('attacker_content_rank', 'real_rank'):
        if memory_off:
            return 'memory off'
        if row.get('memory_search_count') == 0:
            return 'no memory search'
        if row.get('memory_search_count'):
            return 'not retrieved'
    if key in ('saved_as_fact', 'attacker_content_saved') and row.get('write_enabled') is False:
        return 'no write'
    if key == 'native_utility' and row.get('stage', '').startswith('S'):
        return 'not scored'
    if key == 'repeated_in_answer':
        return 'ambiguous (review)'
    if key == 'answer_model':
        return 'task agent' if row.get('stage', '').startswith('Final/memory') else '—'
    if key in ('repeat', 'schedule'):
        return '—'
    return 'not recorded'


def render(analyses):
    lines = ['# Five-stage analysis', '',
             f'Schema `{VERSION}`, classifier `{CLASSIFIER_VERSION}`. Separate reanalysis of saved evidence; '
             'original summaries and native utility are unchanged.',
             'Automatic asserted-value labels are provisional and require review. Missing data is not a negative outcome.',
             'Do not pool runs with different configurations into an attack success rate.',
             '*Saved as fact* means a new record asserts the attacker value. *Attacker content* includes quoted or rejected '
             'mentions; quoting to reject is not adoption. Ranks are 1-based within each search. *Stored … records* count the '
             'whole store after the session. *Consulted* says whether the session read the workspace source, searched memory, or both.', '']
    for analysis in analyses:
        lines += [f"## {analysis['run_id']}", '',
                  f"Workflow: {analysis['workflow']}. Source SHA-256: {analysis['source_sha256']}.", '',
                  '| ' + ' | '.join(title for _, title in COLUMNS) + ' |',
                  '| ' + ' | '.join('---' for _ in COLUMNS) + ' |']
        for row in analysis['rows']:
            lines.append('| ' + ' | '.join(cell(row, key) for key, _ in COLUMNS) + ' |')
        lines += ['', 'Exclusions and all clause-level evidence are retained in the JSON; no rows are silently dropped.', '']
    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    # main's published runs plus the teammate-branch run of aditya v3 (stored separately on main).
    parser.add_argument('--source', type=Path, nargs='+', default=[ROOT / 'results' / 'runs', ROOT / 'results' / 'teammate' / 'runs'])
    parser.add_argument('--output', type=Path, default=ROOT / 'results' / 'analysis')
    args = parser.parse_args()
    analyses = []
    for path in sorted(path for source in args.source for path in source.glob('dojo_*/summary.json')):
        run = json.loads(path.read_text(encoding='utf-8'))
        if run.get('workflow') != 'sustained':
            raise ValueError(f'Unsupported workflow in {path.parent.name}')
        review_path = path.parent / 'analysis-reviews.json'
        reviews = json.loads(review_path.read_text(encoding='utf-8')) if review_path.exists() else None
        analyses.append(analyze_run(run, reviews))
    if not analyses:
        print('No saved runs to analyze. Start and export a three-condition experiment first.')
        return
    args.output.mkdir(parents=True, exist_ok=True)
    output = {'schema': VERSION, 'classifier_version': CLASSIFIER_VERSION, 'analyses': analyses}
    (args.output / 'pipeline_stages.json').write_text(json.dumps(output, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    (args.output / 'pipeline_stages.md').write_text(render(analyses), encoding='utf-8')
    print(f"Analyzed {len(analyses)} runs / {sum(len(a['rows']) for a in analyses)} session rows. No model calls.")


if __name__ == '__main__':
    main()
