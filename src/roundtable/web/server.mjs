#!/usr/bin/env node
/**
 * Shared Express server for Roundtable Web Viewer.
 *
 * One process serves every discussion under --data-dir/<id>/discussion.json,
 * keyed by per-discussion token. Express discovers existing discussions on
 * startup, and watches the data-dir for new subdirectories.
 *
 * CLI usage:
 *   node server.mjs --port 8199 --data-dir /tmp/roundtable_web
 */

import { createServer } from "node:http";
import {
  readFileSync,
  watch,
  existsSync,
  writeFileSync,
  renameSync,
  createReadStream,
  readdirSync,
  mkdirSync,
  statSync,
  unlinkSync,
} from "node:fs";
import * as readline from "node:readline";
import { join, resolve, dirname, basename } from "node:path";
import { createHash, createHmac, randomBytes, timingSafeEqual } from "node:crypto";

// ---------------------------------------------------------------------------
// CLI args
// ---------------------------------------------------------------------------

function parseArgs() {
  const args = process.argv.slice(2);
  const opts = { port: 8199, dataDir: "" };
  for (let i = 0; i < args.length; i++) {
    if (args[i] === "--port" && args[i + 1]) opts.port = parseInt(args[++i], 10);
    if (args[i] === "--data-dir" && args[i + 1]) opts.dataDir = args[++i];
  }
  if (!opts.dataDir) {
    console.error("[Roundtable Web] --data-dir is required");
    process.exit(1);
  }
  return opts;
}

const { port, dataDir: dataDirArg } = parseArgs();
const DATA_DIR = resolve(dataDirArg);
const WEB_DIR = new URL(".", import.meta.url).pathname;
const SERVER_SECRET = randomBytes(32);

// ---------------------------------------------------------------------------
// Discussion registry
// ---------------------------------------------------------------------------

/**
 * @typedef {{
 *   discussionId: string,
 *   dir: string,
 *   discussionPath: string,
 *   tokenStreamPath: string,
 *   passwordHash: string | null,
 *   expiresAt: number | null,
 *   revokedTokenHashes: Set<string>,
 *   tokenHash: string,
 * }} DiscussionEntry
 */

/** @type {Map<string, DiscussionEntry>} */
const byTokenHash = new Map();
/** @type {Map<string, DiscussionEntry>} */
const byDiscussionId = new Map();
/** @type {Map<string, import("fs").FSWatcher>} */
const subdirWatchers = new Map();

function safeReadJSON(path) {
  try {
    if (!existsSync(path)) return null;
    const raw = readFileSync(path, "utf-8");
    return JSON.parse(raw);
  } catch {
    return null;
  }
}

function registerDiscussion(dir, discussionId) {
  const discPath = join(dir, "discussion.json");
  const data = safeReadJSON(discPath);
  if (!data) return null;
  const tokenHash = data.token_hash || (data.token ? _hashToken(data.token) : null);
  if (!tokenHash) return null;

  const previous = byDiscussionId.get(discussionId);
  if (previous && previous.tokenHash !== tokenHash) {
    byTokenHash.delete(previous.tokenHash);
  }

  const entry = {
    discussionId,
    dir,
    discussionPath: discPath,
    tokenStreamPath: join(dir, "token_stream.jsonl"),
    passwordHash: data.password_hash || null,
    expiresAt: data.expires_at ?? null,
    revokedTokenHashes: new Set(data.revoked_token_hashes || []),
    tokenHash,
  };
  byTokenHash.set(tokenHash, entry);
  byDiscussionId.set(discussionId, entry);

  startSubdirWatcher(entry);
  return entry;
}

function refreshEntry(entry) {
  const data = safeReadJSON(entry.discussionPath);
  if (!data) return null;
  const tokenHash = data.token_hash || (data.token ? _hashToken(data.token) : null);
  if (!tokenHash) return null;
  if (tokenHash !== entry.tokenHash) {
    byTokenHash.delete(entry.tokenHash);
    entry.tokenHash = tokenHash;
    byTokenHash.set(tokenHash, entry);
  }
  entry.passwordHash = data.password_hash || null;
  entry.expiresAt = data.expires_at ?? null;
  entry.revokedTokenHashes = new Set(data.revoked_token_hashes || []);
  return data;
}

function unregisterDiscussion(discussionId) {
  const entry = byDiscussionId.get(discussionId);
  if (!entry) return;
  byTokenHash.delete(entry.tokenHash);
  byDiscussionId.delete(discussionId);
  const w = subdirWatchers.get(discussionId);
  if (w) {
    try { w.close(); } catch { /* ignore */ }
    subdirWatchers.delete(discussionId);
  }
  sseClients.delete(discussionId);
  sseDeltaBuffers.delete(discussionId);
  sseLastSeqByToken.delete(discussionId);
  pollWaiters.delete(discussionId);
}

function discoverDiscussions() {
  if (!existsSync(DATA_DIR)) return;
  for (const entry of readdirSync(DATA_DIR, { withFileTypes: true })) {
    if (!entry.isDirectory()) continue;
    registerDiscussion(join(DATA_DIR, entry.name), entry.name);
  }
}

function entryForToken(token) {
  return byTokenHash.get(_hashToken(token)) || null;
}

function readDiscussionFor(entry) {
  if (!entry) return null;
  const data = safeReadJSON(entry.discussionPath);
  if (!data) return null;
  if (data.schema_version === undefined) data.schema_version = 1;
  return data;
}

// ---------------------------------------------------------------------------
// Token + password validation
// ---------------------------------------------------------------------------

function _hashToken(token) {
  if (typeof token !== "string") return "";
  return createHash("sha256").update(token, "utf-8").digest("hex");
}

function _safeStrEqual(a, b) {
  if (typeof a !== "string" || typeof b !== "string") return false;
  const ab = Buffer.from(a, "utf-8");
  const bb = Buffer.from(b, "utf-8");
  if (ab.length !== bb.length) return false;
  return timingSafeEqual(ab, bb);
}

function isTokenValid(token) {
  const entry = entryForToken(token);
  if (!entry) return false;
  const data = readDiscussionFor(entry);
  if (!data) return false;
  const incomingHash = _hashToken(token);
  const storedHash = data.token_hash || (data.token ? _hashToken(data.token) : "");
  if (!_safeStrEqual(storedHash, incomingHash)) return false;
  for (const revokedHash of data.revoked_token_hashes || []) {
    if (_safeStrEqual(revokedHash, incomingHash)) return false;
  }
  if (data.expires_at && Date.now() / 1000 > data.expires_at) return false;
  return true;
}

