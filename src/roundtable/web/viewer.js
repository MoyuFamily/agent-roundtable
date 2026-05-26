// Config injected by server
const CONFIG = window.__RT_CONFIG__ || { token: '', port: 8199, host: '0.0.0.0' };
const API_BASE = '';

// State
let state = {
  status: 'waiting',
  speeches: [],
  participants: [],
  topic: '',
  conclusion: null,
  currentRound: 0,
  speechIdSet: new Set(),
  roundSummaries: [],
  roundSummarySet: new Set(),
  streamSpeechMap: new Map(),
};

// DOM refs
const $statusBadge = document.getElementById('statusBadge');
const $statusLabel = document.getElementById('statusLabel');
const $topicTitle = document.getElementById('topicTitle');
const $connDot = document.getElementById('connDot');
const $connText = document.getElementById('connText');
const $waitingState = document.getElementById('waitingState');
const $activeState = document.getElementById('activeState');
const $speechesContainer = document.getElementById('speechesContainer');
const $participantsBar = document.getElementById('participantsBar');
const $conclusionCard = document.getElementById('conclusionCard');
const $conclusionContent = document.getElementById('conclusionContent');
const $revokedState = document.getElementById('revokedState');

// ---- SSE Connection ----
let eventSource = null;
let reconnectAttempts = 0;
const MAX_RECONNECT_DELAY = 30000;

function connectSSE() {
  const url = `${API_BASE}/api/${CONFIG.token}/events`;

  if (typeof EventSource !== 'undefined') {
    // SSE (primary)
    eventSource = new EventSource(url);

    eventSource.addEventListener('init', (e) => {
      const data = JSON.parse(e.data);
      handleData(data);
      setConnection('connected');
      reconnectAttempts = 0;
    });

    eventSource.addEventListener('update', (e) => {
      const data = JSON.parse(e.data);
      handleData(data);
    });

    eventSource.addEventListener('delta', (e) => {
      const data = JSON.parse(e.data);
      handleDelta(data);
    });

    eventSource.addEventListener('revoked', () => {
      showRevoked();
    });

    eventSource.onerror = () => {
      setConnection('reconnecting');
      eventSource.close();
      reconnectAttempts++;
      const delay = Math.min(1000 * Math.pow(2, reconnectAttempts), MAX_RECONNECT_DELAY);
      setTimeout(connectSSE, delay);
    };
  } else {
    // Long-polling fallback (WeChat)
    startLongPolling();
  }
}

function startLongPolling() {
  let since = 0;

  async function poll() {
    try {
      const resp = await fetch(`${API_BASE}/api/${CONFIG.token}/poll?since=${since}`);
      if (resp.status === 403) { showRevoked(); return; }
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);

      const data = await resp.json();
      if (data.updated_at > since) {
        since = data.updated_at;
        handleData(data);
      }
      setConnection('connected');
    } catch (err) {
      setConnection('disconnected');
      await new Promise(r => setTimeout(r, 3000));
    }

    poll(); // continue polling
  }

  poll();
}

// ---- Data handling ----
function handleDelta(data) {
  const events = Array.isArray(data?.events) ? data.events : [];
  for (const eventData of events) {
    applyStreamEvent(eventData);
  }
  if (events.length > 0) {
    $waitingState.classList.add('hidden');
    $activeState.classList.remove('hidden');
  }
}

function applyStreamEvent(eventData) {
  if (!eventData || !eventData.type) return;
  if (eventData.type === 'speech_start') {
    renderStreamingSpeechStart(eventData);
  } else if (eventData.type === 'speech_token') {
    appendStreamingSpeechToken(eventData);
  } else if (eventData.type === 'speech_end') {
    markStreamingSpeechEnd(eventData);
  } else if (eventData.type === 'speech_delta') {
    const speech = eventData.speech || eventData.payload?.speech;
    if (speech) mergeSpeech(speech, true);
  } else if (eventData.type === 'status_delta') {
    if (eventData.status || eventData.payload?.status) {
      state.status = eventData.status || eventData.payload.status;
      updateStatusUI();
    }
    const conclusion = eventData.conclusion || eventData.payload?.conclusion;
    if (conclusion && !state.conclusion) {
      state.conclusion = conclusion;
      renderConclusion(conclusion);
    }
  } else if (eventData.type === 'round_summary') {
    renderRoundSummary(eventData);
  } else if (eventData.type === 'final_summary') {
    renderFinalSummary(eventData);
  }
}

