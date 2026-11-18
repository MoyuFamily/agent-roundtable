# 技术可靠性与验证

本页对应产品方向中的 P0 工程可靠性基础。以下能力位于当前源码；尚未发布的源码改动不代表已有 PyPI 包包含它们。

## 关键工程边界与阈值

| 模块 / 能力 | 约束或阈值 | 说明 |
|---|---|---|
| **材料包导入** | 单文件 `10 MiB`、最多 `1,000` 段、单段 `100,000` 字符、总计 `500,000` 字符 | 由 `roundtable.materials` 强制校验；不截断原文 |
| **HTTP Bridge 请求** | 请求体上限 `8 MiB`、读取空闲超时 `10s` | 容纳含非 BMP Unicode 转义的材料包；拒绝 chunked 与重复/负 `Content-Length` |
| **轮次等待 (`wait_seconds`)** | `0–30s`（单调时钟计时） | MCP 在工作线程执行、HTTP Bridge 并发服务，等待不阻塞发言 |
| **收件箱读取 (`limit`)** | `1–500`（默认 `50`） | 支持按 `message_types` 过滤与显式幂等确认 (`roundtable_ack_inbox`) |
| **MCP DB 观察器** | 约每 `200ms` 检查 `PRAGMA data_version` | 合并跨进程写入为订阅失效通知（依赖 `mcp>=1.30,<2`） |
| **PDF 导出超时** | 默认 `60s`（`ROUNDTABLE_PDF_TIMEOUT_MS` 上限 `120s`） | 每请求独立临时目录与子进程，取消/超时自动回收进程树 |

---

## 消息的读取、处理与确认

- **两步可靠消费协议**：先调用 `roundtable_inbox(agent_id=..., mark_read=false, message_types=[...])`，成功处理后再调用 `roundtable_ack_inbox(agent_id=..., message_ids=[...])`。
- **幂等与原子性**：重复确认同一消息不重复计数；混入其他 Agent 的消息 ID 会整批拒绝，不会部分确认。`agent_id` 是共享服务中的逻辑身份，不是新的认证机制。
- **消费者分工**：`AgentDaemon` 只过滤消费 `summon` / `invitation`，成功响应后才确认，不消费 `turn` 或未知类型；失败消息保留未读供重启重试。邀请接受支持成功后的重试，用于恢复“已加入、尚未确认消息”的中断。
- **兼容性**：`roundtable_inbox` 默认 `mark_read=true`，Bridge 的 `GET /inbox` 也保持读取即标记；需要重试保障时请显式采用上述两步协议，并避免多个消费者同时执行同一任务（提供至少一次处理基础，不承诺任意宿主副作用恰好一次）。

---

## MCP 订阅与共享数据库

- 当前依赖范围为 `mcp>=1.30,<2`；stdio 与 SSE 实际入口均在初始化时声明 `resources.subscribe`。
- 每个会话拥有独立 SQLite 连接与观察任务（约每 `200ms` 检查 `PRAGMA data_version`），另一个 stdio 进程、HTTP Bridge 或 Daemon 提交到同一数据库也会触发通知。
- 通知使用订阅者实际登记的 URI（含 `transcript` 与 `discussions` 集合）；取消订阅与断开连接会清理登记。
- **语义边界**：通知含义是“请重新读取”，保守使当前会话订阅失效并合并写入，不承诺逐写入精确过滤、固定延迟或持久化重放；重连后需重新订阅，独立数据库之间不自动同步。

```bash
# 本地启动共享数据库 MCP Server（SSE 默认仅监听本机 127.0.0.1）
python -m roundtable.mcp --db /path/to/shared.db
python -m roundtable.mcp --http --host 127.0.0.1 --port 8200 --db /path/to/shared.db
```

---

## 从实际入口验证

安装当前源码及测试依赖后：

```bash
python -m pip install -e '.[dev,mcp,materials]'
python scripts/check_mcp_runtime.py --source-root . --transport stdio
python scripts/check_mcp_runtime.py --source-root . --transport sse
python -m pytest tests/test_agent_runtime.py tests/mcp/test_cli_runtime.py -q
```