let _bcrypt = null;
let _bcryptLoadAttempted = false;
async function loadBcrypt() {
  if (_bcrypt || _bcryptLoadAttempted) return _bcrypt;
  _bcryptLoadAttempted = true;
  try {
    _bcrypt = (await import("bcryptjs")).default;
  } catch (err) {
    console.error("[Roundtable Web] bcryptjs not available:", err.message);
  }
  return _bcrypt;
}

function _signSession(token) {
  return createHmac("sha256", SERVER_SECRET).update(`auth:${token}`).digest("hex");
}

function _parseCookies(cookieHeader) {
  const cookies = {};
  if (!cookieHeader) return cookies;
  for (const part of cookieHeader.split(";")) {
    const [k, ...v] = part.trim().split("=");
    if (k) {
      try { cookies[k.trim()] = decodeURIComponent(v.join("=").trim()); }
      catch { cookies[k.trim()] = v.join("=").trim(); }
    }
  }
  return cookies;
}

function isAuthenticated(req, entry) {
  if (!entry.passwordHash) return true;
  const cookies = _parseCookies(req.headers.cookie);
  const sig = cookies[`rt_pw_${entry.tokenHash}`];
  if (!sig) return false;
  return sig === _signSession(entry.tokenHash);
}

// ---------------------------------------------------------------------------
// HTTP helpers
// ---------------------------------------------------------------------------

