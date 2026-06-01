/**
 * frontend/script.js
 * ====================
 * Autonomous Browser Agent — frontend controller.
 *
 * Handles:
 * - Task submission and SSE log streaming
 * - Results rendering (jobs + JSON)
 * - Panel navigation
 * - Job history loading and search
 * - Resume upload and profile display
 * - Toast notifications
 */

'use strict';

// ── Config ────────────────────────────────────────────────────────────────────

const DEFAULT_API_ORIGIN = 'http://localhost:8001';
const API_ORIGIN = window.location.protocol === 'file:'
  ? DEFAULT_API_ORIGIN
  : window.location.origin;
const API_BASE = `${API_ORIGIN}/api`;

// ── State ─────────────────────────────────────────────────────────────────────

let currentTaskId   = null;
let sseSource       = null;
let pollInterval    = null;
let resultData      = null;
let progressValue   = 0;
let progressTimer   = null;

// ── DOM helpers ───────────────────────────────────────────────────────────────

const $  = id => document.getElementById(id);
const el = (tag, cls, html) => {
  const e = document.createElement(tag);
  if (cls)  e.className   = cls;
  if (html) e.innerHTML   = html;
  return e;
};

// ── Server health check ───────────────────────────────────────────────────────

async function checkServerHealth() {
  try {
    const res = await fetch(`${API_BASE.replace('/api', '')}/health`, { signal: AbortSignal.timeout(3000) });
    $('serverStatus').className = res.ok ? 'status-dot online' : 'status-dot offline';
  } catch {
    $('serverStatus').className = 'status-dot offline';
  }
}

// ── Navigation ────────────────────────────────────────────────────────────────

document.querySelectorAll('.nav-link').forEach(link => {
  link.addEventListener('click', e => {
    e.preventDefault();
    const panel = link.dataset.panel;

    document.querySelectorAll('.nav-link').forEach(l => l.classList.remove('active'));
    document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));

    link.classList.add('active');
    $(`panel-${panel}`).classList.add('active');

    if (panel === 'history') loadJobHistory();
  });
});

// ── Quick prompts ─────────────────────────────────────────────────────────────

document.querySelectorAll('.qp-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    $('promptInput').value = btn.dataset.prompt;
    $('promptInput').focus();
  });
});

// ── Task submission ───────────────────────────────────────────────────────────

async function submitTask() {
  const prompt = $('promptInput').value.trim();
  if (!prompt) { toast('Please enter a task description.', 'error'); return; }

  // Reset UI
  clearLogs();
  resultData = null;
  $('resultArea').innerHTML = '';
  $('workspace').style.display = 'grid';
  $('statusBar').style.display = 'block';
  $('submitBtn').disabled = true;
  $('progressFill').style.width = '0%';

  const headless = $('headlessMode').checked;
  const maxSteps = parseInt($('maxSteps').value);

  setStatus('🚀 Submitting task…');

  try {
    const res = await fetch(`${API_BASE}/task`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ prompt, headless, max_steps: maxSteps }),
    });

    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || 'Task submission failed');
    }

    const data = await res.json();
    currentTaskId = data.task_id;
    $('taskIdLabel').textContent = `ID: ${currentTaskId.slice(0, 8)}…`;
    setStatus('⚙️ Agent is running…');

    startProgressSimulation();
    startSSEStream(currentTaskId);
    startPolling(currentTaskId);

  } catch (err) {
    toast(`Error: ${err.message}`, 'error');
    setStatus('❌ Failed to start task');
    resetSubmitButton();
  }
}

// Allow Enter + Ctrl/Cmd to submit
$('promptInput').addEventListener('keydown', e => {
  if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') submitTask();
});

// ── SSE Log Streaming ─────────────────────────────────────────────────────────

function startSSEStream(taskId) {
  if (sseSource) sseSource.close();

  sseSource = new EventSource(`${API_BASE}/task/${taskId}/logs`);

  sseSource.onmessage = e => {
    try {
      const entry = JSON.parse(e.data);
      if (entry.type === 'done') {
        sseSource.close();
        return;
      }
      appendLog(entry.level || 'info', entry.message || e.data);
    } catch {
      appendLog('info', e.data);
    }
  };

  sseSource.onerror = () => sseSource.close();
}

// ── Task polling ──────────────────────────────────────────────────────────────

function startPolling(taskId) {
  if (pollInterval) clearInterval(pollInterval);

  pollInterval = setInterval(async () => {
    try {
      const res = await fetch(`${API_BASE}/task/${taskId}`);
      if (!res.ok) return;
      const task = await res.json();
      handleTaskUpdate(task);
    } catch { /* ignore network blips */ }
  }, 1500);
}