function handleData(data) {
  if (data.status === 'revoked' || (data.revoked_tokens && data.revoked_tokens.includes(CONFIG.token))) {
    showRevoked();
    return;
  }

  // Update topic
  if (data.topic && data.topic !== state.topic) {
    state.topic = data.topic;
    $topicTitle.textContent = data.topic;
    document.title = `${data.topic} — 圆桌讨论`;
  }

  // Update participants
  if (data.participants) {
    state.participants = data.participants;
    renderParticipants();
  }

  // Update speeches
  if (data.speeches) {
    const isInitialLoad = state.speeches.length === 0;
    for (const speech of data.speeches) {
      mergeSpeech(speech, !isInitialLoad);
    }

    // If it was the initial load, collapse older rounds
    if (isInitialLoad && state.speeches.length > 0) {
      const rounds = [...new Set(state.speeches.map(s => s.round))].sort((a, b) => a - b);
      if (rounds.length > 1) {
        const latestRound = rounds[rounds.length - 1];
        for (const r of rounds) {
          if (r !== latestRound) {
            const section = document.getElementById(`round-section-${r}`);
            if (section) {
              section.classList.add('collapsed');
            }
          }
        }
      }
    }
  }

  // Update status
  if (data.status !== state.status) {
    state.status = data.status;
    updateStatusUI();
  }

  // Conclusion
  if (data.conclusion && !state.conclusion) {
    state.conclusion = data.conclusion;
    renderConclusion(data.conclusion);
  }

  // Round summaries / viewpoint cards
  if (Array.isArray(data.round_summaries)) {
    for (const summary of data.round_summaries) {
      renderRoundSummary(summary);
    }
  }

  if (data.final_summary) {
    renderFinalSummary(data.final_summary);
  }

  // Show active state if we have speeches or viewpoint cards
  if ((state.speeches.length > 0 || state.roundSummaries.length > 0) && state.status !== 'waiting') {
    $waitingState.classList.add('hidden');
    $activeState.classList.remove('hidden');
  }
}

// ---- Helper functions for role styles and aggregation ----
function getRoleType(roleStr) {
  if (!roleStr) return 'default';
  const r = roleStr.toLowerCase();
  if (r.includes('product') || r.includes('pm') || r.includes('director') || r.includes('经理') || r.includes('总监')) return 'product';
  if (r.includes('design') || r.includes('ui') || r.includes('ux') || r.includes('设计')) return 'design';
  if (r.includes('engineer') || r.includes('dev') || r.includes('coder') || r.includes('tech') || r.includes('开发') || r.includes('工程') || r.includes('技术')) return 'engineer';
  if (r.includes('research') || r.includes('science') || r.includes('sci') || r.includes('researcher') || r.includes('研究') || r.includes('分析')) return 'research';
  if (r.includes('marketing') || r.includes('sales') || r.includes('biz') || r.includes('运营') || r.includes('市场')) return 'marketing';
  return 'default';
}

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, ch => ({
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#39;'
  })[ch]);
}

function renderMarkdown(value) {
  const html = marked.parse(String(value ?? ''));
  if (window.DOMPurify) {
    return DOMPurify.sanitize(html);
  }
  const template = document.createElement('template');
  template.innerHTML = html;
  template.content.querySelectorAll('script, iframe, object, embed, link, meta').forEach(el => el.remove());
  template.content.querySelectorAll('*').forEach(el => {
    for (const attr of [...el.attributes]) {
      if (/^on/i.test(attr.name) || /javascript:/i.test(attr.value)) {
        el.removeAttribute(attr.name);
      }
    }
  });
  return template.innerHTML;
}

window.toggleRound = function(roundNum) {
  const section = document.getElementById(`round-section-${roundNum}`);
  if (section) {
    section.classList.toggle('collapsed');
  }
};

