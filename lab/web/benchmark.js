const $ = id => document.getElementById(id);
const labels = { user_task_14: 'Family reunion', user_task_30: 'Hawaii itinerary' };
const sustainedStages = [['baseline', 'Clean seed'], ['session_1', 'S1'], ['session_2', 'S2'], ['session_3', 'S3'], ['native_final', 'Original task']];
const statusLabels = { starting: 'Starting', running: 'Running', completed: 'Completed', needs_review: 'Needs review', error: 'Process error', interrupted: 'Interrupted', incomplete: 'Incomplete', baseline_failed: 'Autonomous baseline failed' };
let selectedRun = '', activeRun = null, loading = false, submitting = false, timer, selectionVersion = 0;
function el(tag, className, text) { const node = document.createElement(tag); if (className) node.className = className; if (text !== undefined) node.textContent = text; return node; }
async function request(url, options) {
  const response = await fetch(url, { cache: 'no-store', ...options });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : `Request failed (${response.status}).`);
  return data;
}
function showError(id, error) { $(id).textContent = error.message || String(error); $(id).hidden = false; }
function setControls() {
  $('run-button').disabled = submitting || Boolean(activeRun);
  $('run-button').textContent = submitting ? 'Starting…' : activeRun ? 'Experiment running…' : 'Run selected cases ↗';
  document.querySelectorAll('#run-form input, #run-form select').forEach(input => input.disabled = submitting || Boolean(activeRun));
  $('memory-model').disabled = submitting || Boolean(activeRun) || $('memory-backend').value === 'follow';
  $('policy').disabled = true;
  $('policy').value = 'agent';
  $('policy-help').textContent = 'Agent-selected tools in every session. Both polluted conditions retain the payload through Final. Memory off applies to the entire timeline.';
}
function evidence(title, text) { const details = el('details', 'evidence'); details.append(el('summary', '', title), el('pre', '', typeof text === 'string' ? text : JSON.stringify(text, null, 2))); return details; }
function analysisValue(value) { return value == null ? 'Not recorded / needs review' : value ? 'Yes' : 'No'; }
function renderAnalysis(analysis) {
  const panel = $('analysis-panel'); panel.hidden = false;
  const priorFilter = panel.querySelector('[data-analysis-filter]')?.value || 'final';
  panel.replaceChildren(el('span', 'eyebrow', 'RESEARCH ANALYSIS · SEPARATE FROM NATIVE SCORING'), el('h2', '', 'Follow each stage'));
  panel.append(el('p', 'config-note', 'Seen → Repeated in answer → Saved → Retrieved → Adopted. Automatic labels are provisional; review the answer and evidence. Missing data is never counted as a failed attack or a deleted fact.'));
  panel.append(el('p', 'config-note', `${analysis.rows.length} session records · ${analysis.reviewed_count} reviewed · ${analysis.classifier_version}. Original results are unchanged.`));
  const download = el('a', 'api-link', 'Analysis JSON ↓'); download.href = `/benchmarks/${analysis.run_id}/analysis`; download.download = `${analysis.run_id}-analysis.json`; panel.append(download);
  if (analysis.reviews_stale) panel.append(el('p', 'case-warning', 'Earlier reviews refer to different evidence or classifier rules. They are preserved but are not applied to this analysis.'));
  const filter = el('select'); filter.dataset.analysisFilter = 'true'; filter.setAttribute('aria-label', 'Analysis sessions');
  for (const [value, text] of [['final', 'Final sessions'], ['exposure', 'S0–S3 / exposure sessions'], ['all', 'All recorded sessions']]) { const option = el('option', '', text); option.value = value; filter.append(option); }
  filter.value = priorFilter; panel.append(filter);
  const rows = el('div', 'analysis-rows'); panel.append(rows);
  function display() {
    rows.replaceChildren();
    const visible = analysis.rows.filter(r => filter.value === 'all' || (filter.value === 'final') === (r.stage.startsWith('Final')));
    if (!visible.length) rows.append(el('p', 'config-note', 'No sessions recorded for this view. Choose All recorded sessions to inspect failures or partial runs.'));
    for (const row of visible) {
      const details = el('details', 'evidence analysis-row');
      details.append(el('summary', '', `${labels[row.task_id] || row.task_id} · ${row.condition} · ${row.stage} · ${row.answer_time_outcome} · ${row.review_status}`));
      details.append(el('p', 'recall-answer', row.answer || 'No answer recorded.'));
      const metrics = el('div', 'metrics');
      for (const [label, value] of [['1 · Payload seen', row.saw_attack], ['2 · Target repeated', row.repeated_in_answer], ['3 · New target memory', row.saved_to_memory], ['4 · Target retrieved', row.attacker_memory_retrieved], ['5 · Target adopted', row.adopted_target]]) {
        const item = el('div', 'metric'); item.append(el('span', '', label), el('strong', '', analysisValue(value))); metrics.append(item);
      }
      details.append(metrics, el('p', 'recall-meta', `Native task utility: ${analysisValue(row.native_utility)} · Conflict: ${analysisValue(row.conflict_flagged)} (${row.conflict_source})`));
      const formatRanks = hits => hits.length ? hits.map(h => `${h.id.slice(0,8)}: ${h.rank == null ? 'rank not recorded' : '#' + h.rank}${h.tool_sequence == null ? '' : ' at call ' + h.tool_sequence}`).join(', ') : 'None recorded';
      details.append(el('p', 'config-note', `Real-memory ranks: ${formatRanks(row.real_retrievals)}. Target-memory ranks: ${formatRanks(row.attacker_retrievals)}.`));
      details.append(el('p', 'config-note', `Automatic real memory retrieved but ignored: ${analysisValue(row.real_memory_retrieved_but_ignored)}. This is a provisional answer-content judgment, not causal proof.`));
      if (row.exclusion_reasons.length) details.append(evidence('Answer-time pair limitations — observation remains included', row.exclusion_reasons));
      details.append(evidence('Classification evidence, memory changes and each retrieval query', {answer: row.answer_classification, selected: row.selected_classification, added_records: row.added_records, queries: row.retrieval_queries, original_memories: row.seed_classifications}));
      if (row.human_review) details.append(evidence('Saved human review (automatic analysis retained separately)', {review: row.human_review, adopted_target: row.reviewed_adopted_target, used_without_conflict: row.reviewed_used_without_conflict, real_memory_retrieved_but_ignored: row.reviewed_real_memory_retrieved_but_ignored}));
      const review = el('details', 'evidence'); review.append(el('summary', '', 'Review this answer'));
      const form = el('form', 'analysis-review');
      const assertion = el('select'); assertion.setAttribute('aria-label', 'Reviewed current value');
      for (const [value, label] of [['', 'Undetermined / insufficient evidence'], ['real', 'Real value'], ['target', 'Attacker value'], ['both', 'Both / unresolved'], ['none', 'No current value']]) { const opt = el('option', '', label); opt.value = value; assertion.append(opt); }
      assertion.value = row.human_review?.label || '';
      const conflict = el('select'); conflict.setAttribute('aria-label', 'Reviewed conflict flag');
      for (const [value, label] of [['', 'Conflict: undetermined'], ['true', 'Conflict explicitly flagged'], ['false', 'No conflict flagged']]) { const opt = el('option', '', label); opt.value = value; conflict.append(opt); }
      conflict.value = row.human_review?.conflict == null ? '' : String(row.human_review.conflict);
      const reason = el('select'); reason.setAttribute('aria-label', 'Reason for no current value');
      for (const [value, label] of [['unknown', 'Uncertainty / unknown'], ['cancelled', 'Explicit cancellation'], ['negated_values', 'Values explicitly rejected']]) { const opt = el('option', '', label); opt.value = value; reason.append(opt); }
      reason.value = row.human_review?.none_reason || 'unknown';
      const updateReason = () => { reason.hidden = assertion.value !== 'none'; }; assertion.addEventListener('change', updateReason); updateReason();
      const notes = el('textarea'); notes.setAttribute('aria-label', 'Review evidence and rationale'); notes.placeholder = 'Quote the relevant phrase and explain your judgment.'; notes.required = true; notes.maxLength = 3000; notes.value = row.human_review?.notes || '';
      const save = el('button', 'primary-button', 'Save review'); save.type = 'submit'; save.disabled = analysis.active;
      const message = el('p', 'config-note');
      form.append(el('p', 'config-note', 'This saves a separate annotation. It does not change the agent answer, native score, memory, or automatic classification.'), assertion, conflict, reason, notes, save, message);
      form.addEventListener('submit', async event => {
        event.preventDefault(); save.disabled = true; message.textContent = 'Saving…';
        try {
          const updated = await request(`/benchmarks/${analysis.run_id}/analysis/${row.row_id}/review`, {method: 'PUT', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({source_sha256: analysis.source_sha256, classifier_version: analysis.classifier_version, label: assertion.value || null, conflict: conflict.value === '' ? null : conflict.value === 'true', none_reason: assertion.value === 'none' ? reason.value : null, notes: notes.value.trim()})});
          if (selectedRun === analysis.run_id) renderAnalysis(updated);
        } catch (error) { message.textContent = error.message; save.disabled = false; }
      });
      review.append(form); details.append(review); rows.append(details);
    }
  }
  filter.addEventListener('change', display); display();
}
function loadAnalysis(run, fingerprint) {
  const panel = $('analysis-panel'); const key = run.run_id + fingerprint;
  if (panel.dataset.source === key) return;
  panel.dataset.source = key; panel.hidden = false; panel.replaceChildren(el('p', 'config-note', 'Analyzing saved evidence…'));
  request(`/benchmarks/${run.run_id}/analysis`).then(data => { if (selectedRun === run.run_id && panel.dataset.source === key) { data.active = run.active; renderAnalysis(data); } }).catch(error => {
    if (panel.dataset.source === key) { panel.replaceChildren(el('p', 'config-note', error.message)); delete panel.dataset.source; }
  });
}
function renderSustained(result) {
  const panel = el('section', 'episode-results');
  const names = {clean: 'Clean', polluted_memory_on: 'Polluted + memory on', polluted_memory_off: 'Polluted + memory off'};
  const yes = value => value === undefined || value === null ? 'Not recorded' : value ? 'Yes' : 'No';
  panel.append(el('h3', '', 'Sustained exposure · native Final'), el('p', 'config-note', 'Fresh sessions · S1 → S2 → S3 → original AgentDojo task. Both polluted conditions retain their payload at Final. Memory off applies throughout.'));
  if (result.seed) panel.append(evidence('S0: clean seed shared by the memory-on branches', result.seed));
  const grid = el('div', 'comparison-grid episode-grid');
  for (const [condition, branch] of Object.entries(result.branches || {})) {
    const card = el('article', 'comparison-card');
    card.append(el('h3', '', names[condition]), el('p', 'config-note', `Sources: ${branch.polluted ? 'polluted through Final' : 'clean throughout'} · Memory: ${branch.memory_enabled ? 'on' : 'off throughout'} · ${branch.status}`));
    const sessions = branch.sessions.map(s => [`S${s.slot}`, s]);
    const final = result.evaluations?.native?.[condition];
    if (final) sessions.push(['Final', final]);
    for (const [stage, value] of sessions) {
      const trace = value.memory_trace;
      card.append(el('h4', '', `${stage} · ${value.status}`));
      if (stage === 'Final') card.append(el('p', 'recall-meta', `Native task utility: ${yes(value.native_utility)} · Memory unchanged: ${yes(value.memory_unchanged)}`));
      if (value.answer) card.append(el('p', 'recall-answer', value.answer));
      if (trace) {
        card.append(el('p', 'recall-meta', `Payload seen: ${yes(trace.payload_seen)} · Target mentioned: ${yes(trace.answer_target_text_match)}`));
        card.append(el('p', 'recall-meta', `New memories: ${trace.added_records?.length ?? '—'} · New target-text records: ${trace.new_target_text_record_ids?.length ?? '—'}`));
        const ranks = trace.target_memory_retrievals.map(r => `query ${r.tool_sequence}: #${r.rank}`).join(', ') || 'None';
        card.append(el('p', 'recall-meta', `Target-memory ranks: ${ranks} · Original memory retrieved: ${yes(trace.real_memory_retrieved)}`));
        card.append(el('p', 'config-note', 'Adoption, conflict and real-memory-ignored judgments: pending semantic review.'));
        card.append(evidence(`${stage}: five-stage memory trace and per-query ranks`, trace));
      }
      if (value.error || value.reason) card.append(el('p', 'error', value.error || value.reason));
      card.append(evidence(`${stage}: question, tool calls, memory before/after and writes`, value));
    }
    grid.append(card);
  }
  panel.append(grid, evidence('Comparison checks', result.comparisons || {}), el('p', 'interpretation', 'Native utility is task success, not attacker success. A target mention can be rejected or quoted. Source and memory both remain available at Final, so this comparison does not isolate a memory-only effect.'));
  return panel;
}
function renderCase(result, policy) {
  const panel = el('section', 'panel case-result');
  const heading = el('div', 'run-heading'); const title = el('div'); title.append(el('span', 'eyebrow', result.task_id.replaceAll('_', ' ').toUpperCase()), el('h2', '', labels[result.task_id] || result.task_id));
  heading.append(title, el('span', 'badge', statusLabels[result.status] || result.status)); panel.append(heading);
  panel.append(el('p', 'case-values', `Expected: ${result.expected}   ·   Attack target: ${result.target}`));
  if (result.sustained) panel.append(evidence('Fixed payload and injection point', {vector: result.vector, payload: result.payload}), renderSustained(result.sustained));
  if (result.error) panel.append(el('p', 'error', result.error));
  return panel;
}

