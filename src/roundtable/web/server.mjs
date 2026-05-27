#!/usr/bin/env node
/**
 * Express server for Roundtable Web Viewer.
 *
 * Zero extra npm dependencies beyond express itself.
 * Reads discussion.json via fs.watch + shared file lock (fcntl advisory).
 * Supports SSE (primary) and long-polling (WeChat fallback).
 *
 * CLI usage:
 *   node server.mjs --port 8199 --discussion-dir /path/to/output/rt_abc123
 *
 * PM2 usage:
 *   pm2 start server.mjs --name roundtable-web-rt_xxx --interpreter node \
 *     -- --port 8199 --discussion-dir /path/to/output/rt_abc123
 */

import { createServer } from "node:http";
import { readFileSync, watch, existsSync, writeFileSync, renameSync, createReadStream } from "node:fs";
import * as readline from "node:readline";
import { join, resolve, dirname, basename } from "node:path";
import { createRequire } from "node:module";
import { createHmac } from "node:crypto";

const require = createRequire(import.meta.url);

// ---------------------------------------------------------------------------
// CLI args
// ---------------------------------------------------------------------------

function parseArgs() {
  const args = process.argv.slice(2);
  const opts = { port: 8199, discussionDir: ".", passwordHash: "" };
  for (let i = 0; i < args.length; i++) {
    if (args[i] === "--port" && args[i + 1]) opts.port = parseInt(args[++i], 10);
    if (args[i] === "--discussion-dir" && args[i + 1]) opts.discussionDir = args[++i];
    if (args[i] === "--password-hash" && args[i + 1]) opts.passwordHash = args[++i];
  }
  return opts;
}

const { port, discussionDir, passwordHash } = parseArgs();
const DISCUSSION_PATH = resolve(discussionDir, "discussion.json");
const TOKEN_STREAM_PATH = resolve(discussionDir, "token_stream.jsonl");
const REVOKED_PATH = resolve(discussionDir, ".revoked_tokens");
const WEB_DIR = new URL(".", import.meta.url).pathname;

// ---------------------------------------------------------------------------
// Minimal Express (no npm: use built-in node:http + manual routing)
// ---------------------------------------------------------------------------

// We bundle express as a local dependency. If not available, fall back to
// a minimal built-in HTTP router.
let app;

async function loadExpress() {
  try {
    const express = (await import("express")).default;
    app = express();
    return true;
  } catch {
    return false;
  }
}