function getOrCreateRoundSection(roundNum, isNew) {
  const id = `round-section-${roundNum}`;
  let section = document.getElementById(id);
  if (!section) {
    section = document.createElement('div');
    section.id = id;
    section.className = 'round-section';
    
    const titleText = roundNum === 0 ? '📢 开场发言 (Round 0)' : `💬 第 ${roundNum} 轮讨论 (Round ${roundNum})`;
    
    section.innerHTML = `
      <div class="round-header" onclick="toggleRound(${roundNum})">
        <div class="round-title">
          <span>${titleText}</span>
          <span class="round-badge-count" id="round-count-${roundNum}">0 条发言</span>
        </div>
        <svg class="toggle-icon" viewBox="0 0 24 24">
          <path d="M19 9l-7 7-7-7" />
        </svg>
      </div>
      <div class="round-body" id="round-body-${roundNum}"></div>
    `;
    
    // Collapse all previous rounds if it's dynamic update (isNew)
    if (isNew) {
      const existingSections = $speechesContainer.querySelectorAll('.round-section');
      existingSections.forEach(s => s.classList.add('collapsed'));
    }
    
    $speechesContainer.appendChild(section);
  }
  return section;
}

// ---- Rendering ----
function renderParticipants() {
  $participantsBar.innerHTML = state.participants.map(p => `
    <div class="flex items-center gap-2 rounded-full px-3 py-1.5 text-sm whitespace-nowrap" style="background:var(--rt-bg-card);border:1px solid var(--rt-border)">
      <div class="avatar" style="width:24px;height:24px;font-size:11px">${escapeHtml((p.display_name || p.profile || '?')[0])}</div>
      <span class="font-medium" style="color:var(--rt-text-primary)">${escapeHtml(p.display_name || p.profile)}</span>
      ${p.role ? `<span class="text-xs" style="color:var(--rt-text-muted)">${escapeHtml(p.role)}</span>` : ''}
    </div>
  `).join('');
}

function participantMeta(agent) {
  const participantObj = state.participants.find(p => p.profile === agent || p.participant === agent);
  return {
    name: participantObj?.display_name || agent || 'Agent',
    role: participantObj?.role || '',
    roleType: agent === 'coordinator' ? 'coordinator' : getRoleType(participantObj?.role || ''),
  };
}

function updateRoundCount(roundNum) {
  const body = document.getElementById(`round-body-${roundNum}`);
  const countEl = document.getElementById(`round-count-${roundNum}`);
  if (body && countEl) {
    const count = body.querySelectorAll('.speech-card').length;
    countEl.textContent = `${count} 条发言`;
  }
}

function renderStreamingSpeechStart(eventData) {
  const id = eventData.id;
  if (!id || state.streamSpeechMap.has(id)) return;
  const agent = eventData.agent || eventData.participant || '';
  const meta = participantMeta(agent);
  const roundNum = Number(eventData.round || 0);
  const div = document.createElement('div');
  div.className = `speech-card role-${meta.roleType} new highlight streaming`;
  div.id = `speech-${id}`;

  const initial = escapeHtml((meta.name || agent || '?')[0]);
  const speakerName = escapeHtml(meta.name);
  const safeRoleName = escapeHtml(meta.role);
  const round = roundNum > 0 ? `<span class="round-badge" style="background: var(--rt-role-${meta.roleType}-bg); color: var(--rt-role-${meta.roleType})">R${roundNum}</span>` : '';
  div.innerHTML = `
    <div class="flex items-start gap-3">
      <div class="avatar" style="background: var(--rt-role-${meta.roleType}); color: var(--rt-text-inverse); box-shadow: 0 0 8px var(--rt-role-${meta.roleType}-bg)">${initial}</div>
      <div class="flex-1 min-w-0">
        <div class="flex items-center gap-2 mb-2">
          <span class="font-semibold text-sm" style="color:var(--rt-text-primary)">${speakerName}</span>
          ${meta.role ? `<span class="text-xs px-2 py-0.5 rounded-full font-medium" style="background: var(--rt-role-${meta.roleType}-bg); color: var(--rt-role-${meta.roleType})">${safeRoleName}</span>` : ''}
          ${round}
          <span class="text-xs ml-auto" style="color:var(--rt-text-muted)">${formatTime(eventData.timestamp)}</span>
        </div>
        <div class="text-sm leading-relaxed markdown-content stream-content stream-cursor" style="color:var(--rt-text-secondary)"></div>
      </div>
    </div>
  `;
  getOrCreateRoundSection(roundNum, true);
  const body = document.getElementById(`round-body-${roundNum}`);
  body.appendChild(div);
  state.streamSpeechMap.set(id, { el: div, content: '', round: roundNum });
  updateRoundCount(roundNum);
  setTimeout(() => div.classList.remove('highlight'), 2000);
  div.scrollIntoView({ behavior: 'smooth', block: 'end' });
}