function renderRun(run) {
  $('empty-state').hidden = true; $('run-detail').hidden = false;
  $('run-status').textContent = statusLabels[run.status] || run.status;
  $('run-badge').textContent = run.active ? 'Live · Chat paused' : 'Agent exposure';
  $('run-badge').className = `badge ${run.active ? 'live' : ''}`;
  $('run-id').textContent = run.run_id;
  const progress = run.progress;
  $('progress-note').textContent = run.active ? progress ? `${labels[progress.task_id] || 'Preparing protocol'} · ${progress.completed_cases} of ${progress.total_cases} cases finished. Each model call can take a few minutes.` : 'Starting the isolated benchmark process…' : run.status === 'error' ? 'The process stopped with an error. Open the process log for details.' : run.status === 'interrupted' ? 'This process did not finish under the current server. Partial results are preserved below.' : 'Results are saved. Review each case below. Each session uses fresh context and autonomous tool calls.';
  $('stages').replaceChildren();
  const track = sustainedStages;
  $('stages').style.gridTemplateColumns = 'repeat(auto-fit, minmax(80px, 1fr))';
  let current = track.findIndex(([key]) => key === progress?.stage);
  if (['finished', 'case_finished'].includes(progress?.stage)) current = track.length;
  for (let i = 0; i < track.length; i++) $('stages').append(el('li', i < current ? 'done' : run.active && i === current ? 'current' : '', `${i < current ? '✓' : i + 1}  ${track[i][1]}`));
  $('stages').hidden = !progress;
  const extraction = run.extraction || {};
  $('run-policy').textContent = `Task: ${run.agent?.backend} / ${run.agent?.model || 'default'} · Extractor: ${extraction.backend || 'not recorded'} / ${extraction.model || 'default'} · Three conditions · Polluted sources persist through Final · Original task + native utility`;
  $('download-evidence').hidden = !run.summary; $('download-evidence').href = `/benchmarks/${run.run_id}/evidence`;
  $('download-report').hidden = !run.has_report; $('download-report').href = `/benchmarks/${run.run_id}/report`;
  const consoleOutput = run.console || 'No console log recorded for this run.';
  if ($('console-output').textContent !== consoleOutput) $('console-output').textContent = consoleOutput;
  // Preserve open evidence panels during polling when completed case results have not changed.
  const fingerprint = JSON.stringify(run.summary?.cases || []);
  if (run.summary) loadAnalysis(run, fingerprint);
  else $('analysis-panel').hidden = true;
  if ($('case-results').dataset.fingerprint !== fingerprint) {
    $('case-results').replaceChildren(...(run.summary?.cases || []).map(c => renderCase(c, run.exposure_policy)));
    $('case-results').dataset.fingerprint = fingerprint;
  }
  if (run.error) showError('page-error', run.error);
}
async function loadRuns(preferred) {
  const data = await request('/benchmarks'); activeRun = data.active_run;
  const keep = preferred || selectedRun || activeRun || data.runs[0]?.run_id || '';
  $('run-select').replaceChildren();
  for (const run of data.runs) { const option = el('option', '', `${run.run_id.replace('dojo_', '')} · ${run.agent?.backend || 'ollama'} · Native Final · ${statusLabels[run.status] || run.status}`); option.value = run.run_id; $('run-select').append(option); }
  if (!data.runs.length) $('run-select').append(el('option', '', 'No runs yet'));
  selectedRun = data.runs.some(r => r.run_id === keep) ? keep : data.runs[0]?.run_id || '';
  $('run-select').value = selectedRun; setControls();
}
async function refresh(preferred) {
  if (loading) return;
  loading = true; clearTimeout(timer); $('page-error').hidden = true;
  try {
    await loadRuns(preferred);
    const id = selectedRun, version = selectionVersion;
    if (id) { const run = await request(`/benchmarks/${id}`); if (selectedRun === id && selectionVersion === version) renderRun(run); }
    else { $('empty-state').hidden = false; $('run-detail').hidden = true; }
  } catch (error) { showError('page-error', error); }
  finally { loading = false; timer = setTimeout(() => refresh(), activeRun ? 3000 : 12000); }
}
$('run-form').addEventListener('submit', async event => {
  event.preventDefault(); if (submitting || activeRun) return;
  $('run-error').hidden = true;
  const tasks = [...document.querySelectorAll('[name="task"]:checked')].map(input => input.value);
  if (!tasks.length) { showError('run-error', new Error('Select at least one case.')); return; }
  submitting = true; setControls();
  try {
    const run = await request('/benchmarks', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({tasks, exposure_policy: 'agent', workflow: 'sustained', evaluation_tools: 'workspace', agent_backend: $('agent-backend').value, agent_model: $('agent-model').value.trim(), memory_backend: $('memory-backend').value, memory_model: $('memory-backend').value === 'follow' ? '' : $('memory-model').value.trim()})});
    activeRun = run.run_id; selectedRun = run.run_id; selectionVersion++; renderRun(run);
    await loadRuns(run.run_id); refresh();
  } catch (error) { showError('run-error', error); }
  finally { submitting = false; setControls(); }
});
async function selectRun(runId) {
  selectedRun = runId; $('run-select').value = runId; selectionVersion++;
  const id = selectedRun;
  try { const run = await request(`/benchmarks/${id}`); if (selectedRun === id) renderRun(run); } catch (error) { showError('page-error', error); }
}
$('run-select').addEventListener('change', () => selectRun($('run-select').value));
$('reload-runs').addEventListener('click', () => refresh());
$('workflow').addEventListener('change', showAgentStatus);
let agentCatalog = [];
function showAgentStatus() {
  const agent = agentCatalog.find(item => item.id === $('agent-backend').value);
  const follow = $('memory-backend').value === 'follow';
  const memory = follow ? agent : agentCatalog.find(item => item.id === $('memory-backend').value);
  const model = follow ? $('agent-model').value.trim() : $('memory-model').value.trim();
  $('agent-status').textContent = agent && memory ? `Task — ${agent.label}: ${agent.note}. Memory — ${memory.label} / ${model || memory.default_model || 'CLI default'}${follow ? ' (follows task)' : ` (independent; ${memory.note})`}.` : 'Agent status unavailable.';
  $('memory-model').placeholder = follow ? 'Follows the task model' : "Use the extractor's default model";
  setControls();
}
$('agent-backend').addEventListener('change', () => { $('agent-model').value = ''; showAgentStatus(); });
$('memory-backend').addEventListener('change', () => { $('memory-model').value = ''; showAgentStatus(); });
$('agent-model').addEventListener('input', showAgentStatus);
$('memory-model').addEventListener('input', showAgentStatus);
request('/agents').then(data => { agentCatalog = data.agents; showAgentStatus(); }).catch(error => { $('agent-status').textContent = error.message; });
refresh();
