const $ = id => document.getElementById(id);
const labels = { user_task_14: 'Family reunion', user_task_30: 'Hawaii itinerary' };
const stages = [['baseline', 'Baseline'], ['snapshot', 'Snapshot'], ['clean', 'Clean read'], ['poison', 'Poisoned read'], ['followup', 'Fresh session']];
const statusLabels = { starting: 'Starting', running: 'Running', completed: 'Completed', completed_with_limitations: 'Completed with limitations', completed_controlled_only: 'Controlled result only', needs_review: 'Needs review', error: 'Process error', interrupted: 'Interrupted', incomplete: 'Incomplete', baseline_failed: 'Autonomous baseline failed', reference_clean_failed: 'Reference control failed', clean_memory_failed: 'Clean memory control failed' };
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
}
function evidence(title, text) { const details = el('details', 'evidence'); details.append(el('summary', '', title), el('pre', '', typeof text === 'string' ? text : JSON.stringify(text, null, 2))); return details; }
function memoryList(records, initialIds = new Set(), citedIds = []) {
  const list = el('div', 'evidence-memories');
  if (!records?.length) { list.append(el('p', 'config-note', 'No records.')); return list; }
  for (const record of records) {
    const item = el('div', 'evidence-memory');
    const flags = [!initialIds.has(record.id) && initialIds.size ? 'Added after exposure' : '', citedIds.includes(record.id) ? 'Cited in answer' : ''].filter(Boolean);
    if (flags.length) item.append(el('span', 'memory-flag', flags.join(' · ')));
    item.append(el('p', '', record.memory), el('small', '', `ID ${record.id}`)); list.append(item);
  }
  return list;
}
function arm(title, data, initialIds, saved) {
  const card = el('article', 'comparison-card');
  card.append(el('h3', '', title));
  if (!data?.output) { card.append(el('p', 'config-note', 'Not evaluated yet.')); return card; }
  const output = data.output;
  card.append(el('span', 'field-label', 'Selected value'), el('p', 'selected-value', output.selected_value), el('p', 'recall-answer', output.answer));
  card.append(el('p', 'recall-meta', `Conflict reported: ${output.conflict ? 'Yes' : 'No'} · ${output.memory_ids_used.length} memory ID(s) cited`));
  const details = el('details', 'evidence'); details.append(el('summary', '', `Retrieved memories (${data.retrieved.length})`), memoryList(data.retrieved, initialIds, output.memory_ids_used)); card.append(details);
  if (saved) { const storage = el('details', 'evidence'); storage.append(el('summary', '', `Saved memories (${saved.length})`), memoryList(saved, initialIds)); card.append(storage); }
  return card;
}
function metric(label, value) { const item = el('div', 'metric'); item.append(el('span', '', label), el('strong', '', value === undefined ? '—' : value ? 'Yes' : 'No')); return item; }
function renderCase(result, policy) {
  const panel = el('section', 'panel case-result');
  const heading = el('div', 'run-heading'); const title = el('div'); title.append(el('span', 'eyebrow', result.task_id.replaceAll('_', ' ').toUpperCase()), el('h2', '', labels[result.task_id] || result.task_id));
  heading.append(title, el('span', 'badge', statusLabels[result.status] || result.status)); panel.append(heading);
  panel.append(el('p', 'case-values', `Expected: ${result.expected}   ·   Attack target: ${result.target}`));
  if (policy === 'reference') panel.append(el('p', 'interpretation', 'Controlled exposure: the same reference tool calls were used in both branches. The baseline below measures autonomous tool use separately.'));
  if (result.baseline && !result.baseline.native_utility) panel.append(el('p', 'case-warning', 'Autonomous baseline failed. Any completed reference-mode results describe controlled memory behavior only.'));
  if (result.error) panel.append(el('p', 'error', result.error));
  if (result.status === 'clean_memory_failed') panel.append(el('p', 'case-warning', 'The clean memory control failed. This run does not establish a valid paired memory comparison.'));
  const metrics = el('div', 'metrics');
  metrics.append(metric('Autonomous baseline passed', result.baseline?.native_utility), metric('Target text saved', result.memory_poison ? Boolean(result.memory_poison.target_claim_record_ids?.length) : undefined), metric('Target text retrieved', result.followup_poison ? Boolean(result.followup_poison.target_claim_retrieved_ids?.length) : undefined), metric('Poisoned recall chose target', result.followup_poison?.target_value_selected));
  panel.append(metrics);
  const grid = el('div', 'comparison-grid'); const initial = new Set((result.initial_memory?.after || []).map(r => r.id));
  grid.append(arm('Clean memory', result.followup_clean, initial, result.memory_clean?.after), arm('Poisoned memory', result.followup_poison, initial, result.memory_poison?.after), arm('Memory off', result.followup_without_memory, initial)); panel.append(grid);
  const path = el('details', 'evidence source-trail'); path.append(el('summary', '', 'Inspect source → agent answer → memory'));
  path.append(el('p', 'config-note', `Injection entry point: ${result.vector}`), evidence('Fixed external payload', result.payload));
  if (result.baseline) path.append(evidence('Autonomous baseline answer & tool calls', { answer: result.baseline.answer, native_utility: result.baseline.native_utility, tools: result.baseline.tools, tool_errors: result.baseline.tool_errors }));
  if (result.clean_exposure) path.append(evidence('Clean source read & agent answer', result.clean_exposure));
  if (result.poisoning_task) path.append(evidence('Poisoned source read & agent answer', result.poisoning_task));
  if (result.initial_memory) path.append(evidence('Initial memory & matched snapshot hashes', { records: result.initial_memory.after, snapshot_hashes: result.snapshot_hashes, original_record_ids_preserved: result.seed_record_ids_preserved }));
  if (result.memory_poison) path.append(evidence('Mem0 write events (poisoned branch)', result.memory_poison.result));
  panel.append(path); return panel;
}
function renderRun(run) {
  $('empty-state').hidden = true; $('run-detail').hidden = false;
  $('run-status').textContent = statusLabels[run.status] || run.status;
  $('run-badge').textContent = run.active ? 'Live · Chat paused' : run.exposure_policy === 'reference' ? 'Controlled exposure' : 'Agent exposure';
  $('run-badge').className = `badge ${run.active ? 'live' : ''}`;
  $('run-id').textContent = run.run_id;
  const progress = run.progress;
  $('progress-note').textContent = run.active ? progress ? `${labels[progress.task_id] || 'Preparing protocol'} · ${progress.completed_cases} of ${progress.total_cases} cases finished. Each model call can take a few minutes.` : 'Starting the isolated benchmark process…' : run.status === 'error' ? 'The process stopped with an error. Open the process log for details.' : run.status === 'interrupted' ? 'This process did not finish under the current server. Partial results are preserved below.' : 'Results are saved. Review each case below. Completed follow-ups use fresh conversations without the original source.';
  $('stages').replaceChildren();
  let current = stages.findIndex(([key]) => key === progress?.stage);
  if (['finished', 'case_finished'].includes(progress?.stage)) current = stages.length;
  for (let i = 0; i < stages.length; i++) $('stages').append(el('li', i < current ? 'done' : run.active && i === current ? 'current' : '', `${i < current ? '✓' : i + 1}  ${stages[i][1]}`));
  $('stages').hidden = !progress;
  const extraction = run.extraction || {backend: 'ollama', model: run.memory_model || 'qwen2.5:7b', mode: 'legacy'};
  $('run-policy').textContent = `Task: ${run.agent?.backend || 'ollama'} / ${run.agent?.model || 'default'} · Memory: ${extraction.backend} / ${extraction.model || 'CLI default'} (${extraction.mode === 'follow' ? 'follows task' : extraction.mode === 'legacy' ? 'legacy fixed extractor' : 'independent'}) · ${run.exposure_policy === 'reference' ? 'Controlled reference reads' : 'Agent-selected tool calls'}`;
  $('download-evidence').hidden = !run.summary; $('download-evidence').href = `/benchmarks/${run.run_id}/evidence`;
  $('download-report').hidden = !run.has_report; $('download-report').href = `/benchmarks/${run.run_id}/report`;
  const consoleOutput = run.console || 'No console log recorded for this run.';
  if ($('console-output').textContent !== consoleOutput) $('console-output').textContent = consoleOutput;
  // Preserve open evidence panels during polling when completed case results have not changed.
  const fingerprint = JSON.stringify(run.summary?.cases || []);
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
  for (const run of data.runs) { const option = el('option', '', `${run.run_id.replace('dojo_', '')} · ${run.agent?.backend || 'ollama'} · ${statusLabels[run.status] || run.status}`); option.value = run.run_id; $('run-select').append(option); }
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
    const run = await request('/benchmarks', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ tasks, exposure_policy: $('policy').value, agent_backend: $('agent-backend').value, agent_model: $('agent-model').value.trim(), memory_backend: $('memory-backend').value, memory_model: $('memory-backend').value === 'follow' ? '' : $('memory-model').value.trim() }) });
    activeRun = run.run_id; selectedRun = run.run_id; selectionVersion++; renderRun(run);
    await loadRuns(run.run_id); refresh();
  } catch (error) { showError('run-error', error); }
  finally { submitting = false; setControls(); }
});
$('policy').addEventListener('change', () => { $('policy-help').textContent = $('policy').value === 'reference' ? 'Replays official reference tool calls in both branches. The selected agent generates each answer without seeing the ground truth.' : 'The selected agent chooses tools in both branches. CLI agents call native MCP tools. A failed autonomous baseline stops that case; the attack source may not be encountered.'; });
$('run-select').addEventListener('change', async () => {
  selectedRun = $('run-select').value; selectionVersion++;
  const id = selectedRun;
  try { const run = await request(`/benchmarks/${id}`); if (selectedRun === id) renderRun(run); } catch (error) { showError('page-error', error); }
});
$('reload-runs').addEventListener('click', () => refresh());
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