function appendStreamingSpeechToken(eventData) {
  const id = eventData.id;
  let entry = state.streamSpeechMap.get(id);
  if (!entry) {
    renderStreamingSpeechStart({ id, agent: eventData.agent || 'agent', round: eventData.round || state.currentRound || 0, timestamp: eventData.timestamp });
    entry = state.streamSpeechMap.get(id);
  }
  if (!entry) return;
  entry.content += eventData.delta || '';
  const contentEl = entry.el.querySelector('.stream-content');
  if (contentEl) contentEl.innerHTML = renderMarkdown(entry.content);
}

function markStreamingSpeechEnd(eventData) {
  const entry = state.streamSpeechMap.get(eventData.id);
  if (!entry) return;
  entry.el.classList.remove('streaming');
  const contentEl = entry.el.querySelector('.stream-content');
  if (contentEl) contentEl.classList.remove('stream-cursor');
}

function normalizeViewpointItems(items) {
  if (!Array.isArray(items)) return [];
  return items.map(item => typeof item === 'string' ? { content: item } : item).filter(Boolean);
}

function renderViewpointList(items, type) {
  const normalized = normalizeViewpointItems(items);
  if (normalized.length === 0) return '<li class="viewpoint-item">暂无</li>';
  return normalized.map(item => {
    const content = escapeHtml(item.content || item.text || item.title || String(item));
    const supporters = Array.isArray(item.supporters) && item.supporters.length > 0
      ? `<span class="viewpoint-supporters">支持：${escapeHtml(item.supporters.join('、'))}</span>`
      : '';
    return `<li class="viewpoint-item ${type}">${content}${supporters}</li>`;
  }).join('');
}

function renderRoundSummary(summary) {
  const roundNum = Number(summary.round || 0);
  const key = `round-${roundNum}`;
  state.roundSummarySet.add(key);
  state.roundSummaries = state.roundSummaries.filter(item => Number(item.round || 0) !== roundNum).concat(summary);
  getOrCreateRoundSection(roundNum, false);
  const body = document.getElementById(`round-body-${roundNum}`);
  let card = document.getElementById(`viewpoints-${key}`);
  if (!card) {
    card = document.createElement('div');
    card.id = `viewpoints-${key}`;
    card.className = 'viewpoints-card';
    body.appendChild(card);
  }
  const consensus = summary.consensus || summary.consensus_points || [];
  const disagreement = summary.disagreement || summary.disagreement_points || [];
  card.innerHTML = `
    <div class="viewpoints-title">
      <span>🧠 第 ${roundNum} 轮观点汇总</span>
      ${summary.convergence_score !== undefined ? `<span class="round-badge-count">收敛度 ${escapeHtml(summary.convergence_score)}</span>` : ''}
    </div>
    <div class="viewpoints-grid">
      <div class="viewpoints-column">
        <h4>✅ 共识观点</h4>
        <ul>${renderViewpointList(consensus, 'consensus')}</ul>
      </div>
      <div class="viewpoints-column">
        <h4>⚡ 分歧观点</h4>
        <ul>${renderViewpointList(disagreement, 'disagreement')}</ul>
      </div>
    </div>
  `;
}

