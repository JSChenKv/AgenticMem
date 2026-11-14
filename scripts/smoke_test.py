"""Real model integration check; every invocation uses isolated disk state."""
import json
import uuid
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lab.core import Lab, ROOT

experiment = 'smoke_' + uuid.uuid4().hex[:10]
lab = Lab(experiment)
report = {'experiment': experiment}
try:
    response = lab.add('alice', [{'role': 'user', 'content': 'My research project codename is Cedar. My preferred programming language is Python.'}])
    assert response['results'], 'Mem0 extracted no facts from clean input'
    assert all(item['event'] == 'ADD' for item in response['results']), response
    assert lab.memories('alice')
    assert lab.memories('bob') == [], 'User isolation failed'
    original_ids = {item['id'] for item in lab.memories('alice')}
    # Force a fully closed/reopened database and a new agent with no chat history.
    lab.close()
    lab = Lab(experiment)
    assert original_ids <= {item['id'] for item in lab.memories('alice')}
    result = lab.ask('alice', 'What is my research project codename and preferred programming language?')
    assert result['retrieved']['results'], 'Persistent retrieval failed'
    assert 'cedar' in result['answer'].lower(), result['answer']
    assert 'python' in result['answer'].lower(), result['answer']
    report['cross_session_answer'] = result
    document_result = lab.ingest_document('document_user', 'clean.txt')
    assert document_result['results'], 'Document summary generated no memories'
    documents = lab.memories('document_user')
    assert all(item.get('metadata', {}).get('source') == 'external_document_summary' for item in documents)
    report['document_ingest'] = document_result
    report['status'] = 'passed'
finally:
    lab.close()
    (ROOT / 'logs').mkdir(exist_ok=True)
    path = ROOT / 'logs' / 'smoke-report.json'
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))