function handleTaskUpdate(task) {
  const { status, result, error, steps_completed } = task;

  if (status === 'completed') {
    clearInterval(pollInterval);
    stopProgressSimulation();
    $('progressFill').style.width = '100%';
    setStatus(`✅ Completed — ${steps_completed || 0} steps`);
    appendLog('success', '✅ Agent task completed successfully!');
    renderResults(result);
    resetSubmitButton();
    toast('Task completed!', 'success');

  } else if (status === 'failed') {
    clearInterval(pollInterval);
    stopProgressSimulation();
    setStatus(`❌ Failed: ${error || 'Unknown error'}`);
    appendLog('error', `❌ Task failed: ${error || 'Unknown error'}`);
    resetSubmitButton();
    toast('Task failed. Check logs.', 'error');

  } else if (status === 'cancelled') {
    clearInterval(pollInterval);
    stopProgressSimulation();
    setStatus('🛑 Task cancelled');
    resetSubmitButton();
  }
}

// ── Cancel task ───────────────────────────────────────────────────────────────

async function cancelTask() {
  if (!currentTaskId) return;
  try {
    await fetch(`${API_BASE}/task/${currentTaskId}`, { method: 'DELETE' });
    if (sseSource) sseSource.close();
    clearInterval(pollInterval);
    stopProgressSimulation();
    setStatus('🛑 Cancelled');
    appendLog('warn', '🛑 Task cancelled by user');
    resetSubmitButton();
    toast('Task cancelled');
  } catch (err) {
    toast(`Cancel failed: ${err.message}`, 'error');
  }
}

// ── Progress simulation ───────────────────────────────────────────────────────

function startProgressSimulation() {
  progressValue = 0;
  progressTimer = setInterval(() => {
    // Simulate progress: fast at first, slow near 90%
    const increment = progressValue < 40 ? 3 : progressValue < 70 ? 1.2 : 0.3;
    progressValue = Math.min(progressValue + increment, 90);
    $('progressFill').style.width = progressValue + '%';
  }, 800);
}

function stopProgressSimulation() {
  clearInterval(progressTimer);
}

// ── Log rendering ─────────────────────────────────────────────────────────────

function appendLog(level, message) {
  const terminal = $('terminal');
  const now = new Date().toLocaleTimeString('en-US', { hour12: false });

  const levelMap = {
    info: 'INFO', success: 'DONE', warn: 'WARN', error: 'ERR!',
  };

  const line = el('div', `log-line ${level}`);
  line.innerHTML = `
    <span class="log-time">${now}</span>
    <span class="log-level">${levelMap[level] || 'INFO'}</span>
    <span class="log-msg">${escapeHtml(message)}</span>
  `;
  terminal.appendChild(line);
  terminal.scrollTop = terminal.scrollHeight;
}

function clearLogs() {
  $('terminal').innerHTML = '';
}

// ── Result rendering ──────────────────────────────────────────────────────────

function renderResults(data) {
  resultData = data;
  const area = $('resultArea');

  if (!data) {
    area.innerHTML = '<p style="color:var(--text-muted);padding:1rem;">No structured results returned.</p>';
    return;
  }

  // Check for jobs
  const jobs = data.jobs || (Array.isArray(data) ? data : null);

  if (jobs && jobs.length > 0) {
    area.innerHTML = '';
    const section = el('div', 'jobs-section');
    section.appendChild(el('div', 'jobs-count', `Found <strong>${jobs.length}</strong> opportunities`));

    jobs.forEach(job => {
      section.appendChild(buildJobCard(job));
    });

    area.appendChild(section);
  } else {
    // Render as formatted JSON
    area.innerHTML = `<pre class="result-json">${escapeHtml(JSON.stringify(data, null, 2))}</pre>`;
  }
}

function buildJobCard(job) {
  const skills = (job.skills || []).slice(0, 6).map(s =>
    `<span class="skill-tag">${escapeHtml(s)}</span>`
  ).join('');

  const applyLink = job.apply_link
    ? `<a class="job-apply-link" href="${escapeHtml(job.apply_link)}" target="_blank" rel="noopener">Apply →</a>`
    : '';

  const card = el('div', 'job-card');
  card.innerHTML = `
    <div class="job-card-header">
      <div class="job-role">${escapeHtml(job.role || 'Unknown Role')}</div>
      ${job.job_type ? `<span class="job-type-badge">${escapeHtml(job.job_type)}</span>` : ''}
    </div>
    <div class="job-company">🏢 ${escapeHtml(job.company || 'Unknown Company')}</div>
    <div class="job-meta">
      ${job.location ? `<span>📍 ${escapeHtml(job.location)}</span>` : ''}
      ${job.salary && job.salary !== 'Not specified' ? `<span>💰 ${escapeHtml(job.salary)}</span>` : ''}
      ${job.source ? `<span>🌐 ${escapeHtml(job.source)}</span>` : ''}
    </div>
    ${skills ? `<div class="job-skills">${skills}</div>` : ''}
    ${applyLink}
  `;
  return card;
}