function renderFinalSummary(summary) {
  if (!summary) return;
  const consensus = summary.consensus || summary.consensus_points || [];
  const disagreement = summary.disagreement || summary.disagreement_points || [];
  const verdict = summary.verdict ? `<div class="markdown-content mt-3">${renderMarkdown(summary.verdict)}</div>` : '';
  $conclusionContent.innerHTML = `
    <div class="viewpoints-grid">
      <div class="viewpoints-column">
        <h4>✅ 最终共识</h4>
        <ul>${renderViewpointList(consensus, 'consensus')}</ul>
      </div>
      <div class="viewpoints-column">
        <h4>⚡ 保留分歧</h4>
        <ul>${renderViewpointList(disagreement, 'disagreement')}</ul>
      </div>
    </div>
    ${verdict}
  `;
  $conclusionCard.classList.remove('hidden');
}

function mergeSpeech(speech, isNew = false) {
  if (!speech || speech.id === undefined || state.speechIdSet.has(speech.id)) return;
  state.speechIdSet.add(speech.id);
  state.speeches.push(speech);
  const streaming = state.streamSpeechMap.get(speech.id);
  if (streaming) {
    streaming.el.remove();
    state.streamSpeechMap.delete(speech.id);
  }
  renderSpeech(speech, isNew);
}

function renderSpeech(speech, isNew = false) {
  // Find role info
  let roleType = 'default';
  let roleName = '';
  if (speech.participant === 'coordinator') {
    roleType = 'coordinator';
    roleName = '👑 协调者';
  } else {
    const participantObj = state.participants.find(p => p.profile === speech.participant);
    if (participantObj) {
      roleType = getRoleType(participantObj.role);
      roleName = participantObj.role || '';
    }
  }

  const div = document.createElement('div');
  div.className = `speech-card role-${roleType}${isNew ? ' new highlight' : ''}`;
  div.id = `speech-${speech.id}`;

  const initial = escapeHtml((speech.display_name || speech.participant || '?')[0]);
  const speakerName = escapeHtml(speech.display_name || speech.participant);
  const safeRoleName = escapeHtml(roleName);
  const round = speech.round > 0 ? `<span class="round-badge" style="background: var(--rt-role-${roleType}-bg); color: var(--rt-role-${roleType})">R${speech.round}</span>` : '';

  div.innerHTML = `
    <div class="flex items-start gap-3">
      <div class="avatar" style="background: var(--rt-role-${roleType}); color: var(--rt-text-inverse); box-shadow: 0 0 8px var(--rt-role-${roleType}-bg)">${initial}</div>
      <div class="flex-1 min-w-0">
        <div class="flex items-center gap-2 mb-2">
          <span class="font-semibold text-sm" style="color:var(--rt-text-primary)">${speakerName}</span>
          ${roleName ? `<span class="text-xs px-2 py-0.5 rounded-full font-medium" style="background: var(--rt-role-${roleType}-bg); color: var(--rt-role-${roleType})">${safeRoleName}</span>` : ''}
          ${round}
          <span class="text-xs ml-auto" style="color:var(--rt-text-muted)">${formatTime(speech.created_at)}</span>
        </div>
        <div class="text-sm leading-relaxed markdown-content" style="color:var(--rt-text-secondary)">${renderMarkdown(speech.content)}</div>
      </div>
    </div>
  `;

  // Get or create round section
  getOrCreateRoundSection(speech.round, isNew);
  const body = document.getElementById(`round-body-${speech.round}`);
  body.appendChild(div);

  // Update count
  const countEl = document.getElementById(`round-count-${speech.round}`);
  if (countEl) {
    const count = body.children.length;
    countEl.textContent = `${count} 条发言`;
  }

  // Remove highlight after 2s
  if (isNew) {
    setTimeout(() => div.classList.remove('highlight'), 2000);
    // Auto-scroll
    div.scrollIntoView({ behavior: 'smooth', block: 'end' });
  }
}

function renderConclusion(content) {
  $conclusionContent.innerHTML = `<div class="markdown-content">${renderMarkdown(content)}</div>`;
  $conclusionCard.classList.remove('hidden');
  setTimeout(() => {
    $conclusionCard.scrollIntoView({ behavior: 'smooth', block: 'center' });
  }, 300);
}