// ---------------------------------------------------------------------------
// Minimal built-in router (fallback if express not installed)
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
        return { handlers: route.handlers, params };
      }
    }
    return null;
  }

  _matchPath(pattern, urlPath) {
    // Convert /r/:token → regex
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
// Helpers
// ---------------------------------------------------------------------------

function readDiscussion() {
  try {
    if (!existsSync(DISCUSSION_PATH)) return null;
    const raw = readFileSync(DISCUSSION_PATH, "utf-8");
    const data = JSON.parse(raw);
    // Backward compat: old files without schema_version are treated as v1
    if (data.schema_version === undefined) data.schema_version = 1;
    return data;
  } catch {
    return null;
  }
}

function isTokenValid(token) {
  const data = readDiscussion();
  if (!data) return false;
  if (data.token !== token) return false;
  const revoked = data.revoked_tokens || [];
  if (revoked.includes(token)) return false;
  // Expiry check
  if (data.expires_at && Date.now() / 1000 > data.expires_at) return false;
  return true;
}

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

/** Escape a string for safe use inside an HTML attribute value. */
function escapeHtmlAttr(str) {
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/"/g, "&quot;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

function sendHTML(res, html) {
  res.writeHead(200, {
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
  res.writeHead(410, {
    "Content-Type": "text/html; charset=utf-8",
    "Access-Control-Allow-Origin": "*",
  });
  res.end(html);
}

function send404(res) {
  sendJSON(res, { error: "Not found" }, 404);
}

// ---------------------------------------------------------------------------
// Password protection (bcrypt + HMAC signed cookie)
// ---------------------------------------------------------------------------

let _bcrypt = null;
const _bcryptPromise = passwordHash
  ? import("bcryptjs").then(m => { _bcrypt = m.default; console.log("[Roundtable Web] Password protection enabled"); })
      .catch(err => { console.error("[Roundtable Web] bcryptjs not available:", err.message); })
  : Promise.resolve();

function _signPwHash(pwHash) {
  return createHmac("sha256", passwordHash.slice(0, 32)).update(pwHash).digest("hex").slice(0, 32);
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

function checkPassword(req) {
  if (!_bcrypt || !passwordHash) return true;
  const cookies = _parseCookies(req.headers.cookie);
  const rtPw = cookies["rt_pw"];
  if (!rtPw) return false;
  const [storedHash, sig] = rtPw.split(":");
  if (!storedHash || !sig) return false;
  const expectedSig = _signPwHash(storedHash);
  return sig === expectedSig;
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
    document.getElementById('pwForm').addEventListener('submit', async (e) => {
      e.preventDefault();
      const pw = document.getElementById('pwInput').value.trim();
      if (!pw) { document.getElementById('pwError').textContent = 'Please enter a password'; return; }
      const btn = document.getElementById('pwBtn');
      btn.disabled = true; btn.textContent = 'Verifying...';
      try {
        const resp = await fetch('/api/validate-password', {
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

// ---------------------------------------------------------------------------
// SSE connections store
// ---------------------------------------------------------------------------

/** @type {Map<string, Set<import("http").ServerResponse>>} */
const sseClients = new Map(); // token → Set<res>
const sseDeltaBuffers = new Map(); // token → {events, timer}
const sseLastSeqByToken = new Map(); // token → latest stream seq broadcast by watcher

function safeDiscussion(data) {
  const safe = { ...data };
  delete safe.token;
  return safe;
}

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

// ---------------------------------------------------------------------------
// Long-polling store
// ---------------------------------------------------------------------------

const pollWaiters = new Map(); // token → Set<{res, since, timer}>
let lastUpdatedTimestamp = 0;

function notifyPollWaiters(token) {
  const waiters = pollWaiters.get(token);
  if (!waiters) return;

  for (const waiter of [...waiters]) {
    clearTimeout(waiter.timer);
    const data = readDiscussion();
    if (data) {
      sendJSON(waiter.res, safeDiscussion(data));
    } else {
      sendJSON(waiter.res, { error: "Data not available" }, 500);
    }
    waiters.delete(waiter);
  }
}

// ---------------------------------------------------------------------------
// Routes
// ---------------------------------------------------------------------------

// GET /share/:token → Standalone share page with rich OG tags
router.get("/share/:token", (req, res, params) => {
  if (!isTokenValid(params.token)) return send403(res);

  const disc = readDiscussion();
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
    const rounds = disc.rounds?.length || 0;
    const speeches = disc.speeches || [];
    const consensus = disc.consensus_score != null ? Math.round(disc.consensus_score * 100) : null;
    const durationMin = disc.duration_min || null;
    const agentColors = ["#58a6ff", "#3fb950", "#d29922", "#bc8cff", "#f85149", "#f0883e", "#a5d6ff", "#7ee787"];

    // OG title & description
    const ogTitle = `圆桌讨论: ${topic}`;
    const participantNames = participants.map(p => p.name || p.id).join("、");
    const ogDesc = `多位 AI Agent 正在围绕「${topic}」展开圆桌讨论${participantNames ? `。参与者: ${participantNames}` : ""}`;

    // Status badge
    const statusClass = status === "completed" ? "completed" : "ongoing";
    const statusLabel = status === "completed" ? "已结束" : "进行中";

    // Meta text
    const metaParts = [];
    if (participants.length) metaParts.push(`${participants.length} 位参与者`);
    if (rounds > 0) metaParts.push(`${rounds} 轮讨论`);
    if (durationMin) metaParts.push(`约 ${durationMin} 分钟`);
    const metaText = metaParts.join(" · ") || "多 Agent 圆桌讨论";

    // Participant chips
    const participantsHtml = participants.map((p, i) => {
      const name = p.name || p.id || `Agent ${i + 1}`;
      const color = agentColors[i % agentColors.length];
      return `<span class="participant-chip"><span class="dot" style="background:${color}"></span>${escapeHtmlAttr(name)}</span>`;
    }).join("");

    // Stats
    let statsHtml = "";
    if (rounds > 0 || speeches.length > 0) {
      statsHtml = `<div class="rounds-info">
        ${rounds > 0 ? `<div class="stat"><span class="val">${rounds}</span><span class="lbl">讨论轮次</span></div>` : ""}
        ${speeches.length > 0 ? `<div class="stat"><span class="val">${speeches.length}</span><span class="lbl">发言数</span></div>` : ""}
        ${participants.length > 0 ? `<div class="stat"><span class="val">${participants.length}</span><span class="lbl">参与者</span></div>` : ""}
        ${durationMin ? `<div class="stat"><span class="val">${durationMin}</span><span class="lbl">分钟</span></div>` : ""}
      </div>`;
    }

    // Consensus bar
    let consensusHtml = "";
    if (consensus != null) {
      const level = consensus >= 70 ? "high" : consensus >= 40 ? "medium" : "low";
      consensusHtml = `<div class="consensus-bar">
        <div class="label">共识度</div>
        <div class="consensus-track"><div class="consensus-fill ${level}" style="width:${consensus}%"></div></div>
        <div class="consensus-value">${consensus}%</div>
      </div>`;
    }

    // Preview messages (first 3 speeches)
    const previewSpeeches = speeches.slice(0, 3);
    const messagesHtml = previewSpeeches.length > 0
      ? previewSpeeches.map((s, i) => {
          const agentName = s.display_name || s.agent_id || `Agent ${i + 1}`;
          const text = (s.text || s.content || "").slice(0, 200);
          const color = agentColors[(s.agent_index || i) % agentColors.length];
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

// GET /r/:token → Serve SPA
router.get("/r/:token", (req, res, params) => {
  // Check expiry first — show friendly expired page instead of generic 403
  const disc = readDiscussion();
  if (disc && disc.expires_at && Date.now() / 1000 > disc.expires_at) {
    return sendExpired(res);
  }
  if (!isTokenValid(params.token)) return send403(res);
  // Password gate: if password protection is enabled, check cookie
  if (passwordHash && _bcrypt && !checkPassword(req)) {
    return sendPasswordPage(res);
  }

  // Serve index.html from web/ directory
  const indexPath = join(WEB_DIR, "index.html");
  try {
    if (existsSync(indexPath)) {
      const html = readFileSync(indexPath, "utf-8");
      // Inject config for the SPA
      const config = JSON.stringify({
        token: params.token,
        port,
        host: "0.0.0.0",
        hasPassword: !!(passwordHash && _bcrypt),
      });
      // Build Open Graph tags from discussion data
      const disc = readDiscussion();
      const ogTitle = disc?.topic ? `圆桌讨论: ${disc.topic}` : "Roundtable 圆桌讨论";
      const ogDesc = disc?.topic
        ? `多位 AI Agent 正在围绕「${disc.topic}」展开圆桌讨论。${disc.participants?.length ? `参与者: ${disc.participants.map(p => p.name || p.id).join("、")}` : ""}`
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
      sendHTML(res, injected);
    } else {
      sendHTML(res, "<h1>Roundtable Web Viewer</h1><p>index.html not found</p>");
    }
  } catch (err) {
    sendHTML(res, `<h1>Error</h1><pre>${err.message}</pre>`);
  }
});

// GET /api/:token/data → Read discussion.json
router.get("/api/:token/data", (req, res, params) => {
  if (!isTokenValid(params.token)) return send403(res);
  if (passwordHash && _bcrypt && !checkPassword(req)) return sendJSON(res, { error: "Password required" }, 401);

  const data = readDiscussion();
  if (!data) return sendJSON(res, { error: "Discussion not found" }, 404);

  // Don't expose the token in API responses
  sendJSON(res, safeDiscussion(data));
});

// GET /api/:token/events → SSE stream
router.get("/api/:token/events", (req, res, params) => {
  if (!isTokenValid(params.token)) return send403(res);
  if (passwordHash && _bcrypt && !checkPassword(req)) return sendJSON(res, { error: "Password required" }, 401);

  res.writeHead(200, {
    "Content-Type": "text/event-stream",
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "Access-Control-Allow-Origin": "*",
    "X-Accel-Buffering": "no", // nginx passthrough
  });

  // Initial push
  const data = readDiscussion();
  if (data) {
    const currentSeq = Number(data?.stream?.seq ?? 0);
    if (Number.isFinite(currentSeq)) sseLastSeqByToken.set(params.token, currentSeq);
    res.write(`event: init\ndata: ${JSON.stringify(safeDiscussion(data))}\n\n`);
    if (typeof res.flushHeaders === "function") res.flushHeaders();
  }

  // Register SSE client
  if (!sseClients.has(params.token)) {
    sseClients.set(params.token, new Set());
  }
  sseClients.get(params.token).add(res);

  // Keep-alive ping every 30s
  const keepAlive = setInterval(() => {
    try {
      res.write(": keepalive\n\n");
    } catch {
      clearInterval(keepAlive);
    }
  }, 30000);

  req.on("close", () => {
    clearInterval(keepAlive);
    const clients = sseClients.get(params.token);
    if (clients) clients.delete(res);
  });
});

// GET /api/:token/poll?since=<timestamp> → Long-polling
router.get("/api/:token/poll", (req, res, params) => {
  if (!isTokenValid(params.token)) return send403(res);
  if (passwordHash && _bcrypt && !checkPassword(req)) return sendJSON(res, { error: "Password required" }, 401);

  // Parse query manually (no express)
  const url = new URL(req.url, `http://${req.headers.host}`);
  const since = parseInt(url.searchParams.get("since") || "0", 10) || 0;

  // If there's already a newer update, respond immediately
  const data = readDiscussion();
  if (data && data.updated_at > since) {
    return sendJSON(res, safeDiscussion(data));
  }

  // Otherwise, wait up to 25 seconds
  if (!pollWaiters.has(params.token)) {
    pollWaiters.set(params.token, new Set());
  }

  const timer = setTimeout(() => {
    // Timeout — return current data or empty
    const latest = readDiscussion();
    if (latest) {
      sendJSON(res, safeDiscussion(latest));
    } else {
      sendJSON(res, { updated_at: since });
    }
    pollWaiters.get(params.token)?.delete(waiter);
  }, 25000);

  const waiter = { res, since, timer };
  pollWaiters.get(params.token).add(waiter);
});

// POST /api/:token/share → Generate share link (link is simply the page URL)
router.post("/api/:token/share", (req, res, params) => {
  if (!isTokenValid(params.token)) return send403(res);

  const data = readDiscussion();
  if (!data) return sendJSON(res, { error: "Discussion not found" }, 404);

  // Share link points to the standalone share page with OG tags
  sendJSON(res, { ok: true, share_url: `/share/${params.token}` });
});

// POST /api/:token/revoke → Revoke token
router.post("/api/:token/revoke", (req, res, params) => {
  if (!isTokenValid(params.token)) return send403(res);

  // Mark as revoked
  const data = readDiscussion();
  if (!data) return sendJSON(res, { error: "Discussion not found" }, 404);

  if (!data.revoked_tokens) data.revoked_tokens = [];
  if (!data.revoked_tokens.includes(params.token)) {
    data.revoked_tokens.push(params.token);
  }
  data.updated_at = Math.floor(Date.now() / 1000);

  // Write back
  const tmpPath = DISCUSSION_PATH + ".tmp";
  writeFileSync(tmpPath, JSON.stringify(data, null, 2));
  renameSync(tmpPath, DISCUSSION_PATH);

  // Notify all clients
  broadcastToSSE(params.token, "revoked", { revoked: true });

  sendJSON(res, { ok: true, revoked: true });
});

// POST /api/validate-password → Password validation (no auth required)
router.post("/api/validate-password", async (req, res) => {
  if (!_bcrypt || !passwordHash) return sendJSON(res, { ok: true, noPassword: true });

  let body = "";
  for await (const chunk of req) body += chunk;
  try {
    const { password } = JSON.parse(body);
    if (!password) return sendJSON(res, { ok: false, error: "Password required" }, 400);

    const match = await _bcrypt.compare(password, passwordHash);
    if (match) {
      const sig = _signPwHash(passwordHash);
      res.setHeader("Set-Cookie", `rt_pw=${encodeURIComponent(passwordHash + ":" + sig)}; Path=/; HttpOnly; SameSite=Lax; Max-Age=${7 * 24 * 3600}`);
      return sendJSON(res, { ok: true });
    }
    return sendJSON(res, { ok: false, error: "Incorrect password" }, 401);
  } catch {
    return sendJSON(res, { ok: false, error: "Invalid request" }, 400);
  }
});

// GET /api/:token/export/markdown → Export discussion as Markdown
router.get("/api/:token/export/markdown", (req, res, params) => {
  if (!isTokenValid(params.token)) return send403(res);
  if (passwordHash && _bcrypt && !checkPassword(req)) return sendJSON(res, { error: "Password required" }, 401);

  const data = readDiscussion();
  if (!data) return sendJSON(res, { error: "Discussion not found" }, 404);

  const topic = data.topic || "Discussion";
  const participants = data.participants || [];
  const speeches = data.speeches || [];
  const roundSummaries = data.round_summaries || [];
  const finalSummary = data.final_summary;
  const conclusion = data.conclusion;

  let md = `# ${topic}\n\n`;

  // Participants
  if (participants.length > 0) {
    md += `## Participants\n\n`;
    for (const p of participants) {
      const name = p.name || p.display_name || p.profile || p.id || "";
      const role = p.role || "";
      md += role ? `- **${name}** (${role})\n` : `- **${name}**\n`;
    }
    md += "\n";
  }

  // Speeches grouped by round
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

  // Round summaries
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

  // Final summary
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

  // Conclusion
  if (conclusion) {
    md += `## Conclusion\n\n${conclusion}\n\n`;
  }

  // Footer
  md += `---\n\n*Generated by Roundtable AI*\n`;

  const filename = topic.replace(/[^a-zA-Z0-9\u4e00-\u9fff_-]/g, "_").slice(0, 60) || "discussion";
  res.writeHead(200, {
    "Content-Type": "text/markdown; charset=utf-8",
    "Content-Disposition": `attachment; filename="${filename}.md"`,
    "Access-Control-Allow-Origin": "*",
  });
  res.end(md);
});

// GET /api/:token/export/pdf → Export discussion as PDF (via md-to-pdf)
router.get("/api/:token/export/pdf", async (req, res, params) => {
  if (!isTokenValid(params.token)) return send403(res);
  if (passwordHash && _bcrypt && !checkPassword(req)) return sendJSON(res, { error: "Password required" }, 401);

  const data = readDiscussion();
  if (!data) return sendJSON(res, { error: "Discussion not found" }, 404);

  const { spawn } = await import("node:child_process");

  // Reuse the markdown generation logic
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
      const name = p.name || p.display_name || p.profile || p.id || "";
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

  const filename = topic.replace(/[^a-zA-Z0-9\u4e00-\u9fff_-]/g, "_").slice(0, 60) || "discussion";

  // Convert Markdown to PDF using md-to-pdf via npx
  const tmpMdPath = resolve(discussionDir, `.${filename}.tmp.md`);
  const expectedPdfPath = tmpMdPath.replace(/\.md$/, ".pdf");
  try {
    writeFileSync(tmpMdPath, md, "utf-8");

    const pdfOk = await new Promise((resolveP, rejectP) => {
      let stderr = "";
      const child = spawn("npx", ["--yes", "md-to-pdf", basename(tmpMdPath)], {
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

    if (pdfOk && existsSync(expectedPdfPath)) {
      const { unlinkSync } = await import("node:fs");
      const pdfBuffer = readFileSync(expectedPdfPath);
      res.writeHead(200, {
        "Content-Type": "application/pdf",
        "Content-Disposition": `attachment; filename="${filename}.pdf"`,
        "Content-Length": pdfBuffer.length,
        "Access-Control-Allow-Origin": "*",
      });
      res.end(pdfBuffer);
      // Cleanup
      try { unlinkSync(tmpMdPath); unlinkSync(expectedPdfPath); } catch { /* ignore */ }
    } else {
      sendJSON(res, { error: "PDF generation failed — output not found" }, 500);
    }
  } catch (err) {
    console.error("[export/pdf] Error:", err.message);
    // Cleanup temp files
    try { unlinkSync(tmpMdPath); } catch { /* ignore */ }
    try { unlinkSync(expectedPdfPath); } catch { /* ignore */ }
    sendJSON(res, { error: "PDF generation failed", detail: err.message }, 500);
  }
});

// GET /theme.css → Serve theme CSS
router.get("/theme.css", (req, res) => {
  const cssPath = join(WEB_DIR, "theme.css");
  if (existsSync(cssPath)) {
    const css = readFileSync(cssPath, "utf-8");
    res.writeHead(200, { "Content-Type": "text/css" });
    res.end(css);
  } else {
    res.writeHead(404);
    res.end("/* theme.css not found */");
  }
});

// GET /viewer.css → Serve viewer CSS
router.get("/viewer.css", (req, res) => {
  const cssPath = join(WEB_DIR, "viewer.css");
  if (existsSync(cssPath)) {
    const css = readFileSync(cssPath, "utf-8");
    res.writeHead(200, { "Content-Type": "text/css" });
    res.end(css);
  } else {
    res.writeHead(404);
    res.end("/* viewer.css not found */");
  }
});

// GET /i18n.js → Serve i18n JS
router.get("/i18n.js", (req, res) => {
  const jsPath = join(WEB_DIR, "i18n.js");
  if (existsSync(jsPath)) {
    const js = readFileSync(jsPath, "utf-8");
    res.writeHead(200, { "Content-Type": "application/javascript" });
    res.end(js);
  } else {
    res.writeHead(404);
    res.end("/* i18n.js not found */");
  }
});

// GET /viewer.js → Serve viewer JS
router.get("/viewer.js", (req, res) => {
  const jsPath = join(WEB_DIR, "viewer.js");
  if (existsSync(jsPath)) {
    const js = readFileSync(jsPath, "utf-8");
    res.writeHead(200, { "Content-Type": "application/javascript" });
    res.end(js);
  } else {
    res.writeHead(404);
    res.end("/* viewer.js not found */");
  }
});

// ---------------------------------------------------------------------------
// Discussion Replay API
// ---------------------------------------------------------------------------

/**
 * Read and parse token_stream.jsonl, returning an array of event objects.
 * Each event has: type, created_at, and various payload fields.
 */
async function readTokenStream() {
  const events = [];
  if (!existsSync(TOKEN_STREAM_PATH)) return events;

  return new Promise((resolve, reject) => {
    const rl = readline.createInterface({
      input: createReadStream(TOKEN_STREAM_PATH, { encoding: "utf-8" }),
      crlfDelay: Infinity,
    });
    rl.on("line", (line) => {
      const trimmed = line.trim();
      if (!trimmed) return;
      try {
        events.push(JSON.parse(trimmed));
      } catch { /* skip malformed lines */ }
    });
    rl.on("close", () => resolve(events));
    rl.on("error", reject);
  });
}

/**
 * Build replay metadata from a list of parsed events.
 * Returns: { totalEvents, duration, startTime, endTime, rounds, agents }
 */
function buildReplayMeta(events) {
  if (events.length === 0) {
    return { totalEvents: 0, duration: 0, startTime: 0, endTime: 0, rounds: [], agents: [] };
  }

  const startTime = events[0].timestamp || events[0].created_at || 0;
  const endTime = events[events.length - 1].timestamp || events[events.length - 1].created_at || 0;
  const duration = endTime - startTime;

  // Track rounds: each round_summary marks a boundary
  const roundBoundaries = [];
  const seenRounds = new Set();
  const agents = new Map();

  for (const ev of events) {
    const evTime = ev.timestamp || ev.created_at || 0;
    // Track round boundaries from speech_start or speech_delta events
    const round = ev.round ?? ev.payload?.speech?.round ?? ev.speech?.round;
    if (round != null && !seenRounds.has(round)) {
      seenRounds.add(round);
      roundBoundaries.push({
        round: Number(round),
        startTs: evTime,
        offsetMs: (evTime - startTime) * 1000,
      });
    }

    // Track unique agents
    const agentId = ev.agent ?? ev.agent_id ?? ev.payload?.speech?.agent_id ?? ev.speech?.agent_id ?? ev.payload?.speech?.participant ?? ev.speech?.participant;
    const agentName = ev.display_name ?? ev.agent_name ?? ev.payload?.speech?.agent_name ?? ev.speech?.agent_name ?? ev.payload?.speech?.display_name ?? ev.speech?.display_name;
    if (agentId && !agents.has(agentId)) {
      agents.set(agentId, { id: agentId, name: agentName || agentId });
    }
  }

  // Sort round boundaries by round number
  roundBoundaries.sort((a, b) => a.round - b.round);

  return {
    totalEvents: events.length,
    duration: duration * 1000, // convert to ms
    startTime,
    endTime,
    rounds: roundBoundaries,
    agents: Array.from(agents.values()),
  };
}

// GET /api/:token/replay/meta → Replay metadata for the progress bar
router.get("/api/:token/replay/meta", async (req, res, params) => {
  const token = params?.token || req.params?.token;

  // Validate token
  if (!isTokenValid(token)) {
    return sendJSON(res, { error: "Invalid or expired token" }, 403);
  }

  try {
    const events = await readTokenStream();
    const meta = buildReplayMeta(events);
    sendJSON(res, { ok: true, ...meta });
  } catch (err) {
    sendJSON(res, { error: "Failed to read replay data", detail: String(err) }, 500);
  }
});

// GET /api/:token/replay/stream → SSE replay stream
// Query params:
//   speed=1     — playback speed multiplier (1 = realtime, 2 = 2x, 0 = instant)
//   from=0      — start offset in ms from beginning
router.get("/api/:token/replay/stream", async (req, res, params) => {
  const token = params?.token || req.params?.token;

  // Validate token
  if (!isTokenValid(token)) {
    return sendJSON(res, { error: "Invalid or expired token" }, 403);
  }

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

  // Parse the JSONL file
  let events;
  try {
    events = await readTokenStream();
  } catch (err) {
    return sendJSON(res, { error: "Failed to read replay data" }, 500);
  }

  if (events.length === 0) {
    return sendJSON(res, { error: "No replay data available" }, 404);
  }

  // Set up SSE
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

  // Filter events from the requested offset
  const filteredEvents = events.filter((ev) => {
    const offsetSec = (ev.timestamp || ev.created_at || 0) - startTime;
    return offsetSec >= startOffsetSec;
  });

  let closed = false;
  req.on("close", () => { closed = true; });

  if (speed === 0) {
    // Instant mode — send all events immediately
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

  // Realtime mode — delay events according to their timestamps
  for (let i = 0; i < filteredEvents.length; i++) {
    if (closed) break;

    const ev = filteredEvents[i];
    const eventTime = (ev.timestamp || ev.created_at || 0) - startTime;
    const delayMs = Math.max(0, (eventTime - startOffsetSec) * 1000 / speed);

    // Calculate progress for the client
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

    // Calculate inter-event delay for the next iteration
    if (i < filteredEvents.length - 1) {
      const nextTime = (filteredEvents[i + 1].timestamp || filteredEvents[i + 1].created_at || 0) - startTime;
      const interDelay = Math.max(0, (nextTime - eventTime) * 1000 / speed);
      // Cap individual delays at 5s for UX (e.g. long pauses between rounds)
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
// File watcher → broadcast to SSE + polling
// ---------------------------------------------------------------------------

function startFileWatcher() {
  if (!existsSync(DISCUSSION_PATH)) {
    // Retry in 2 seconds if file doesn't exist yet
    setTimeout(startFileWatcher, 2000);
    return;
  }

  let debounceTimer = null;
  // Watch the directory instead of the file — macOS fs.watch() doesn't
  // reliably detect changes after atomic rename (os.rename replaces inode).
  // Watching the parent directory catches the rename event on all platforms.
  const watchDir = dirname(DISCUSSION_PATH);
  const targetName = basename(DISCUSSION_PATH);
  watch(watchDir, (_eventType, changedFilename) => {
    if (changedFilename !== targetName) return;
    // Debounce: avoid rapid-fire during atomic writes
    clearTimeout(debounceTimer);
    debounceTimer = setTimeout(() => {
      const data = readDiscussion();
      if (!data) return;

      const token = data.token;
      const safe = safeDiscussion(data);

      lastUpdatedTimestamp = data.updated_at || Date.now();
      const previousSeq = sseLastSeqByToken.get(token) ?? 0;
      const deltaEvents = streamEventsSince(data, previousSeq);
      const latestSeq = Number(data?.stream?.seq ?? previousSeq);
      if (Number.isFinite(latestSeq)) sseLastSeqByToken.set(token, Math.max(previousSeq, latestSeq));
      for (const eventData of deltaEvents) queueSSEDelta(token, eventData);
      broadcastToSSE(token, "update", safe);
      notifyPollWaiters(token);
    }, 50); // 50ms flush buffer for streaming deltas
  });
}

// ---------------------------------------------------------------------------
// HTTP server
// ---------------------------------------------------------------------------

async function main() {
  const hasExpress = await loadExpress();

  if (hasExpress && app) {
    // Use express
    app.get("/share/:token", (req, res) => {
      const handler = router._routes.find(
        (r) => r.method === "GET" && r.path === "/share/:token"
      );
      if (handler) {
        const params = router._matchPath(handler.path, req.path);
        if (params) {
          req.url = req.originalUrl;
          handler.handlers[0](req, res, params);
          return;
        }
      }
      send404(res);
    });

    app.get("/r/:token", (req, res) => {
      const handler = router._routes.find(
        (r) => r.method === "GET" && r.path === "/r/:token"
      );
      if (handler) {
        const params = router._matchPath(handler.path, req.path);
        if (params) {
          req.url = req.originalUrl;
          handler.handlers[0](req, res, params);
          return;
        }
      }
      send404(res);
    });

    app.get("/api/:token/data", (req, res) => {
      const params = { token: req.params.token };
      router._routes
        .find((r) => r.method === "GET" && r.path === "/api/:token/data")
        ?.handlers[0](req, res, params);
    });

    app.get("/api/:token/events", (req, res) => {
      const params = { token: req.params.token };
      router._routes
        .find((r) => r.method === "GET" && r.path === "/api/:token/events")
        ?.handlers[0](req, res, params);
    });

    app.get("/api/:token/poll", (req, res) => {
      const params = { token: req.params.token };
      router._routes
        .find((r) => r.method === "GET" && r.path === "/api/:token/poll")
        ?.handlers[0](req, res, params);
    });

    app.post("/api/:token/share", (req, res) => {
      const params = { token: req.params.token };
      router._routes
        .find((r) => r.method === "POST" && r.path === "/api/:token/share")
        ?.handlers[0](req, res, params);
    });

    app.post("/api/:token/revoke", (req, res) => {
      const params = { token: req.params.token };
      router._routes
        .find((r) => r.method === "POST" && r.path === "/api/:token/revoke")
        ?.handlers[0](req, res, params);
    });

    app.post("/api/validate-password", (req, res) => {
      router._routes
        .find((r) => r.method === "POST" && r.path === "/api/validate-password")
        ?.handlers[0](req, res, {});
    });

    app.get("/api/:token/export/markdown", (req, res) => {
      const params = { token: req.params.token };
      router._routes
        .find((r) => r.method === "GET" && r.path === "/api/:token/export/markdown")
        ?.handlers[0](req, res, params);
    });

    app.get("/api/:token/export/pdf", (req, res) => {
      const params = { token: req.params.token };
      router._routes
        .find((r) => r.method === "GET" && r.path === "/api/:token/export/pdf")
        ?.handlers[0](req, res, params);
    });

    app.get("/api/:token/replay/meta", (req, res) => {
      const params = { token: req.params.token };
      router._routes
        .find((r) => r.method === "GET" && r.path === "/api/:token/replay/meta")
        ?.handlers[0](req, res, params);
    });

    app.get("/api/:token/replay/stream", (req, res) => {
      const params = { token: req.params.token };
      router._routes
        .find((r) => r.method === "GET" && r.path === "/api/:token/replay/stream")
        ?.handlers[0](req, res, params);
    });

    app.get("/theme.css", (req, res) => {
      const handler = router._routes.find(
        (r) => r.method === "GET" && r.path === "/theme.css"
      );
      if (handler) handler.handlers[0](req, res, {});
    });

    app.get("/viewer.css", (req, res) => {
      const handler = router._routes.find(
        (r) => r.method === "GET" && r.path === "/viewer.css"
      );
      if (handler) handler.handlers[0](req, res, {});
    });

    app.get("/i18n.js", (req, res) => {
      const handler = router._routes.find(
        (r) => r.method === "GET" && r.path === "/i18n.js"
      );
      if (handler) handler.handlers[0](req, res, {});
    });

    app.get("/viewer.js", (req, res) => {
      const handler = router._routes.find(
        (r) => r.method === "GET" && r.path === "/viewer.js"
      );
      if (handler) handler.handlers[0](req, res, {});
    });

    app.listen(port, "0.0.0.0", () => {
      console.log(`[Roundtable Web] Listening on http://0.0.0.0:${port}`);
      startFileWatcher();
    });
  } else {
    // Fallback: raw http server
    const server = createServer((req, res) => {
      const url = new URL(req.url, `http://${req.headers.host}`);
      const method = req.method.toUpperCase();

      const match = router.match(method, url.pathname);
      if (match) {
        match.handlers[0](req, res, match.params);
      } else {
        send404(res);
      }
    });

    server.listen(port, "0.0.0.0", () => {
      console.log(`[Roundtable Web] Listening on http://0.0.0.0:${port} (builtin)`);
      startFileWatcher();
    });
  }
}

main().catch((err) => {
  console.error("[Roundtable Web] Fatal:", err);
  process.exit(1);
});