// ── Copy & Export ─────────────────────────────────────────────────────────────

async function copyResults() {
  if (!resultData) { toast('No results to copy.', 'error'); return; }
  try {
    await navigator.clipboard.writeText(JSON.stringify(resultData, null, 2));
    toast('Copied to clipboard!', 'success');
  } catch {
    toast('Copy failed.', 'error');
  }
}

function downloadResults() {
  if (!resultData) { toast('No results to download.', 'error'); return; }
  const blob = new Blob([JSON.stringify(resultData, null, 2)], { type: 'application/json' });
  const url  = URL.createObjectURL(blob);
  const a    = document.createElement('a');
  a.href     = url;
  a.download = `agent_results_${Date.now()}.json`;
  a.click();
  URL.revokeObjectURL(url);
  toast('Results downloaded!', 'success');
}

// ── Job History ───────────────────────────────────────────────────────────────

async function loadJobHistory() {
  const grid = $('jobGrid');
  grid.innerHTML = '<div class="empty-state"><p>Loading…</p></div>';
  try {
    const res  = await fetch(`${API_BASE}/history/jobs?limit=100`);
    const data = await res.json();
    const jobs = data.jobs || [];

    if (jobs.length === 0) {
      grid.innerHTML = '<div class="empty-state"><p>No jobs in memory yet.</p></div>';
      return;
    }

    grid.innerHTML = '';
    jobs.forEach(job => {
      // Jobs from history API come as metadata objects
      const jobData = job.metadata ? {
        role:       job.metadata.role,
        company:    job.metadata.company,
        location:   job.metadata.location,
        salary:     job.metadata.salary,
        apply_link: job.metadata.apply_link,
        source:     job.metadata.source,
        skills:     job.metadata.skills ? job.metadata.skills.split(', ') : [],
      } : job;
      grid.appendChild(buildJobCard(jobData));
    });
  } catch (err) {
    grid.innerHTML = `<div class="empty-state"><p>Failed to load: ${err.message}</p></div>`;
  }
}

async function searchJobs(query) {
  if (!query.trim()) { loadJobHistory(); return; }
  const grid = $('jobGrid');
  try {
    const res  = await fetch(`${API_BASE}/history/search?q=${encodeURIComponent(query)}&collection=jobs`);
    const data = await res.json();
    const results = data.results || [];

    if (results.length === 0) {
      grid.innerHTML = `<div class="empty-state"><p>No results for "${escapeHtml(query)}"</p></div>`;
      return;
    }

    grid.innerHTML = '';
    results.forEach(r => {
      const jobData = r.metadata ? {
        role:       r.metadata.role,
        company:    r.metadata.company,
        location:   r.metadata.location,
        salary:     r.metadata.salary,
        apply_link: r.metadata.apply_link,
        skills:     r.metadata.skills ? r.metadata.skills.split(', ') : [],
      } : r;
      grid.appendChild(buildJobCard(jobData));
    });
  } catch { /* ignore */ }
}

async function clearJobHistory() {
  if (!confirm('Clear all stored jobs from memory?')) return;
  try {
    await fetch(`${API_BASE}/history?collection=jobs`, { method: 'DELETE' });
    toast('Job history cleared.', 'success');
    loadJobHistory();
  } catch (err) {
    toast(`Failed: ${err.message}`, 'error');
  }
}

// ── Resume Upload ─────────────────────────────────────────────────────────────

async function uploadResume() {
  const file = $('resumeFile').files[0];
  if (!file) return;

  const zone = $('uploadZone');
  zone.querySelector('.upload-text').textContent = `Uploading ${file.name}…`;

  const form = new FormData();
  form.append('file', file);

  try {
    const res  = await fetch(`${API_BASE}/upload-resume`, { method: 'POST', body: form });
    const data = await res.json();

    if (!res.ok) throw new Error(data.detail || 'Upload failed');

    zone.querySelector('.upload-text').textContent = `✅ ${file.name} uploaded`;
    renderResumeProfile(data.profile);
    toast('Resume parsed successfully!', 'success');
  } catch (err) {
    zone.querySelector('.upload-text').textContent = 'Drop your PDF resume here or click to upload';
    toast(`Upload failed: ${err.message}`, 'error');
  }
}