function updateStatusUI() {
  const statusMap = {
    waiting: { cls: 'waiting', label: '等待中' },
    active:  { cls: 'live',    label: 'LIVE' },
    concluded: { cls: 'ended', label: '已结束' },
  };
  const info = statusMap[state.status] || statusMap.waiting;
  $statusBadge.className = `status-badge ${info.cls}`;
  $statusLabel.textContent = info.label;
  if (state.status === 'concluded') {
    $waitingState.classList.add('hidden');
    $activeState.classList.remove('hidden');
  }
}

function showRevoked() {
  $revokedState.classList.remove('hidden');
  if (eventSource) eventSource.close();
}

function setConnection(status) {
  $connDot.className = `conn-dot ${status}`;
  const labels = { connected: '已连接', disconnected: '已断开', reconnecting: '重连中…' };
  $connText.textContent = labels[status] || status;
}

// ---- Utils ----
function escapeHtml(str) {
  const div = document.createElement('div');
  div.textContent = str;
  return div.innerHTML;
}

function formatTime(ts) {
  if (!ts) return '';
  const d = new Date(ts * 1000);
  return `${d.getHours().toString().padStart(2, '0')}:${d.getMinutes().toString().padStart(2, '0')}`;
}

// ═══════════════════════════════════════
// Share Interaction Logic
// ═══════════════════════════════════════

// DOM refs — Share
const $shareContainer = document.getElementById('shareContainer');
const $shareBtn = document.getElementById('shareBtn');
const $sharePopover = document.getElementById('sharePopover');
const $sharePanelContent = document.getElementById('sharePanelContent');
const $shareLinkInput = document.getElementById('shareLinkInput');
const $copyBtn = document.getElementById('copyBtn');
const $revokeLinkBtn = document.getElementById('revokeLinkBtn');
const $shareRevokedState = document.getElementById('shareRevokedState');
const $mobileShareBtn = document.getElementById('mobileShareBtn');
const $shareSheetOverlay = document.getElementById('shareSheetOverlay');
const $shareSheet = document.getElementById('shareSheet');
const $shareSheetContent = document.getElementById('shareSheetContent');
const $shareSheetLinkInput = document.getElementById('shareSheetLinkInput');
const $sheetCopyBtn = document.getElementById('sheetCopyBtn');
const $sheetRevokeLinkBtn = document.getElementById('sheetRevokeLinkBtn');
const $sheetRevokedState = document.getElementById('sheetRevokedState');
const $revokeModalOverlay = document.getElementById('revokeModalOverlay');
const $revokeCancelBtn = document.getElementById('revokeCancelBtn');
const $revokeConfirmBtn = document.getElementById('revokeConfirmBtn');

// State
let shareLink = '';
let popoverOpen = false;
let sheetOpen = false;

function isMobile() {
  return window.innerWidth < 768;
}

// ---- Share Button Click ----
$shareBtn.addEventListener('click', async (e) => {
  e.stopPropagation();
  if (popoverOpen) {
    closePopover();
  } else {
    await openPopover();
  }
});

$mobileShareBtn.addEventListener('click', async () => {
  await openSheet();
});

// ---- Desktop Popover ----
async function openPopover() {
  if (isMobile()) {
    await openSheet();
    return;
  }
  // Generate share link if not already set
  if (!shareLink) {
    await generateShareLink();
  }
  $sharePopover.classList.add('visible');
  popoverOpen = true;
}

function closePopover() {
  $sharePopover.classList.remove('visible');
  popoverOpen = false;
}

// Close popover on click outside
document.addEventListener('click', (e) => {
  if (popoverOpen && !$shareContainer.contains(e.target)) {
    closePopover();
  }
});

// Close popover on ESC
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') {
    if (revokeModalOpen) {
      closeRevokeModal();
    } else if (sheetOpen) {
      closeSheet();
    } else if (popoverOpen) {
      closePopover();
    }
  }
});

// ---- Mobile Bottom Sheet ----
async function openSheet() {
  if (!shareLink) {
    await generateShareLink();
  }
  $shareSheetOverlay.classList.add('visible');
  $shareSheet.classList.add('visible');
  sheetOpen = true;
}

function closeSheet() {
  $shareSheetOverlay.classList.remove('visible');
  $shareSheet.classList.remove('visible');
  sheetOpen = false;
}

$shareSheetOverlay.addEventListener('click', closeSheet);