function sendJSON(res, data, status = 200) {
  res.writeHead(status, {
    "Content-Type": "application/json",
    "Access-Control-Allow-Origin": "*",
  });
  res.end(JSON.stringify(data));
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function escapeHtmlAttr(str) {
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/"/g, "&quot;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

function sendHTML(res, html, status = 200) {
  res.writeHead(status, {
    "Content-Type": "text/html; charset=utf-8",
    "Access-Control-Allow-Origin": "*",
  });
  res.end(html);
}

function send403(res) {
  sendJSON(res, { error: "Access denied or token revoked" }, 403);
}

function sendExpired(res) {
  const html = `<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>链接已过期</title>
  <style>
    *{margin:0;padding:0;box-sizing:border-box}
    body{min-height:100vh;display:flex;align-items:center;justify-content:center;
      font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
      background:#0f172a;color:#e2e8f0}
    .card{max-width:480px;padding:3rem 2.5rem;text-align:center;
      background:#1e293b;border-radius:16px;border:1px solid #334155}
    .icon{font-size:4rem;margin-bottom:1rem}
    h1{font-size:1.5rem;font-weight:600;margin-bottom:.75rem;color:#f1f5f9}
    p{color:#94a3b8;line-height:1.6}
  </style>
</head>
<body>
  <div class="card">
    <div class="icon">⏳</div>
    <h1>此讨论链接已过期</h1>
    <p>该讨论的访问链接已超过有效期，无法继续查看。请联系讨论发起者获取新链接。</p>
  </div>
</body>
</html>`;
  sendHTML(res, html, 410);
}

function send404(res) {
  sendJSON(res, { error: "Not found" }, 404);
}

function sendPasswordPage(res) {
  const html = `<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Roundtable - Access Verification</title>
  <style>
    *{margin:0;padding:0;box-sizing:border-box}
    body{min-height:100vh;display:flex;align-items:center;justify-content:center;
      font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
      background:#0f172a;color:#e2e8f0}
    .card{max-width:420px;width:90%;padding:2.5rem 2rem;text-align:center;
      background:#1e293b;border-radius:16px;border:1px solid #334155;
      box-shadow:0 8px 32px rgba(0,0,0,0.3)}
    .icon{font-size:3rem;margin-bottom:0.8rem}
    h1{font-size:1.3rem;font-weight:600;margin-bottom:0.5rem;color:#f1f5f9}
    p{color:#94a3b8;line-height:1.6;font-size:0.9rem;margin-bottom:1.5rem}
    .input{width:100%;padding:12px 16px;border:1px solid #475569;border-radius:10px;
      background:#0f172a;color:#e2e8f0;font-size:15px;outline:none;
      transition:border-color 0.2s}
    .input:focus{border-color:#60a5fa}
    .btn{width:100%;padding:12px;margin-top:12px;border:none;border-radius:10px;
      background:linear-gradient(135deg,#3b82f6,#6366f1);color:#fff;
      font-size:15px;font-weight:600;cursor:pointer;transition:opacity 0.2s}
    .btn:hover{opacity:0.9}
    .btn:disabled{opacity:0.5;cursor:not-allowed}
    .error{color:#f87171;font-size:13px;margin-top:8px;min-height:20px}
    .brand{margin-top:1.5rem;color:#64748b;font-size:12px}
  </style>
</head>
<body>
  <div class="card">
    <div class="icon">🔒</div>
    <h1>Access Verification</h1>
    <p>This discussion requires a password to view</p>
    <form id="pwForm">
      <input class="input" type="password" id="pwInput" placeholder="Enter access password" autofocus autocomplete="off">
      <button class="btn" type="submit" id="pwBtn">Enter</button>
      <div class="error" id="pwError"></div>
    </form>
    <div class="brand">Roundtable AI</div>
  </div>
  <script>
    const TOKEN = window.location.pathname.split('/').pop();
    document.getElementById('pwForm').addEventListener('submit', async (e) => {
      e.preventDefault();
      const pw = document.getElementById('pwInput').value.trim();
      if (!pw) { document.getElementById('pwError').textContent = 'Please enter a password'; return; }
      const btn = document.getElementById('pwBtn');
      btn.disabled = true; btn.textContent = 'Verifying...';
      try {
        const resp = await fetch('/api/' + TOKEN + '/validate-password', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ password: pw })
        });
        const data = await resp.json();
        if (data.ok) {
          window.location.reload();
        } else {
          document.getElementById('pwError').textContent = 'Incorrect password, please try again';
          btn.disabled = false; btn.textContent = 'Enter';
        }
      } catch {
        document.getElementById('pwError').textContent = 'Network error';
        btn.disabled = false; btn.textContent = 'Enter';
      }
    });
  </script>
</body>
</html>`;
  sendHTML(res, html);
}

function safeDiscussion(data) {
  const safe = { ...data };
  delete safe.token;
  delete safe.token_hash;
  delete safe.revoked_token_hashes;
  delete safe.password_hash;
  return safe;
}

// ---------------------------------------------------------------------------
// SSE + long-poll state
// ---------------------------------------------------------------------------

/** @type {Map<string, Set<import("http").ServerResponse>>} */
const sseClients = new Map();
const sseDeltaBuffers = new Map();
const sseLastSeqByToken = new Map();
const pollWaiters = new Map();
let lastUpdatedTimestamp = 0;

function broadcastToSSE(token, event, data) {
  const clients = sseClients.get(token);
  if (!clients || clients.size === 0) return;

  const payload = `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`;
  for (const res of clients) {
    try {
      res.write(payload);
    } catch {
      clients.delete(res);
    }
  }
}

function queueSSEDelta(token, eventData) {
  if (!token || !eventData) return;
  const clients = sseClients.get(token);
  if (!clients || clients.size === 0) return;

  let buffer = sseDeltaBuffers.get(token);
  if (!buffer) {
    buffer = { events: [], timer: null };
    sseDeltaBuffers.set(token, buffer);
  }
  buffer.events.push(eventData);

  if (buffer.timer) return;
  buffer.timer = setTimeout(() => {
    const pending = buffer.events.splice(0, buffer.events.length);
    buffer.timer = null;
    if (pending.length === 0) return;
    broadcastToSSE(token, "delta", { events: pending });
  }, 50);
}

function streamEventsSince(data, previousSeq) {
  const events = Array.isArray(data?.stream?.events) ? data.stream.events : [];
  const nextEvents = events.filter((eventData) => {
    const seq = Number(eventData?.seq ?? -1);
    return Number.isFinite(seq) && seq > previousSeq;
  });
  if (nextEvents.length > 0) return nextEvents;

  const latest = data?.latest_event;
  const latestSeq = Number(latest?.seq ?? -1);
  if (latest && Number.isFinite(latestSeq) && latestSeq > previousSeq) {
    return [latest];
  }
  return [];
}

function notifyPollWaiters(token) {
  const waiters = pollWaiters.get(token);
  if (!waiters) return;
  const entry = entryForToken(token);
  for (const waiter of [...waiters]) {
    clearTimeout(waiter.timer);
    const data = entry ? readDiscussionFor(entry) : null;
    if (data) {
      sendJSON(waiter.res, safeDiscussion(data));
    } else {
      sendJSON(waiter.res, { error: "Data not available" }, 500);
    }
    waiters.delete(waiter);
  }
}

// ---------------------------------------------------------------------------
// Markdown export (shared between MD and PDF routes)
// ---------------------------------------------------------------------------

function buildMarkdown(data) {
  const topic = data.topic || "Discussion";
  const participants = data.participants || [];
  const speeches = data.speeches || [];
  const roundSummaries = data.round_summaries || [];
  const finalSummary = data.final_summary;
  const conclusion = data.conclusion;

  let md = `# ${topic}\n\n`;

  if (participants.length > 0) {
    md += `## Participants\n\n`;
    for (const p of participants) {
      const name = p.display_name || p.profile || p.name || p.id || "";
      const role = p.role || "";
      md += role ? `- **${name}** (${role})\n` : `- **${name}**\n`;
    }
    md += "\n";
  }

  const rounds = new Map();
  for (const s of speeches) {
    const r = s.round || 0;
    if (!rounds.has(r)) rounds.set(r, []);
    rounds.get(r).push(s);
  }

  const sortedRounds = [...rounds.keys()].sort((a, b) => a - b);
  for (const r of sortedRounds) {
    md += r === 0 ? `## Opening (Round 0)\n\n` : `## Round ${r}\n\n`;
    for (const s of rounds.get(r)) {
      const speaker = s.display_name || s.participant || "Unknown";
      md += `### ${speaker}\n\n`;
      md += `${s.content || ""}\n\n`;
    }
  }

  if (roundSummaries.length > 0) {
    md += `## Round Summaries\n\n`;
    for (const rs of roundSummaries) {
      md += `### Round ${rs.round || "?"}\n\n`;
      const consensus = rs.consensus || rs.consensus_points || [];
      const disagreement = rs.disagreement || rs.disagreement_points || [];
      if (consensus.length > 0) {
        md += `**Consensus:**\n`;
        for (const c of consensus) {
          const text = typeof c === "string" ? c : c.point || c.text || JSON.stringify(c);
          md += `- ${text}\n`;
        }
        md += "\n";
      }
      if (disagreement.length > 0) {
        md += `**Disagreement:**\n`;
        for (const d of disagreement) {
          const text = typeof d === "string" ? d : d.point || d.text || JSON.stringify(d);
          md += `- ${text}\n`;
        }
        md += "\n";
      }
      if (rs.convergence_score !== undefined) {
        md += `*Convergence: ${Math.round(rs.convergence_score * 100)}%*\n\n`;
      }
    }
  }

  if (finalSummary) {
    md += `## Final Summary\n\n`;
    const fsConsensus = finalSummary.consensus || finalSummary.consensus_points || [];
    const fsDisagreement = finalSummary.disagreement || finalSummary.disagreement_points || [];
    if (fsConsensus.length > 0) {
      md += `### Consensus\n`;
      for (const c of fsConsensus) {
        const text = typeof c === "string" ? c : c.point || c.text || JSON.stringify(c);
        md += `- ${text}\n`;
      }
      md += "\n";
    }
    if (fsDisagreement.length > 0) {
      md += `### Disagreement\n`;
      for (const d of fsDisagreement) {
        const text = typeof d === "string" ? d : d.point || d.text || JSON.stringify(d);
        md += `- ${text}\n`;
      }
      md += "\n";
    }
    if (finalSummary.verdict) {
      md += `### Verdict\n\n${finalSummary.verdict}\n\n`;
    }
  }

  if (conclusion) {
    md += `## Conclusion\n\n${conclusion}\n\n`;
  }

  md += `---\n\n*Generated by Roundtable AI*\n`;
  return md;
}

function safeFilename(topic) {
  return topic.replace(/[^a-zA-Z0-9一-鿿_-]/g, "_").slice(0, 60) || "discussion";
}

// ---------------------------------------------------------------------------
// Mini router (used as fallback when express isn't available, and as the
// canonical route source — express main() bridges to these handlers)
// ---------------------------------------------------------------------------

class MiniRouter {
  constructor() {
    this._routes = [];
  }

  get(path, ...handlers) {
    this._routes.push({ method: "GET", path, handlers });
  }
  post(path, ...handlers) {
    this._routes.push({ method: "POST", path, handlers });
  }

  match(method, urlPath) {
    for (const route of this._routes) {
      if (route.method !== method) continue;
      const params = this._matchPath(route.path, urlPath);
      if (params !== null) {
        return { route, params };
      }
    }
    return null;
  }

  _matchPath(pattern, urlPath) {
    const parts = pattern.split("/");
    const urlParts = urlPath.split("/");
    if (parts.length !== urlParts.length) return null;
    const params = {};
    for (let i = 0; i < parts.length; i++) {
      if (parts[i].startsWith(":")) {
        params[parts[i].slice(1)] = decodeURIComponent(urlParts[i]);
      } else if (parts[i] !== urlParts[i]) {
        return null;
      }
    }
    return params;
  }
}

const router = new MiniRouter();

// ---------------------------------------------------------------------------
// Routes
// ---------------------------------------------------------------------------

router.get("/share/:token", (req, res, params) => {
  const entry = entryForToken(params.token);
  if (!entry) return send403(res);
  if (entry.expiresAt && Date.now() / 1000 > entry.expiresAt) return sendExpired(res);
  if (!isTokenValid(params.token)) return send403(res);

  const disc = readDiscussionFor(entry);
  if (!disc) return send404(res);

  const templatePath = join(WEB_DIR, "share.html");
  if (!existsSync(templatePath)) {
    return sendHTML(res, "<h1>Share page template not found</h1>");
  }

  try {
    let html = readFileSync(templatePath, "utf-8");
    const participants = disc.participants || [];
    const topic = disc.topic || "圆桌讨论";
    const status = disc.status || "ongoing";
    const rounds = disc.round_summaries?.length || 0;
    const speeches = disc.speeches || [];
    const finalScore = disc.final_summary?.convergence_score;
    const lastRoundScore = disc.round_summaries?.length
      ? disc.round_summaries[disc.round_summaries.length - 1]?.convergence_score
      : null;
    const score = finalScore ?? lastRoundScore ?? null;
    const consensus = score != null ? Math.round(score * 100) : null;
    const agentColors = ["#58a6ff", "#3fb950", "#d29922", "#bc8cff", "#f85149", "#f0883e", "#a5d6ff", "#7ee787"];

    const ogTitle = `圆桌讨论: ${topic}`;
    const participantNames = participants.map(p => p.display_name || p.profile || p.id).filter(Boolean).join("、");
    const ogDesc = `多位 AI Agent 正在围绕「${topic}」展开圆桌讨论${participantNames ? `。参与者: ${participantNames}` : ""}`;

    const statusClass = status === "concluded" ? "completed" : "ongoing";
    const statusLabel = status === "concluded" ? "已结束" : "进行中";

    const metaParts = [];
    if (participants.length) metaParts.push(`${participants.length} 位参与者`);
    if (rounds > 0) metaParts.push(`${rounds} 轮讨论`);
    const metaText = metaParts.join(" · ") || "多 Agent 圆桌讨论";

    const participantsHtml = participants.map((p, i) => {
      const name = p.display_name || p.profile || p.id || `Agent ${i + 1}`;
      const color = agentColors[i % agentColors.length];
      return `<span class="participant-chip"><span class="dot" style="background:${color}"></span>${escapeHtmlAttr(name)}</span>`;
    }).join("");

    let statsHtml = "";
    if (rounds > 0 || speeches.length > 0) {
      statsHtml = `<div class="rounds-info">
        ${rounds > 0 ? `<div class="stat"><span class="val">${rounds}</span><span class="lbl">讨论轮次</span></div>` : ""}
        ${speeches.length > 0 ? `<div class="stat"><span class="val">${speeches.length}</span><span class="lbl">发言数</span></div>` : ""}
        ${participants.length > 0 ? `<div class="stat"><span class="val">${participants.length}</span><span class="lbl">参与者</span></div>` : ""}
      </div>`;
    }

    let consensusHtml = "";
    if (consensus != null) {
      const level = consensus >= 70 ? "high" : consensus >= 40 ? "medium" : "low";
      consensusHtml = `<div class="consensus-bar">
        <div class="label">共识度</div>
        <div class="consensus-track"><div class="consensus-fill ${level}" style="width:${consensus}%"></div></div>
        <div class="consensus-value">${consensus}%</div>
      </div>`;
    }

    const previewSpeeches = speeches.slice(0, 3);
    const messagesHtml = previewSpeeches.length > 0
      ? previewSpeeches.map((s, i) => {
          const agentName = s.display_name || s.participant || `Agent ${i + 1}`;
          const text = (s.content || "").slice(0, 200);
          const color = agentColors[i % agentColors.length];
          return `<div class="preview-msg">
            <div class="agent" style="color:${color}">${escapeHtmlAttr(agentName)}</div>
            <div class="text">${escapeHtmlAttr(text)}</div>
          </div>`;
        }).join("")
      : '<div class="preview-msg"><div class="text" style="color:var(--muted)">讨论即将开始...</div></div>';

    const viewerUrl = `/r/${params.token}`;
    const shareUrl = `/share/${params.token}`;

    html = html
      .replace(/\{\{ogTitle\}\}/g, escapeHtmlAttr(ogTitle))
      .replace(/\{\{ogDesc\}\}/g, escapeHtmlAttr(ogDesc))
      .replace(/\{\{shareUrl\}\}/g, shareUrl)
      .replace(/\{\{topic\}\}/g, escapeHtmlAttr(topic))
      .replace(/\{\{statusClass\}\}/g, statusClass)
      .replace(/\{\{statusLabel\}\}/g, statusLabel)
      .replace(/\{\{metaText\}\}/g, metaText)
      .replace(/\{\{participantsHtml\}\}/g, participantsHtml)
      .replace(/\{\{statsHtml\}\}/g, statsHtml)
      .replace(/\{\{consensusHtml\}\}/g, consensusHtml)
      .replace(/\{\{messagesHtml\}\}/g, messagesHtml)
      .replace(/\{\{viewerUrl\}\}/g, viewerUrl);

    sendHTML(res, html);
  } catch (err) {
    sendHTML(res, `<h1>Error</h1><pre>${err.message}</pre>`);
  }
});

// ---------------------------------------------------------------------------
// Shared HTML viewer renderer (used by /r/:token and /embed/:token)
// ---------------------------------------------------------------------------
function renderViewer(req, res, entry, token, opts) {
  const { templateName, embed } = opts;
  const templatePath = join(WEB_DIR, templateName);
  try {
    if (!existsSync(templatePath)) {
      return sendHTML(res, `<h1>Roundtable Web Viewer</h1><p>${templateName} not found</p>`);
    }
    const html = readFileSync(templatePath, "utf-8");
    const config = JSON.stringify({
      token,
      port,
      host: "0.0.0.0",
      hasPassword: !!entry.passwordHash,
      embed: !!embed,
    });
    const disc = readDiscussionFor(entry);
    const ogTitle = disc?.topic ? `圆桌讨论: ${disc.topic}` : "Roundtable 圆桌讨论";
    const participantNames = (disc?.participants || []).map(p => p.display_name || p.profile).filter(Boolean).join("、");
    const ogDesc = disc?.topic
      ? `多位 AI Agent 正在围绕「${disc.topic}」展开圆桌讨论。${participantNames ? `参与者: ${participantNames}` : ""}`
      : "多 Agent 圆桌讨论引擎 — 让多个 AI Agent 像开会一样讨论、追踪共识分歧并生成结构化会议记录。";
    const ogTags = [
      `<meta property="og:title" content="${escapeHtmlAttr(ogTitle)}">`,
      `<meta property="og:description" content="${escapeHtmlAttr(ogDesc)}">`,
      `<meta property="og:type" content="article">`,
      `<meta property="og:site_name" content="Roundtable">`,
      `<meta name="twitter:card" content="summary">`,
      `<meta name="twitter:title" content="${escapeHtmlAttr(ogTitle)}">`,
      `<meta name="twitter:description" content="${escapeHtmlAttr(ogDesc)}">`,
    ].join("\n    ");

    const injected = html.replace(
      "</head>",
      `${ogTags}\n    <script>window.__RT_CONFIG__ = ${config};</script></head>`
    );

    // Embed responses must explicitly allow framing across origins.
    // We intentionally do NOT set X-Frame-Options (which is single-origin only)
    // and instead use a permissive frame-ancestors CSP.
    const headers = {
      "Content-Type": "text/html; charset=utf-8",
      "Access-Control-Allow-Origin": "*",
    };
    if (embed) {
      headers["Content-Security-Policy"] = "frame-ancestors *";
      headers["X-Roundtable-Embed"] = "1";
    }
    res.writeHead(200, headers);
    res.end(injected);
  } catch (err) {
    sendHTML(res, `<h1>Error</h1><pre>${err.message}</pre>`);
  }
}

router.get("/r/:token", async (req, res, params) => {
  const entry = entryForToken(params.token);
  if (entry && entry.expiresAt && Date.now() / 1000 > entry.expiresAt) return sendExpired(res);
  if (!entry || !isTokenValid(params.token)) return send403(res);

  if (entry.passwordHash) {
    await loadBcrypt();
    if (!isAuthenticated(req, entry)) return sendPasswordPage(res);
  }

  renderViewer(req, res, entry, params.token, { templateName: "index.html", embed: false });
});

router.get("/embed/:token", async (req, res, params) => {
  const entry = entryForToken(params.token);
  if (entry && entry.expiresAt && Date.now() / 1000 > entry.expiresAt) return sendExpired(res);
  if (!entry || !isTokenValid(params.token)) return send403(res);

  // Password-protected discussions cannot be embedded — embedding contexts have
  // no good way to surface a password prompt and it leaks UX onto the host page.
  // Surface a clean "open in new tab" hint instead.
  if (entry.passwordHash) {
    await loadBcrypt();
    if (!isAuthenticated(req, entry)) {
      const url = `/r/${encodeURIComponent(params.token)}`;
      const html = `<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>需要在新标签页打开</title>
  <style>
    *{margin:0;padding:0;box-sizing:border-box}
    body{min-height:100vh;display:flex;align-items:center;justify-content:center;
      font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
      background:#0f172a;color:#e2e8f0;padding:1rem}
    .card{max-width:420px;padding:2rem;text-align:center;
      background:#1e293b;border-radius:14px;border:1px solid #334155}
    h1{font-size:1.1rem;font-weight:600;margin-bottom:.5rem;color:#f1f5f9}
    p{color:#94a3b8;line-height:1.6;font-size:.9rem;margin-bottom:1.25rem}
    a{display:inline-block;padding:10px 20px;border-radius:10px;
      background:linear-gradient(135deg,#3b82f6,#6366f1);color:#fff;
      text-decoration:none;font-weight:600;font-size:.9rem}
  </style>
</head>
<body>
  <div class="card">
    <h1>🔒 此讨论受密码保护</h1>
    <p>受密码保护的讨论无法在嵌入视图中查看，请在新标签页中打开后输入密码。</p>
    <a href="${escapeHtmlAttr(url)}" target="_blank" rel="noopener">在新标签页打开</a>
  </div>
</body>
</html>`;
      res.writeHead(200, {
        "Content-Type": "text/html; charset=utf-8",
        "Content-Security-Policy": "frame-ancestors *",
      });
      return res.end(html);
    }
  }

  renderViewer(req, res, entry, params.token, { templateName: "embed.html", embed: true });
});

router.get("/api/:token/data", async (req, res, params) => {
  const entry = entryForToken(params.token);
  if (!entry || !isTokenValid(params.token)) return send403(res);
  if (entry.passwordHash) {
    await loadBcrypt();
    if (!isAuthenticated(req, entry)) return sendJSON(res, { error: "Password required" }, 401);
  }

  const data = readDiscussionFor(entry);
  if (!data) return sendJSON(res, { error: "Discussion not found" }, 404);
  sendJSON(res, safeDiscussion(data));
});

router.get("/api/:token/events", async (req, res, params) => {
  const entry = entryForToken(params.token);
  if (!entry || !isTokenValid(params.token)) return send403(res);
  if (entry.passwordHash) {
    await loadBcrypt();
    if (!isAuthenticated(req, entry)) return sendJSON(res, { error: "Password required" }, 401);
  }

  res.writeHead(200, {
    "Content-Type": "text/event-stream",
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "Access-Control-Allow-Origin": "*",
    "X-Accel-Buffering": "no",
  });

  const data = readDiscussionFor(entry);
  if (data) {
    const currentSeq = Number(data?.stream?.seq ?? 0);
    if (Number.isFinite(currentSeq)) sseLastSeqByToken.set(entry.discussionId, currentSeq);
    res.write(`event: init\ndata: ${JSON.stringify(safeDiscussion(data))}\n\n`);
    if (typeof res.flushHeaders === "function") res.flushHeaders();
  }

  if (!sseClients.has(entry.discussionId)) {
    sseClients.set(entry.discussionId, new Set());
  }
  sseClients.get(entry.discussionId).add(res);

  const keepAlive = setInterval(() => {
    try {
      res.write(": keepalive\n\n");
    } catch {
      clearInterval(keepAlive);
    }
  }, 30000);

  req.on("close", () => {
    clearInterval(keepAlive);
    const clients = sseClients.get(entry.discussionId);
    if (clients) clients.delete(res);
  });
});

router.get("/api/:token/poll", async (req, res, params) => {
  const entry = entryForToken(params.token);
  if (!entry || !isTokenValid(params.token)) return send403(res);
  if (entry.passwordHash) {
    await loadBcrypt();
    if (!isAuthenticated(req, entry)) return sendJSON(res, { error: "Password required" }, 401);
  }

  const url = new URL(req.url, `http://${req.headers.host}`);
  const since = parseInt(url.searchParams.get("since") || "0", 10) || 0;

  const data = readDiscussionFor(entry);
  if (data && data.updated_at > since) {
    return sendJSON(res, safeDiscussion(data));
  }

  if (!pollWaiters.has(entry.discussionId)) {
    pollWaiters.set(entry.discussionId, new Set());
  }

  const timer = setTimeout(() => {
    const latest = readDiscussionFor(entry);
    if (latest) {
      sendJSON(res, safeDiscussion(latest));
    } else {
      sendJSON(res, { updated_at: since });
    }
    pollWaiters.get(entry.discussionId)?.delete(waiter);
  }, 25000);

  const waiter = { res, since, timer };
  pollWaiters.get(entry.discussionId).add(waiter);
});

router.post("/api/:token/share", (req, res, params) => {
  if (!isTokenValid(params.token)) return send403(res);
  sendJSON(res, { ok: true, share_url: `/share/${params.token}` });
});

router.post("/api/:token/revoke", (req, res, params) => {
  const entry = entryForToken(params.token);
  if (!entry || !isTokenValid(params.token)) return send403(res);

  const data = readDiscussionFor(entry);
  if (!data) return sendJSON(res, { error: "Discussion not found" }, 404);

  const incomingHash = _hashToken(params.token);
  if (!data.revoked_token_hashes) data.revoked_token_hashes = [];
  if (!data.revoked_token_hashes.includes(incomingHash)) {
    data.revoked_token_hashes.push(incomingHash);
  }
  data.updated_at = Math.floor(Date.now() / 1000);

  const tmpPath = entry.discussionPath + ".tmp";
  writeFileSync(tmpPath, JSON.stringify(data, null, 2));
  renameSync(tmpPath, entry.discussionPath);

  entry.revokedTokenHashes.add(incomingHash);
  broadcastToSSE(entry.discussionId, "revoked", { revoked: true });

  sendJSON(res, { ok: true, revoked: true });
});

router.post("/api/:token/validate-password", async (req, res, params) => {
  const entry = entryForToken(params.token);
  if (!entry) return send403(res);
  if (!entry.passwordHash) return sendJSON(res, { ok: true, noPassword: true });

  const bcrypt = await loadBcrypt();
  if (!bcrypt) return sendJSON(res, { ok: false, error: "Password verification unavailable" }, 500);

  let body = "";
  for await (const chunk of req) body += chunk;
  try {
    const { password } = JSON.parse(body);
    if (!password) return sendJSON(res, { ok: false, error: "Password required" }, 400);

    const match = await bcrypt.compare(password, entry.passwordHash);
    if (match) {
      const sig = _signSession(entry.tokenHash);
      res.setHeader(
        "Set-Cookie",
        `rt_pw_${entry.tokenHash}=${sig}; Path=/; HttpOnly; SameSite=Lax; Max-Age=${7 * 24 * 3600}`
      );
      return sendJSON(res, { ok: true });
    }
    return sendJSON(res, { ok: false, error: "Incorrect password" }, 401);
  } catch {
    return sendJSON(res, { ok: false, error: "Invalid request" }, 400);
  }
});

router.get("/api/:token/export/markdown", async (req, res, params) => {
  const entry = entryForToken(params.token);
  if (!entry || !isTokenValid(params.token)) return send403(res);
  if (entry.passwordHash) {
    await loadBcrypt();
    if (!isAuthenticated(req, entry)) return sendJSON(res, { error: "Password required" }, 401);
  }

  const data = readDiscussionFor(entry);
  if (!data) return sendJSON(res, { error: "Discussion not found" }, 404);

  const md = buildMarkdown(data);
  const filename = safeFilename(data.topic || "Discussion");
  res.writeHead(200, {
    "Content-Type": "text/markdown; charset=utf-8",
    "Content-Disposition": `attachment; filename="${filename}.md"`,
    "Access-Control-Allow-Origin": "*",
  });
  res.end(md);
});

router.get("/api/:token/export/pdf", async (req, res, params) => {
  const entry = entryForToken(params.token);
  if (!entry || !isTokenValid(params.token)) return send403(res);
  if (entry.passwordHash) {
    await loadBcrypt();
    if (!isAuthenticated(req, entry)) return sendJSON(res, { error: "Password required" }, 401);
  }

  const data = readDiscussionFor(entry);
  if (!data) return sendJSON(res, { error: "Discussion not found" }, 404);

  const { spawn } = await import("node:child_process");
  const md = buildMarkdown(data);
  const filename = safeFilename(data.topic || "Discussion");
  const tmpMdPath = resolve(entry.dir, `.${filename}.tmp.md`);
  const expectedPdfPath = tmpMdPath.replace(/\.md$/, ".pdf");

  let child = null;
  let clientClosed = false;
  req.on("close", () => {
    clientClosed = true;
    if (child) {
      try { child.kill("SIGTERM"); } catch { /* ignore */ }
    }
  });

  try {
    writeFileSync(tmpMdPath, md, "utf-8");

    const pdfOk = await new Promise((resolveP, rejectP) => {
      let stderr = "";
      child = spawn("npx", ["--no-install", "md-to-pdf", basename(tmpMdPath)], {
        cwd: dirname(tmpMdPath),
        env: { ...process.env },
        stdio: ["pipe", "pipe", "pipe"],
      });
      child.stdin.end();
      child.stderr?.on("data", (d) => { stderr += d.toString(); });
      child.on("close", (code) => {
        if (code === 0) resolveP(true);
        else rejectP(new Error(`md-to-pdf exited with code ${code}: ${stderr.slice(0, 500)}`));
      });
      child.on("error", rejectP);
    });

    if (clientClosed) return;

    if (pdfOk && existsSync(expectedPdfPath)) {
      const pdfBuffer = readFileSync(expectedPdfPath);
      res.writeHead(200, {
        "Content-Type": "application/pdf",
        "Content-Disposition": `attachment; filename="${filename}.pdf"`,
        "Content-Length": pdfBuffer.length,
        "Access-Control-Allow-Origin": "*",
      });
      res.end(pdfBuffer);
    } else {
      sendJSON(res, { error: "PDF generation failed — output not found" }, 500);
    }
  } catch (err) {
    if (!clientClosed) {
      console.error("[export/pdf] Error:", err.message);
      sendJSON(res, { error: "PDF generation failed", detail: err.message }, 500);
    }
  } finally {
    try { unlinkSync(tmpMdPath); } catch { /* ignore */ }
    try { unlinkSync(expectedPdfPath); } catch { /* ignore */ }
  }
});

// ---------------------------------------------------------------------------
// Static assets (shared across all discussions)
// ---------------------------------------------------------------------------

function staticHandler(filename, contentType) {
  return (req, res) => {
    const path = join(WEB_DIR, filename);
    if (existsSync(path)) {
      const content = readFileSync(path, "utf-8");
      res.writeHead(200, { "Content-Type": contentType });
      res.end(content);
    } else {
      res.writeHead(404);
      res.end(`/* ${filename} not found */`);
    }
  };
}

router.get("/theme.css", staticHandler("theme.css", "text/css"));
router.get("/viewer.css", staticHandler("viewer.css", "text/css"));
router.get("/i18n.js", staticHandler("i18n.js", "application/javascript"));
router.get("/viewer.js", staticHandler("viewer.js", "application/javascript"));

// ---------------------------------------------------------------------------
// Replay API
// ---------------------------------------------------------------------------

async function readTokenStream(path) {
  const events = [];
  if (!existsSync(path)) return events;

  return new Promise((resolveP, rejectP) => {
    const rl = readline.createInterface({
      input: createReadStream(path, { encoding: "utf-8" }),
      crlfDelay: Infinity,
    });
    rl.on("line", (line) => {
      const trimmed = line.trim();
      if (!trimmed) return;
      try {
        events.push(JSON.parse(trimmed));
      } catch { /* skip malformed lines */ }
    });
    rl.on("close", () => resolveP(events));
    rl.on("error", rejectP);
  });
}

function buildReplayMeta(events) {
  if (events.length === 0) {
    return { totalEvents: 0, duration: 0, startTime: 0, endTime: 0, rounds: [], agents: [] };
  }

  const startTime = events[0].timestamp || events[0].created_at || 0;
  const endTime = events[events.length - 1].timestamp || events[events.length - 1].created_at || 0;
  const duration = endTime - startTime;

  const roundBoundaries = [];
  const seenRounds = new Set();
  const agents = new Map();

  for (const ev of events) {
    const evTime = ev.timestamp || ev.created_at || 0;
    const round = ev.round ?? ev.payload?.speech?.round ?? ev.speech?.round;
    if (round != null && !seenRounds.has(round)) {
      seenRounds.add(round);
      roundBoundaries.push({
        round: Number(round),
        startTs: evTime,
        offsetMs: (evTime - startTime) * 1000,
      });
    }

    const agentId = ev.agent ?? ev.agent_id ?? ev.payload?.speech?.agent_id ?? ev.speech?.agent_id ?? ev.payload?.speech?.participant ?? ev.speech?.participant;
    const agentName = ev.display_name ?? ev.agent_name ?? ev.payload?.speech?.agent_name ?? ev.speech?.agent_name ?? ev.payload?.speech?.display_name ?? ev.speech?.display_name;
    if (agentId && !agents.has(agentId)) {
      agents.set(agentId, { id: agentId, name: agentName || agentId });
    }
  }

  roundBoundaries.sort((a, b) => a.round - b.round);

  return {
    totalEvents: events.length,
    duration: duration * 1000,
    startTime,
    endTime,
    rounds: roundBoundaries,
    agents: Array.from(agents.values()),
  };
}

router.get("/api/:token/replay/meta", async (req, res, params) => {
  const entry = entryForToken(params.token);
  if (!entry || !isTokenValid(params.token)) return send403(res);

  try {
    const events = await readTokenStream(entry.tokenStreamPath);
    const meta = buildReplayMeta(events);
    sendJSON(res, { ok: true, ...meta });
  } catch (err) {
    sendJSON(res, { error: "Failed to read replay data", detail: String(err) }, 500);
  }
});

router.get("/api/:token/replay/stream", async (req, res, params) => {
  const entry = entryForToken(params.token);
  if (!entry || !isTokenValid(params.token)) return send403(res);

  let speedVal, fromVal;
  if (req.query) {
    speedVal = req.query.speed;
    fromVal = req.query.from;
  } else {
    try {
      const url = new URL(req.url, `http://${req.headers.host || "localhost"}`);
      speedVal = url.searchParams.get("speed");
      fromVal = url.searchParams.get("from");
    } catch {
      speedVal = null;
      fromVal = null;
    }
  }
  const speed = Math.max(0, parseFloat(speedVal) || 1);
  const fromMs = Math.max(0, parseInt(fromVal, 10) || 0);

  let events;
  try {
    events = await readTokenStream(entry.tokenStreamPath);
  } catch {
    return sendJSON(res, { error: "Failed to read replay data" }, 500);
  }

  if (events.length === 0) {
    return sendJSON(res, { error: "No replay data available" }, 404);
  }

  res.writeHead(200, {
    "Content-Type": "text/event-stream",
    "Cache-Control": "no-cache, no-transform",
    Connection: "keep-alive",
    "X-Accel-Buffering": "no",
  });

  const meta = buildReplayMeta(events);
  res.write(`event: replay_meta\ndata: ${JSON.stringify(meta)}\n\n`);

  const startTime = events[0].timestamp || events[0].created_at || 0;
  const startOffsetSec = fromMs / 1000;

  const filteredEvents = events.filter((ev) => {
    const offsetSec = (ev.timestamp || ev.created_at || 0) - startTime;
    return offsetSec >= startOffsetSec;
  });

  let closed = false;
  req.on("close", () => { closed = true; });

  if (speed === 0) {
    for (const ev of filteredEvents) {
      if (closed) break;
      const offsetMs = ((ev.timestamp || ev.created_at || 0) - startTime) * 1000;
      res.write(`event: replay_event\ndata: ${JSON.stringify({ ...ev, _offsetMs: offsetMs })}\n\n`);
    }
    if (!closed) {
      res.write(`event: replay_end\ndata: ${JSON.stringify({ totalEvents: filteredEvents.length })}\n\n`);
      res.end();
    }
    return;
  }

  for (let i = 0; i < filteredEvents.length; i++) {
    if (closed) break;

    const ev = filteredEvents[i];
    const eventTime = (ev.timestamp || ev.created_at || 0) - startTime;
    const delayMs = Math.max(0, (eventTime - startOffsetSec) * 1000 / speed);

    const progress = {
      currentMs: eventTime * 1000,
      totalMs: meta.duration,
      eventIndex: i,
      totalEvents: filteredEvents.length,
    };

    await sleep(delayMs);
    if (closed) break;

    res.write(`event: replay_progress\ndata: ${JSON.stringify(progress)}\n\n`);
    res.write(`event: replay_event\ndata: ${JSON.stringify(ev)}\n\n`);

    if (i < filteredEvents.length - 1) {
      const nextTime = (filteredEvents[i + 1].timestamp || filteredEvents[i + 1].created_at || 0) - startTime;
      const interDelay = Math.max(0, (nextTime - eventTime) * 1000 / speed);
      const cappedDelay = Math.min(interDelay, 5000);
      if (cappedDelay > 0) await sleep(cappedDelay);
      if (closed) break;
    }
  }

  if (!closed) {
    res.write(`event: replay_end\ndata: ${JSON.stringify({ totalEvents: filteredEvents.length })}\n\n`);
    res.end();
  }
});

// ---------------------------------------------------------------------------
// File watchers
// ---------------------------------------------------------------------------

function startSubdirWatcher(entry) {
  if (subdirWatchers.has(entry.discussionId)) return;
  let debounceTimer = null;
  const w = watch(entry.dir, (_eventType, changedFilename) => {
    if (changedFilename !== "discussion.json") return;
    clearTimeout(debounceTimer);
    debounceTimer = setTimeout(() => {
      if (!existsSync(entry.discussionPath)) {
        unregisterDiscussion(entry.discussionId);
        return;
      }
      const data = refreshEntry(entry);
      if (!data) return;

      const safe = safeDiscussion(data);
      lastUpdatedTimestamp = data.updated_at || Date.now();
      const previousSeq = sseLastSeqByToken.get(entry.discussionId) ?? 0;
      const deltaEvents = streamEventsSince(data, previousSeq);
      const latestSeq = Number(data?.stream?.seq ?? previousSeq);
      if (Number.isFinite(latestSeq)) sseLastSeqByToken.set(entry.discussionId, Math.max(previousSeq, latestSeq));
      for (const eventData of deltaEvents) queueSSEDelta(entry.discussionId, eventData);
      broadcastToSSE(entry.discussionId, "update", safe);
      notifyPollWaiters(entry.discussionId);
    }, 50);
  });
  subdirWatchers.set(entry.discussionId, w);
}

function startDataDirWatcher() {
  watch(DATA_DIR, (_eventType, filename) => {
    if (!filename) return;
    if (byDiscussionId.has(filename)) return;
    const candidatePath = join(DATA_DIR, filename);
    setTimeout(() => {
      try {
        if (!existsSync(candidatePath)) return;
        if (!statSync(candidatePath).isDirectory()) return;
        if (!existsSync(join(candidatePath, "discussion.json"))) return;
        registerDiscussion(candidatePath, filename);
      } catch { /* ignore transient races */ }
    }, 100);
  });
}

// ---------------------------------------------------------------------------
// HTTP server bootstrap
// ---------------------------------------------------------------------------

async function loadExpress() {
  try {
    const express = (await import("express")).default;
    return express();
  } catch {
    return null;
  }
}

function bridge(app) {
  for (const route of router._routes) {
    const handler = (req, res) => {
      const params = route.path.includes(":")
        ? router._matchPath(route.path, req.path) ?? {}
        : {};
      route.handlers[0](req, res, params);
    };
    app[route.method.toLowerCase()](route.path, handler);
  }
}

async function main() {
  mkdirSync(DATA_DIR, { recursive: true });
  discoverDiscussions();

  const app = await loadExpress();

  if (app) {
    bridge(app);
    app.listen(port, "0.0.0.0", () => {
      console.log(`[Roundtable Web] Listening on http://0.0.0.0:${port} (data-dir=${DATA_DIR})`);
      console.log(`[Roundtable Web] Discovered ${byDiscussionId.size} existing discussion(s)`);
      startDataDirWatcher();
    });
  } else {
    const server = createServer((req, res) => {
      const url = new URL(req.url, `http://${req.headers.host}`);
      const method = req.method.toUpperCase();
      const match = router.match(method, url.pathname);
      if (match) {
        match.route.handlers[0](req, res, match.params);
      } else {
        send404(res);
      }
    });

    server.listen(port, "0.0.0.0", () => {
      console.log(`[Roundtable Web] Listening on http://0.0.0.0:${port} (builtin, data-dir=${DATA_DIR})`);
      console.log(`[Roundtable Web] Discovered ${byDiscussionId.size} existing discussion(s)`);
      startDataDirWatcher();
    });
  }
}

main().catch((err) => {
  console.error("[Roundtable Web] Fatal:", err);
  process.exit(1);
});
