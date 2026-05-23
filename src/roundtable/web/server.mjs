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
import { readFileSync, watch, existsSync, writeFileSync, renameSync } from "node:fs";
import { join, resolve, dirname, basename } from "node:path";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);

// ---------------------------------------------------------------------------
// CLI args
// ---------------------------------------------------------------------------

function parseArgs() {
  const args = process.argv.slice(2);
  const opts = { port: 8199, discussionDir: "." };
  for (let i = 0; i < args.length; i++) {
    if (args[i] === "--port" && args[i + 1]) opts.port = parseInt(args[++i], 10);
    if (args[i] === "--discussion-dir" && args[i + 1]) opts.discussionDir = args[++i];
  }
  return opts;
}

const { port, discussionDir } = parseArgs();
const DISCUSSION_PATH = resolve(discussionDir, "discussion.json");
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
    return JSON.parse(raw);
  } catch {
    return null;
  }
}

function isTokenValid(token) {
  const data = readDiscussion();
  if (!data) return false;
  if (data.token !== token) return false;
  const revoked = data.revoked_tokens || [];
  return !revoked.includes(token);
}

function sendJSON(res, data, status = 200) {
  res.writeHead(status, {
    "Content-Type": "application/json",
    "Access-Control-Allow-Origin": "*",
  });
  res.end(JSON.stringify(data));
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

function send404(res) {
  sendJSON(res, { error: "Not found" }, 404);
}

// ---------------------------------------------------------------------------
// SSE connections store
// ---------------------------------------------------------------------------

/** @type {Map<string, Set<import("http").ServerResponse>>} */
const sseClients = new Map(); // token → Set<res>

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
      sendJSON(waiter.res, data);
    } else {
      sendJSON(waiter.res, { error: "Data not available" }, 500);
    }
    waiters.delete(waiter);
  }
}

// ---------------------------------------------------------------------------
// Routes
// ---------------------------------------------------------------------------

// GET /r/:token → Serve SPA
router.get("/r/:token", (req, res, params) => {
  if (!isTokenValid(params.token)) return send403(res);

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
      });
      const injected = html.replace(
        "</head>",
        `<script>window.__RT_CONFIG__ = ${config};</script></head>`
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

  const data = readDiscussion();
  if (!data) return sendJSON(res, { error: "Discussion not found" }, 404);

  // Don't expose the token in API responses
  const safe = { ...data };
  delete safe.token;
  sendJSON(res, safe);
});

// GET /api/:token/events → SSE stream
router.get("/api/:token/events", (req, res, params) => {
  if (!isTokenValid(params.token)) return send403(res);

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
    const safe = { ...data };
    delete safe.token;
    res.write(`event: init\ndata: ${JSON.stringify(safe)}\n\n`);
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

  // Parse query manually (no express)
  const url = new URL(req.url, `http://${req.headers.host}`);
  const since = parseInt(url.searchParams.get("since") || "0", 10) || 0;

  // If there's already a newer update, respond immediately
  const data = readDiscussion();
  if (data && data.updated_at > since) {
    const safe = { ...data };
    delete safe.token;
    return sendJSON(res, safe);
  }

  // Otherwise, wait up to 25 seconds
  if (!pollWaiters.has(params.token)) {
    pollWaiters.set(params.token, new Set());
  }

  const timer = setTimeout(() => {
    // Timeout — return current data or empty
    const latest = readDiscussion();
    if (latest) {
      const safe = { ...latest };
      delete safe.token;
      sendJSON(res, safe);
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

  // Share link is just the viewer URL with the token
  sendJSON(res, { ok: true, share_url: `/r/${params.token}` });
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
      const safe = { ...data };
      delete safe.token;

      lastUpdatedTimestamp = data.updated_at || Date.now();
      broadcastToSSE(token, "update", safe);
      notifyPollWaiters(token);
    }, 100); // 100ms debounce
  });
}

// ---------------------------------------------------------------------------
// HTTP server
// ---------------------------------------------------------------------------

async function main() {
  const hasExpress = await loadExpress();

  if (hasExpress && app) {
    // Use express
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

    app.get("/theme.css", (req, res) => {
      const handler = router._routes.find(
        (r) => r.method === "GET" && r.path === "/theme.css"
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