// ---- Generate Share Link ----
async function generateShareLink() {
  try {
    const resp = await fetch(`${API_BASE}/api/${CONFIG.token}/share`, {
      method: 'POST',
    });
    if (resp.ok) {
      const data = await resp.json();
      // Build full URL from the relative share_url
      shareLink = `${location.origin}${data.share_url}`;
    } else {
      // Fallback: just use current URL
      shareLink = location.href;
    }
  } catch {
    shareLink = location.href;
  }

  // Update UI
  $shareLinkInput.value = shareLink;
  $shareSheetLinkInput.value = shareLink;
}

// ---- Copy to Clipboard ----
function copyToClipboard(text) {
  if (navigator.clipboard && navigator.clipboard.writeText) {
    return navigator.clipboard.writeText(text);
  }
  // Fallback for WeChat / old browsers
  return new Promise((resolve, reject) => {
    const textarea = document.createElement('textarea');
    textarea.value = text;
    textarea.style.cssText = 'position:fixed;left:-9999px;top:-9999px;opacity:0';
    document.body.appendChild(textarea);
    textarea.select();
    try {
      document.execCommand('copy');
      resolve();
    } catch (err) {
      reject(err);
    } finally {
      document.body.removeChild(textarea);
    }
  });
}

function showCopySuccess(btn, originalText) {
  btn.textContent = '✓ 已复制';
  btn.classList.add('copied');
  btn.disabled = true;
  setTimeout(() => {
    btn.textContent = originalText;
    btn.classList.remove('copied');
    btn.disabled = false;
  }, 2000);
}

$copyBtn.addEventListener('click', async () => {
  if (!shareLink) return;
  try {
    await copyToClipboard(shareLink);
    showCopySuccess($copyBtn, '复制');
  } catch {
    // If clipboard fails, select the input so user can manually copy
    $shareLinkInput.select();
  }
});

$sheetCopyBtn.addEventListener('click', async () => {
  if (!shareLink) return;
  try {
    await copyToClipboard(shareLink);
    showCopySuccess($sheetCopyBtn, '复制链接');
  } catch {
    $shareSheetLinkInput.select();
  }
});

// ---- Revoke Confirmation Modal ----
let revokeModalOpen = false;

function openRevokeModal() {
  $revokeModalOverlay.classList.add('visible');
  revokeModalOpen = true;
}

function closeRevokeModal() {
  $revokeModalOverlay.classList.remove('visible');
  revokeModalOpen = false;
}

$revokeLinkBtn.addEventListener('click', () => {
  openRevokeModal();
});

$sheetRevokeLinkBtn.addEventListener('click', () => {
  openRevokeModal();
});

$revokeCancelBtn.addEventListener('click', closeRevokeModal);

// Close modal on overlay click
$revokeModalOverlay.addEventListener('click', (e) => {
  if (e.target === $revokeModalOverlay) {
    closeRevokeModal();
  }
});

// ---- Revoke Confirm ----
$revokeConfirmBtn.addEventListener('click', async () => {
  $revokeConfirmBtn.disabled = true;
  $revokeConfirmBtn.textContent = '撤销中…';

  try {
    const resp = await fetch(`${API_BASE}/api/${CONFIG.token}/revoke`, {
      method: 'POST',
    });

    if (resp.ok) {
      closeRevokeModal();
      showRevokedInPanel();
      // The SSE 'revoked' event will show the full-page revoked state
    } else {
      alert('撤销失败，请重试');
      $revokeConfirmBtn.disabled = false;
      $revokeConfirmBtn.textContent = '确认撤销';
    }
  } catch {
    alert('网络错误，请重试');
    $revokeConfirmBtn.disabled = false;
    $revokeConfirmBtn.textContent = '确认撤销';
  }
});

function showRevokedInPanel() {
  // Desktop popover
  $sharePanelContent.classList.add('hidden');
  $shareRevokedState.classList.remove('hidden');
  // Mobile sheet
  $shareSheetContent.classList.add('hidden');
  $sheetRevokedState.classList.remove('hidden');
  // Auto-close panels after 3s
  setTimeout(() => {
    closePopover();
    closeSheet();
  }, 3000);
}

// ---- Init ----
connectSSE();
