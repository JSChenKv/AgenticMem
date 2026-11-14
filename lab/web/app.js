const $ = id => document.getElementById(id);
const state = { history: [], busy: false, experiment: 'web', user: 'researcher', memoryRequest: 0 };
const modeNotes = { write: 'Uses existing memories and extracts new ones from your message', read: 'Uses existing memories without saving this message', none: 'Uses this conversation only; long-term memory is off' };
function payload() { return { experiment: state.experiment, user: state.user, agent_backend: $('agent-backend').value, agent_model: $('agent-model').value.trim(), memory_backend: $('memory-backend').value, memory_model: $('memory-backend').value === 'follow' ? '' : $('memory-model').value.trim() }; }
function errorText(error) {
  const text = String(error.message || error);
  if (/already accessed|another instance|locked|另一个进程/i.test(text)) return 'This experiment space is in use. Close the CLI using it, or choose another space in Experiment settings.';
  if (/Failed to fetch|NetworkError/i.test(text)) return 'Cannot reach the local server. Start the web service and refresh.';
  if (/connect to Ollama|Connection refused/i.test(text)) return 'The local model service is unavailable. Start Ollama and try again.';
  return text;
}
async function request(url, options) {
  const response = await fetch(url, options);
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    const detail = Array.isArray(data.detail) ? 'Invalid input. Check your experiment settings or message length.' : data.detail;
    throw new Error(detail || `Request failed (${response.status}). Please try again.`);
  }
  return response.json();
}
function busy(value) {
  state.busy = value;
  for (const id of ['send', 'message', 'new-session', 'mode', 'experiment', 'user', 'refresh-memory', 'load-memory', 'agent-backend', 'agent-model', 'memory-backend', 'memory-model']) { const control = $(id); if (control) control.disabled = value; }
  $('memory-model').disabled = value || $('memory-backend').value === 'follow';
  document.querySelectorAll('[data-example]').forEach(button => button.disabled = value);
  $('activity').hidden = !value;
}
function addMessage(role, text) {
  $('welcome').hidden = true;
  const item = document.createElement('article'); item.className = `message ${role}`;
  const speaker = document.createElement('div'); speaker.className = 'speaker'; speaker.textContent = role === 'user' ? 'You' : $('agent-backend').selectedOptions[0].textContent;
  const content = document.createElement('div'); content.className = 'message-content'; content.textContent = text;
  item.append(speaker, content); $('messages').append(item); scrollBottom(); return item;
}
function scrollBottom() { $('messages').scrollTop = $('messages').scrollHeight; }
function resetSession() {
  state.history = [];
  $('messages').querySelectorAll('.message').forEach(item => item.remove());
  $('welcome').hidden = false; $('error').hidden = true;
  $('session-note').textContent = 'New session started. Conversation context cleared; long-term memories retained.';
  $('message').value = ''; $('message').focus();
}
async function checkHealth() {
  $('health-label').textContent = 'Checking connection';
  try {
    const data = await request('/health');
    $('health').className = 'status online'; $('health-label').textContent = 'Local models connected';
    $('health').title = `Mem0 ${data.mem0ai} · ${data.models.join(' · ')} · Click to check connection`;
  } catch (error) {
    $('health').className = 'status offline'; $('health-label').textContent = 'Service unavailable · Retry'; $('health').title = errorText(error);
  }
}
async function refreshMemories() {
  const ticket = ++state.memoryRequest;
  $('memory-notice').textContent = 'Loading saved memories…';
  try {
    const records = await request(`/memories?${new URLSearchParams(payload())}`);
    if (ticket !== state.memoryRequest) return;
    $('memory-list').replaceChildren(); $('memory-count').textContent = records.length;
    if (!records.length) {
      const empty = document.createElement('div'); empty.className = 'memory-placeholder';
      const text = document.createElement('p'); text.textContent = 'No long-term memories yet. Try sharing a fact about yourself.'; empty.append(text); $('memory-list').append(empty);
    }
    for (const record of records) {
      const card = document.createElement('article'); card.className = 'memory-card';
      const text = document.createElement('p'); text.textContent = record.memory;
      const meta = document.createElement('small');
      const date = record.created_at ? new Date(record.created_at).toLocaleString('en-US') : '';
      meta.textContent = `${date}${date ? ' · ' : ''}ID ${record.id.slice(0, 8)}`;
      card.append(text, meta); $('memory-list').append(card);
    }
    $('memory-notice').textContent = 'These are the actual records saved in the local database.';
  } catch (error) { if (ticket === state.memoryRequest) $('memory-notice').textContent = errorText(error); }
}
$('chat-form').addEventListener('submit', async event => {
  event.preventDefault(); if (state.busy) return;
  const text = $('message').value.trim(); if (!text) return;
  $('error').hidden = true;
  const mode = $('mode').value;
  const userMessage = addMessage('user', text); userMessage.classList.add('pending');
  busy(true); $('activity-label').textContent = mode === 'write' ? 'Thinking and extracting memories. Initial model loading may take a moment…' : 'Thinking. Initial model loading may take a moment…';
  try {
    const result = await request('/chat', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ...payload(), text, mode, history: state.history.slice(-8) }) });
    userMessage.classList.remove('pending');
    const answer = addMessage('assistant', result.answer);
    const records = result.retrieved?.results || [];
    if (records.length) {
      const details = document.createElement('details'); const summary = document.createElement('summary');
      summary.textContent = `Referenced ${records.length} memories`; details.append(summary);
      for (const record of records) { const source = document.createElement('div'); source.className = 'source'; source.textContent = `${record.memory}\nID: ${record.id}`; details.append(source); }
      answer.append(details);
    }
    const note = document.createElement('div'); note.className = 'write-note';
    note.textContent = mode === 'write' ? `Added ${result.memory_write?.results?.length || 0} memories this turn` : mode === 'read' ? 'No long-term memories saved this turn' : 'Long-term memory was off this turn'; answer.append(note);
    if (result.extraction) note.textContent += ` · Extractor: ${result.extraction.backend} / ${result.extraction.model || 'CLI default'}`;
    state.history.push({ role: 'user', content: text }, { role: 'assistant', content: result.answer }); state.history = state.history.slice(-8);
    $('message').value = ''; scrollBottom();
    if (mode !== 'none') await refreshMemories();
  } catch (error) {
    userMessage.remove(); $('welcome').hidden = state.history.length > 0;
    $('error').textContent = `${errorText(error)} If processing had already begun, some memories may have been saved. Refresh the memory panel to check.`;
    $('error').hidden = false;
  } finally { busy(false); $('message').focus(); }
});
$('message').addEventListener('keydown', event => { if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) { event.preventDefault(); $('chat-form').requestSubmit(); } });
$('new-session').addEventListener('click', resetSession);
function updateExtractionNote() {
  const follow = $('memory-backend').value === 'follow';
  const backend = follow ? $('agent-backend').selectedOptions[0].textContent : $('memory-backend').selectedOptions[0].textContent;
  const model = follow ? $('agent-model').value.trim() : $('memory-model').value.trim();
  $('extraction-note').textContent = `Extractor: ${backend} / ${model || 'provider default'} (${follow ? 'follows task' : 'independent control'}). CLI providers receive their task or extraction inputs. Embeddings and storage stay local. Use a new experiment space for a clean comparison.`;
}
$('agent-backend').addEventListener('change', () => { $('agent-model').value = ''; updateExtractionNote(); resetSession(); });
$('agent-model').addEventListener('change', () => { updateExtractionNote(); resetSession(); });
$('memory-backend').addEventListener('change', () => { $('memory-model').value = ''; $('memory-model').placeholder = $('memory-backend').value === 'follow' ? 'Follows the task model' : "Use the extractor's default model"; busy(false); updateExtractionNote(); resetSession(); });
$('memory-model').addEventListener('change', () => { updateExtractionNote(); resetSession(); });
$('health').addEventListener('click', checkHealth);
$('refresh-memory').addEventListener('click', refreshMemories);
$('load-memory').addEventListener('click', refreshMemories);
$('mode').addEventListener('change', () => { $('mode-note').textContent = modeNotes[$('mode').value]; });
for (const id of ['experiment', 'user']) {
  $(id).addEventListener('change', () => {
    const value = $(id).value.trim();
    if (!/^[A-Za-z0-9_-]{1,80}$/.test(value)) { $(id).value = state[id]; $('error').textContent = 'Names must contain 1–80 letters, numbers, underscores or hyphens.'; $('error').hidden = false; return; }
    if (value === state[id]) return;
    state[id] = value; state.memoryRequest++; resetSession(); $('memory-count').textContent = '—'; $('memory-list').replaceChildren();
    $('memory-notice').textContent = 'Space or user changed. Refresh to load its saved memories.';
  });
}
document.querySelectorAll('[data-example]').forEach(button => button.addEventListener('click', () => { $('message').value = button.dataset.example; $('message').focus(); }));
checkHealth();
updateExtractionNote();