- `scripts/check_mcp_runtime.py` 启动真实双客户端进程，验证 `initialize`、工具/资源/提示词发现、订阅通知 URI、取消订阅、消息确认、读取端重启和结论恢复（固定测试发言，不调用模型）。
- CI 与 release preflight 在干净 venv 安装 wheel 后运行同一脚本（不传 `--source-root`，以 `python -I` 从临时目录启动），避免本地 checkout 掩盖安装包缺失。

---

## 加入会议与并发请求

- **原子成员加入**：接受邀请或召集时，状态变更与 `participants` 写入在同一事务提交，失败自动回滚；过期检查直接在响应路径执行，不依赖前置轮询；已关闭会议拒绝新成员，重复接受幂等返回。
- **并发请求与等待**：HTTP Bridge 使用多线程并发服务，MCP 在工作线程执行同步工具，轮次等待（`wait_seconds` `0–30s`）不会阻塞另一客户端提交发言。
- **Bridge 鉴权与启停**：配置 `auth_token` 的 `CodexBridge` / `GenericBridge` 对 `/agent`、`/inbox`、`/status/...` 及所有写入端点校验 `Authorization: Bearer` 或 `X-Roundtable-Token`，保留 `/health` 公开探测；不存在的会议返回 JSON `404`。两种 Bridge 共用 `GenericBridge` 实现，先绑定端口再登记端点（失败关闭监听），重复 `start()` 幂等。
- **请求体校验**：HTTP POST 请求体上限 `8 MiB`（兼容材料包 Unicode 转义），读取空闲超时 `10s`，拒绝 chunked 与重复/负 `Content-Length`，畸形 JSON/UTF-8 返回 `400`，超限返回 `413`。

---

## Viewer 会话与请求错误

- **跨进程锁与原子写入**：Python 实时发布与跨进程同步共用 `file_io.py`（POSIX `flock` / Windows `msvcrt` 字节锁）；整个读取-合并-替换持有同一 sidecar 锁，通过同目录临时文件 + `os.replace` 原子更新，所有 JSON/JSONL 显式使用 UTF-8。
- **独立链接撤销**：HTTP 撤销链接写入 `revocations/<token_hash>` 独立标记，不再覆盖整个 `discussion.json`；访问校验同时识别独立标记与历史快照中的 `revoked_token_hashes`，旧快照写回无法还原已撤销链接。
- **会话与降级路径**：密码校验仅签发以 token 哈希命名的会话 Cookie（服务重启后会话密钥轮换，需重新输入密码）。Express 与内置无依赖 HTTP 路径均捕获异步路由异常返回 JSON 错误；未安装 Node 依赖时内置路径仍可读取讨论。

---

## PDF 导出

- **进程与目录隔离**：`pdf-worker.mjs` 从已安装的 Viewer 路径加载 `md-to-pdf`（不运行 `npx` 或临时下载依赖）。每次导出使用独立临时目录与渲染子进程，默认超时 `60s`（可通过 `ROUNDTABLE_PDF_TIMEOUT_MS` 调整，最大 `120s`）。
- **取消与跨平台清理**：POSIX 通过 Puppeteer 信号处理与进程组回收浏览器；Windows 使用 `taskkill /T /F` 结束 worker 进程树，并用最多 5 次、递增 `100ms` 的异步重试清理短暂持锁（`EBUSY`）的 profile 目录。浏览器 socket 临时目录单独建在短路径 `/tmp` 下以避开 Linux Unix socket 路径长度上限；响应始终在临时目录清理完成后发送。
- **安全与环境变量**：讨论正文中的原始 HTML、脚本和远程图片作为纯文本渲染，不在导出浏览器中执行或请求远程资源。可通过 `PUPPETEER_EXECUTABLE_PATH` 指定本地 Chrome/Chromium，受控 CI 环境如需关闭沙箱可显式设置 `ROUNDTABLE_PDF_NO_SANDBOX=1`；测试中设置 `ROUNDTABLE_REQUIRE_PDF=1` 会在缺少浏览器时直接失败（CI 默认模式）。
- **CI 验证范围**：GitHub Actions 在 Ubuntu（Python 3.10/3.11/3.12）和 Windows Server 2025（Python 3.12）运行完整源码回归并要求真实 Chrome/PDF 导出通过；干净 wheel 安装烟雾检查运行在 Ubuntu。