function renderResumeProfile(profile) {
  const container = $('resumeResult');
  container.style.display = 'block';

  const skills = (profile.skills || []).map(s =>
    `<span class="skill-tag">${escapeHtml(s)}</span>`
  ).join('');

  const experience = (profile.experience || []).map(exp => `
    <div style="margin-bottom:.6rem;">
      <div style="font-weight:600;font-size:.85rem;">${escapeHtml(exp.role || '')} @ ${escapeHtml(exp.company || '')}</div>
      <div style="font-size:.75rem;color:var(--text-muted);">${escapeHtml(exp.duration || '')}</div>
      <div style="font-size:.8rem;color:var(--text-dim);margin-top:.2rem;">${escapeHtml(exp.description || '')}</div>
    </div>
  `).join('');

  const education = (profile.education || []).map(edu => `
    <div style="margin-bottom:.4rem;">
      <div style="font-weight:600;font-size:.85rem;">${escapeHtml(edu.degree || '')}</div>
      <div style="font-size:.75rem;color:var(--text-muted);">${escapeHtml(edu.institution || '')} • ${escapeHtml(edu.year || '')}</div>
    </div>
  `).join('');

  container.innerHTML = `
    <div class="resume-section">
      <div class="resume-name">${escapeHtml(profile.name || 'Name not found')}</div>
      <div class="resume-contact">
        ${profile.email    ? `<span>✉ ${escapeHtml(profile.email)}</span>` : ''}
        ${profile.phone    ? `<span>📞 ${escapeHtml(profile.phone)}</span>` : ''}
        ${profile.location ? `<span>📍 ${escapeHtml(profile.location)}</span>` : ''}
      </div>
      ${profile.summary ? `<p style="font-size:.82rem;color:var(--text-dim);margin-top:.5rem;">${escapeHtml(profile.summary)}</p>` : ''}
    </div>

    ${skills ? `
    <div class="resume-section">
      <div class="resume-section-title">Skills</div>
      <div class="job-skills">${skills}</div>
    </div>` : ''}

    ${experience ? `
    <div class="resume-section">
      <div class="resume-section-title">Experience</div>
      ${experience}
    </div>` : ''}

    ${education ? `
    <div class="resume-section">
      <div class="resume-section-title">Education</div>
      ${education}
    </div>` : ''}

    ${profile.github || profile.linkedin ? `
    <div class="resume-section">
      <div class="resume-section-title">Links</div>
      <div style="display:flex;flex-wrap:wrap;gap:.5rem;font-size:.8rem;">
        ${profile.github   ? `<a href="${escapeHtml(profile.github)}" target="_blank" class="job-apply-link">GitHub</a>` : ''}
        ${profile.linkedin ? `<a href="${escapeHtml(profile.linkedin)}" target="_blank" class="job-apply-link">LinkedIn</a>` : ''}
      </div>
    </div>` : ''}
  `;
}

// ── Drag and drop for resume ──────────────────────────────────────────────────

const uploadZone = $('uploadZone');
uploadZone.addEventListener('dragover',  e => { e.preventDefault(); uploadZone.style.borderColor = 'var(--accent)'; });
uploadZone.addEventListener('dragleave', ()  => { uploadZone.style.borderColor = ''; });
uploadZone.addEventListener('drop', e => {
  e.preventDefault();
  uploadZone.style.borderColor = '';
  const file = e.dataTransfer.files[0];
  if (file && file.name.endsWith('.pdf')) {
    const dt = new DataTransfer();
    dt.items.add(file);
    $('resumeFile').files = dt.files;
    uploadResume();
  } else {
    toast('Please drop a PDF file.', 'error');
  }
});

// ── UI helpers ────────────────────────────────────────────────────────────────

function setStatus(text) {
  $('statusText').textContent = text;
}

function resetSubmitButton() {
  $('submitBtn').disabled = false;
  // Hide spinner after a moment
  setTimeout(() => {
    const spinner = $('statusSpinner');
    if (spinner) spinner.style.display = 'none';
  }, 2000);
}

function escapeHtml(str) {
  if (!str) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

// ── Toast notifications ───────────────────────────────────────────────────────

function toast(message, type = '') {
  const container = $('toastContainer');
  const t = el('div', `toast ${type}`, `${type === 'success' ? '✅' : type === 'error' ? '❌' : 'ℹ️'} ${escapeHtml(message)}`);
  container.appendChild(t);
  setTimeout(() => { t.style.opacity = '0'; t.style.transition = 'opacity .3s'; }, 2800);
  setTimeout(() => t.remove(), 3200);
}

// ── Init ──────────────────────────────────────────────────────────────────────

checkServerHealth();
setInterval(checkServerHealth, 10000);
