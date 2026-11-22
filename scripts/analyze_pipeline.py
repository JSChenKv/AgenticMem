"""Analyze all saved workflows without model calls or changes to source runs.

Extends aditya/8183c91's five-stage analysis. V1 reports remain untouched.
V2 reports contain per-session evidence and provisional classifications.
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


def cell(value):
    if value is None:
        return 'Not recorded / needs review'
    if isinstance(value, bool):
        return 'Yes' if value else 'No'
    return str(value).replace('|', '\\|').replace('\n', ' ')


def render(analyses):
    lines = ['# Five-stage analysis — v2', '',
             'Separate reanalysis of saved evidence. Original summaries and native utility are unchanged.',
             'Automatic asserted-value labels are provisional and require review. Missing data is not a negative outcome.',
             'Historical workflows remain separate. Do not pool them into an attack success rate.',
             'Unranked historical retrieval unions are never assigned fabricated per-query ranks.', '']
    for analysis in analyses:
        lines += [f"## {analysis['run_id']}", '',
                  f"Workflow: {analysis['workflow']}. Source SHA-256: {analysis['source_sha256']}.", '',
                  '| Task | Condition | Session | Seen | Repeated | Saved | Target rank | Real rank | Native utility | Automatic outcome | Review |',
                  '| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |']
        for r in analysis['rows']:
            lines.append('| ' + ' | '.join(cell(r.get(k)) for k in (
                'task_id', 'condition', 'stage', 'saw_attack', 'repeated_in_answer', 'saved_to_memory',
                'attacker_rank', 'real_rank', 'native_utility', 'answer_time_outcome', 'review_status')) + ' |')
        lines += ['', 'Exclusions and all clause-level evidence are retained in the JSON; no rows are silently dropped.', '']
    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=ROOT / 'results' / 'runs')
    parser.add_argument('--output', type=Path, default=ROOT / 'results' / 'analysis')
    args = parser.parse_args()
    analyses = []
    for path in sorted(args.source.glob('dojo_*/summary.json')):
        run = json.loads(path.read_text(encoding='utf-8'))
        review_path = path.parent / 'analysis-reviews.json'
        reviews = json.loads(review_path.read_text(encoding='utf-8')) if review_path.exists() else None
        analyses.append(analyze_run(run, reviews))
    if not analyses:
        raise ValueError('No saved run summaries found')
    args.output.mkdir(parents=True, exist_ok=True)
    output = {'schema': VERSION, 'classifier_version': CLASSIFIER_VERSION, 'analyses': analyses}
    (args.output / 'pipeline_stages_v2.json').write_text(json.dumps(output, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    (args.output / 'pipeline_stages_v2.md').write_text(render(analyses), encoding='utf-8')
    print(f"Analyzed {len(analyses)} runs / {sum(len(a['rows']) for a in analyses)} session rows. No model calls.")


if __name__ == '__main__':
    main()
