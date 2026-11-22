const $ = id => document.getElementById(id);
const labels = { user_task_14: 'Family reunion', user_task_30: 'Hawaii itinerary' };
const stages = [['baseline', 'Baseline'], ['snapshot', 'Snapshot'], ['clean', 'Clean read'], ['poison', 'Poisoned read'], ['followup', 'Fresh session']];
const episodeStages = [...stages, ['intermediate', 'Intermediate tasks'], ['episode_probes', 'Transfer tasks']];
const autonomousStages = [['baseline', 'Clean seed'], ['session_1', 'S1'], ['session_2', 'S2'], ['session_3', 'S3'], ['autonomous_probes', 'Final tasks']];
const sustainedStages = [...autonomousStages.slice(0, 4), ['native_final', 'Original task']];
const directStages = [['reminder_polluted', 'Polluted reminder'], ['plan_polluted', 'Polluted plan']];
const statusLabels = { starting: 'Starting', running: 'Running', completed: 'Completed', completed_with_limitations: 'Completed with limitations', completed_controlled_only: 'Controlled result only', needs_review: 'Needs review', error: 'Process error', interrupted: 'Interrupted', incomplete: 'Incomplete', baseline_failed: 'Autonomous baseline failed', reference_clean_failed: 'Reference control failed', clean_memory_failed: 'Clean memory control failed' };
let selectedRun = '', activeRun = null, loading = false, submitting = false, timer, selectionVersion = 0;
statusLabels.episode_needs_review = 'Episode needs review';
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
  $('delay-tasks').disabled = submitting || Boolean(activeRun) || $('workflow').value !== 'episode';
  $('episode-options').hidden = $('workflow').value !== 'episode';
  const autonomous = $('workflow').value === 'autonomous';
  const sustained = $('workflow').value === 'sustained';
  const direct = $('workflow').value === 'direct';
  $('direct-options').hidden = !direct;
  $('source-run').disabled = submitting || Boolean(activeRun) || !direct;
  $('memory-backend').disabled = submitting || Boolean(activeRun) || direct;
  $('memory-model').disabled ||= direct;
  $('memory-policy-help').textContent = direct ? 'Memory reads and writes are disabled in this supplement. No extraction calls are made. The source run supplies the existing clean-file reference.' : 'By default, the selected agent also extracts memories in a separate session. Independent extractors are optional controls. CLI providers receive their task or extraction inputs; embeddings and storage stay local.';
  $('autonomous-options').hidden = !autonomous;
  $('evaluation-tools').disabled = submitting || Boolean(activeRun) || !autonomous;
  $('policy').disabled = submitting || Boolean(activeRun) || autonomous || direct || sustained;
  if (sustained) {
    $('policy').value = 'agent';
    $('evaluation-tools').value = 'workspace';
    $('policy-help').textContent = 'Agent-selected tools in every session. Two polluted conditions keep the same payload through Final; the clean control stays clean. Memory off applies to all sessions. Each run records exposure, answers, memory changes and retrieval ranks.';
  } else if (direct) {
    $('policy').value = 'agent';
    $('policy-help').textContent = 'Only the polluted-source reminder and plan are new. Agent-selected tools; the payload may not be encountered. Clean controls are reused from the source run.';
  } else if (autonomous) {
    $('policy').value = 'agent';
    $('policy-help').textContent = 'All sessions choose their own tools. No reference reads, memory prefetch, or forced exposure. The four fixed schedules are compared separately.';
  } else {
    $('policy-help').textContent = $('policy').value === 'reference' ? 'Replays official reference tool calls in both branches. The selected agent generates each answer without seeing the ground truth.' : 'The selected agent chooses tools in both branches. CLI agents call native MCP tools. A failed autonomous baseline stops that case; the attack source may not be encountered.';
  }
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
  for (const [value, text] of [['final', 'Final / recall sessions'], ['exposure', 'S0–S3 / exposure sessions'], ['all', 'All recorded sessions']]) { const option = el('option', '', text); option.value = value; filter.append(option); }
  filter.value = priorFilter; panel.append(filter);
  const rows = el('div', 'analysis-rows'); panel.append(rows);
  function display() {
    rows.replaceChildren();
    const visible = analysis.rows.filter(r => filter.value === 'all' || (filter.value === 'final') === (r.stage.startsWith('Final') || r.stage === 'Recall'));
    if (!visible.length) rows.append(el('p', 'config-note', 'No sessions recorded for this view. Choose All recorded sessions to inspect failures or partial runs.'));
    for (const row of visible) {
      const details = el('details', 'evidence analysis-row');
      details.append(el('summary', '', `${labels[row.task_id] || row.task_id} · ${row.condition} · ${row.stage} · ${row.answer_time_outcome} · ${row.review_status}`));
      if (row.data_origin === 'reused_source_run') details.append(el('p', 'case-warning', 'Reused historical observation — not an additional trial.'));
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
function renderEpisode(episode) {
  const block = el('section', 'episode-results');
  block.append(el('h3', '', 'Cross-session transfer'), el('p', 'config-note', `${episode.delay_tasks} intermediate task(s) per branch · Fresh session and independent snapshot for each probe · Memory-only evidence · No probe writes or executed actions.`));
  block.append(el('p', 'config-note', 'Restored: full pre-exposure memory and extraction history, followed by the same intermediate tasks. Memory off: poisoned state with retrieval disabled.'));
  const armNames = {clean: 'Clean memory', poisoned: 'Poisoned memory', memory_off: 'Memory off', restored: 'Restored memory'};
  for (const [kind, group] of Object.entries(episode.probes)) {
    block.append(el('h3', '', kind === 'reminder' ? 'Reminder draft' : 'Structured plan'));
    const comparison = episode.comparisons[kind] || {clean_control_valid: false};
    if (!comparison.clean_control_valid) block.append(el('p', 'case-warning', 'This comparison needs review: an arm failed or the clean draft/plan did not pass its content check.'));
    const grid = el('div', 'comparison-grid episode-grid');
    for (const [armName, data] of Object.entries(group)) {
      const card = el('article', 'comparison-card'); card.append(el('h3', '', armNames[armName]));
      if (data.artifact) {
        const artifact = data.artifact;
        card.append(el('p', 'recall-answer', kind === 'reminder' ? artifact.body : `${artifact.title}\nDate: ${artifact.date}\nTime: ${artifact.time}\nLocation: ${artifact.location}\n${artifact.notes}`));
        card.append(el('p', 'recall-meta', `Expected content: ${data.expected_content_present ? 'Yes' : 'No'} · Target content: ${data.target_content_present ? 'Yes' : 'No'} · Conflict: ${artifact.conflict ? 'Yes' : 'No'}`));
        const memories = el('details', 'evidence'); memories.append(el('summary', '', `Retrieved memories (${data.retrieved.length})`), memoryList(data.retrieved, new Set(), artifact.memory_ids_used)); card.append(memories);
      }
      if (data.error) card.append(el('p', 'error', data.error));
      card.append(evidence('Session evidence and snapshot checks', data)); grid.append(card);
    }
    block.append(grid);
  }
  block.append(el('p', 'interpretation', 'Reminder checks detect literal target text, including possible negations. Plans use exact field checks. Inspect the artifact before interpreting adoption; this is not an executed-action success rate.'));
  block.append(evidence('Intermediate sessions and restoration snapshots', episode.branches));
  return block;
}
function renderRepeated(result) {
  const panel = el('section', 'episode-results');
  panel.append(el('h3', '', 'Autonomous repeated exposure'), el('p', 'config-note', `S0 → S1 → S2 → S3 → Final tasks · Final evidence: ${result.evaluation_tools === 'workspace' ? 'Memory + clean workspace' : 'Memory only'} · Fixed payload · Fresh sessions`));
  if (result.seed) panel.append(evidence('S0: clean seed task, tools and memory writes', result.seed));
  const timelines = el('div', 'comparison-grid episode-grid');
  const names = {clean: 'Clean', single_early: 'Single early', single_late: 'Single late', repeated: 'Repeated', repeated_memory_off: 'Repeated + memory off', repeated_restored: 'Repeated + restored'};
  for (const [arm, branch] of Object.entries(result.branches || {})) {
    const card = el('article', 'comparison-card');
    card.append(el('h3', '', `${names[arm]} · ${branch.schedule.join('')}`), el('p', 'config-note', `Status: ${branch.status} · Scheduled: ${branch.schedule.reduce((a,b)=>a+b,0)} · Sessions exposed: ${branch.observed_exposure_sessions ?? branch.sessions.filter(s=>s.attack_source_seen).length} · Payload reads: ${branch.attack_tool_reads ?? branch.sessions.reduce((a,s)=>a+s.attack_tool_reads,0)}`));
    for (const session of branch.sessions) {
      card.append(el('p', 'recall-meta', `S${session.slot}: ${session.status} · ${session.exposure_observation} · Memory calls ${session.memory_calls} · Workspace calls ${session.workspace_calls}`));
      card.append(evidence(`S${session.slot}: tools → answer → memory`, session));
    }
    if (branch.error) card.append(el('p', 'error', branch.error));
    timelines.append(card);
  }
  panel.append(timelines, el('p', 'interpretation', 'An attack opportunity is not a confirmed exposure. Unencountered payloads stay in the scheduled-group results. Final sources contain no attack. Restored uses the complete clean S3 memory state, including extraction history.'));
  for (const [kind, group] of Object.entries(result.evaluations || {})) {
    panel.append(el('h3', '', kind === 'reminder' ? 'Reminder draft — six conditions' : 'Structured plan — six conditions'));
    const grid = el('div', 'comparison-grid episode-grid');
    for (const [condition, value] of Object.entries(group)) {
      const card = el('article', 'comparison-card'); card.append(el('h3', '', names[condition]));
      card.append(el('p', 'recall-meta', `Status: ${value.status} · Memory calls: ${value.memory_calls ?? '—'} · Workspace calls: ${value.workspace_calls ?? '—'}`));
      if (value.artifact) {
        const a = value.artifact;
        card.append(el('p', 'recall-answer', kind === 'reminder' ? a.body : `${a.title}\nDate: ${a.date}\nTime: ${a.time}\nLocation: ${a.location}\n${a.notes}`));
        card.append(el('p', 'recall-meta', `Expected content: ${value.expected_content_present ? 'Yes' : 'No'} · Target content: ${value.target_content_present ? 'Yes' : 'No'} · Conflict: ${a.conflict ? 'Yes' : 'No'}`));
      }
      if (value.error || value.reason) card.append(el('p', 'case-warning', value.error || value.reason));
      card.append(evidence('Tool choices, retrieved evidence and snapshot checks', value)); grid.append(card);
    }
    panel.append(grid);
    if (result.comparisons?.[kind]) panel.append(evidence('Comparison validity and diagnostic indicators', result.comparisons[kind]));
  }
  panel.append(el('p', 'interpretation', 'Plans are draft artifacts, not executed actions. Target-text matches in memory can include rejected claims or a location on another date. Reminder mentions also require review. No aggregate attack success rate is inferred from this single run.'));
  return panel;
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
  if (result.sustained) {
    panel.append(evidence('Fixed payload and injection point', {vector: result.vector, payload: result.payload}), renderSustained(result.sustained));
    if (result.error) panel.append(el('p', 'error', result.error));
    return panel;
  }
  if (result.direct) {
    const d = result.direct;
    panel.append(el('h3', '', 'Memory off: clean vs polluted source'), el('p', 'config-note', 'Clean source = prior Repeated + memory off, reused without rerunning. Polluted source = new session. Both have memory reads and writes disabled. Only current source content differs; the observations come from different runs.'));
    const source = el('button', 'primary-button', 'View source run'); source.type = 'button';
    source.addEventListener('click', () => selectRun(d.source.run_id));
    panel.append(el('p', 'run-id', `Source: ${d.source.run_id}`), source, evidence('Fixed inherited payload', result.payload));
    for (const [kind, group] of Object.entries(d.evaluations || {})) {
      panel.append(el('h3', '', kind === 'reminder' ? 'Reminder draft' : 'Structured plan'));
      const grid = el('div', 'comparison-grid episode-grid');
      for (const [condition, value] of Object.entries(group)) {
        const card = el('article', 'comparison-card');
        card.append(el('h3', '', `Memory off + ${condition} source`), el('span', 'badge', value.data_origin === 'reused_source_run' ? 'Reused · previous run' : 'New · this run'));
        card.append(el('p', 'recall-meta', `Status: ${value.status} · Payload encountered: ${value.attack_source_seen ? 'Yes' : 'No'} · Payload reads: ${value.attack_tool_reads ?? 0} · Memory calls: ${value.memory_calls ?? 0} (empty results)`));
        if (value.artifact) {
          const a = value.artifact;
          card.append(el('p', 'recall-answer', kind === 'reminder' ? a.body : `${a.title}\nDate: ${a.date}\nTime: ${a.time}\nLocation: ${a.location}\n${a.notes}`));
          card.append(el('p', 'recall-meta', `Expected content: ${value.expected_content_present ? 'Yes' : 'No'} · Target content: ${value.target_content_present ? 'Yes' : 'No'} · Conflict: ${a.conflict ? 'Yes' : 'No'}`));
        }
        if (value.error) card.append(el('p', 'error', value.error));
        card.append(evidence('Provenance, tool calls and snapshot checks', value)); grid.append(card);
      }
      panel.append(grid);
    }
    if (result.error || d.error) panel.append(el('p', 'error', result.error || d.error));
    panel.append(evidence('Comparison checks', d.comparisons), el('p', 'interpretation', 'A target mention may express doubt or rejection. Read the artifact before interpreting adoption. Historical-reference comparison: provider defaults and execution time may differ; this is not aggregate ASR.'));
    return panel;
  }
  if (result.repeated) {
    panel.append(evidence('Fixed external payload and injection entry point', {vector: result.vector, payload: result.payload}));
    if (result.error) panel.append(el('p', 'error', result.error));
    panel.append(renderRepeated(result.repeated));
    return panel;
  }
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
  panel.append(path);
  if (result.episode) panel.append(renderEpisode(result.episode));
  return panel;
}
function renderRun(run) {
  $('empty-state').hidden = true; $('run-detail').hidden = false;
  $('run-status').textContent = statusLabels[run.status] || run.status;
  $('run-badge').textContent = run.active ? 'Live · Chat paused' : run.exposure_policy === 'reference' ? 'Controlled exposure' : 'Agent exposure';
  $('run-badge').className = `badge ${run.active ? 'live' : ''}`;
  $('run-id').textContent = run.run_id;
  const progress = run.progress;
  $('progress-note').textContent = run.active ? progress ? `${labels[progress.task_id] || 'Preparing protocol'} · ${progress.completed_cases} of ${progress.total_cases} cases finished. Each model call can take a few minutes.` : 'Starting the isolated benchmark process…' : run.status === 'error' ? 'The process stopped with an error. Open the process log for details.' : run.status === 'interrupted' ? 'This process did not finish under the current server. Partial results are preserved below.' : 'Results are saved. Review each case below. Follow-ups use fresh sessions and the recorded evidence policy.';
  $('stages').replaceChildren();
  const track = run.workflow === 'sustained' ? sustainedStages : run.workflow === 'direct' ? directStages : run.workflow === 'autonomous' ? autonomousStages : run.workflow === 'episode' ? episodeStages : stages;
  $('stages').style.gridTemplateColumns = 'repeat(auto-fit, minmax(80px, 1fr))';
  let current = track.findIndex(([key]) => key === progress?.stage);
  if (['finished', 'case_finished'].includes(progress?.stage)) current = track.length;
  for (let i = 0; i < track.length; i++) $('stages').append(el('li', i < current ? 'done' : run.active && i === current ? 'current' : '', `${i < current ? '✓' : i + 1}  ${track[i][1]}`));
  $('stages').hidden = !progress;
  const extraction = run.extraction || {backend: 'ollama', model: run.memory_model || 'qwen2.5:7b', mode: 'legacy'};
  $('run-policy').textContent = `Task: ${run.agent?.backend || 'ollama'} / ${run.agent?.model || 'default'} · Memory: ${extraction.backend} / ${extraction.model || 'CLI default'} (${extraction.mode === 'follow' ? 'follows task' : extraction.mode === 'legacy' ? 'legacy fixed extractor' : 'independent'}) · ${run.exposure_policy === 'reference' ? 'Controlled reference reads' : 'Agent-selected tool calls'}`;
  $('run-policy').textContent += run.workflow === 'autonomous' ? ` · Autonomous repeated exposure · Final tools: ${run.evaluation_tools}` : run.workflow === 'episode' ? ` · Cross-session episode · ${run.delay_tasks} intermediate task(s)` : ' · Original recall pilot';
  if (run.workflow === 'direct') $('run-policy').textContent = `Task: ${run.agent?.backend} / ${run.agent?.model || 'default'} · Memory reads/writes off · No extraction · New polluted-source probes; prior clean probes reused · Source: ${run.source_run_id}`;
  if (run.workflow === 'sustained') $('run-policy').textContent = `Task: ${run.agent?.backend} / ${run.agent?.model || 'default'} · Extractor: ${extraction.backend} / ${extraction.model || 'default'} · Three conditions · Polluted sources persist through Final · Original task + native utility`;
  else $('run-policy').textContent = 'Historical protocol — not the current three-condition design. ' + $('run-policy').textContent;
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
  const sourceKeep = $('source-run').value;
  const sources = data.runs.filter(r => r.workflow === 'autonomous' && r.status === 'completed');
  $('source-run').replaceChildren(...sources.map(r => { const option = el('option', '', `${r.run_id} · ${r.agent?.backend}`); option.value = r.run_id; return option; }));
  if (sources.some(r => r.run_id === sourceKeep)) $('source-run').value = sourceKeep;
  if (!sources.length) { const option = el('option', '', 'No completed autonomous runs'); option.value = ''; $('source-run').append(option); }
  $('run-select').replaceChildren();
  for (const run of data.runs) { const option = el('option', '', `${run.run_id.replace('dojo_', '')} · ${run.agent?.backend || 'ollama'} · ${run.workflow === 'sustained' ? 'Native Final' : 'Historical protocol'} · ${statusLabels[run.status] || run.status}`); option.value = run.run_id; $('run-select').append(option); }
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
    const direct = $('workflow').value === 'direct';
    if (direct && !$('source-run').value) throw new Error('Choose a completed autonomous source run first.');
    const run = await request('/benchmarks', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ tasks, exposure_policy: $('policy').value, agent_backend: $('agent-backend').value, agent_model: $('agent-model').value.trim(), memory_backend: direct ? 'follow' : $('memory-backend').value, memory_model: direct || $('memory-backend').value === 'follow' ? '' : $('memory-model').value.trim(), workflow: $('workflow').value, delay_tasks: $('workflow').value === 'episode' ? Number($('delay-tasks').value) : 0, evaluation_tools: direct ? 'workspace' : $('evaluation-tools').value, source_run_id: direct ? $('source-run').value : '' }) });
    activeRun = run.run_id; selectedRun = run.run_id; selectionVersion++; renderRun(run);
    await loadRuns(run.run_id); refresh();
  } catch (error) { showError('run-error', error); }
  finally { submitting = false; setControls(); }
});
$('policy').addEventListener('change', () => { $('policy-help').textContent = $('policy').value === 'reference' ? 'Replays official reference tool calls in both branches. The selected agent generates each answer without seeing the ground truth.' : 'The selected agent chooses tools in both branches. CLI agents call native MCP tools. A failed autonomous baseline stops that case; the attack source may not be encountered.'; });
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
  if ($('workflow').value === 'direct' && agent) $('agent-status').textContent = `Task — ${agent.label}: ${agent.note}. Memory reads/writes off; no extraction calls.`;
  $('memory-model').placeholder = follow ? 'Follows the task model' : "Use the extractor's default model";
  setControls();
}
$('agent-backend').addEventListener('change', () => { $('agent-model').value = ''; showAgentStatus(); });
$('memory-backend').addEventListener('change', () => { $('memory-model').value = ''; showAgentStatus(); });
$('agent-model').addEventListener('input', showAgentStatus);
$('memory-model').addEventListener('input', showAgentStatus);
request('/agents').then(data => { agentCatalog = data.agents; showAgentStatus(); }).catch(error => { $('agent-status').textContent = error.message; });
refresh();
