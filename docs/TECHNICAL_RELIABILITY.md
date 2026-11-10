# 技术可靠性与验证

本页对应产品方向中的 P0 工程项。以下能力位于当前源码；尚未发布的源码改动不代表已有 PyPI 包包含它们。

## 消息的读取、处理与确认

可靠消费者采用两步协议：先调用 `roundtable_inbox(agent_id=..., mark_read=false)`，成功处理后调用 `roundtable_ack_inbox(agent_id=..., message_ids=[...])`。重试确认同一消息不会重复计数；混入其他 Agent 的消息 ID 会整批拒绝，不会部分确认。Agent ID 是共享服务中的逻辑身份，不是新的认证机制。

`message_types` 可筛选消息类型，`limit` 为 1–500。Daemon 只读取 summon/invitation，确认成功响应后才标记已读。它不消费 turn 或未知类型；手动处理、失败消息仍留在队列，重启后可重试。类型筛选避免积压的轮次消息占满前50条，阻挡后续召集。邀请接受支持成功后的重试，用于恢复“已经加入、尚未确认消息”时的中断。

为保持兼容，`roundtable_inbox` 的默认 mark_read 仍为 true，Bridge 的 GET /inbox 也保留读取即标记的行为。需要重试保障时应明确使用上述工具流程；避免两个消费者同时执行同一任务。这提供至少一次处理的基础，不承诺任意宿主副作用恰好执行一次。

## MCP 订阅与共享数据库

当前依赖范围为 `mcp>=1.30,<2`。stdio 和 SSE 的实际启动入口都声明 resources.subscribe；不是只在单元测试中构造能力对象。

每个连接拥有一个随会话释放的数据库观察任务，约每200毫秒检查独立 SQLite 连接的 data_version。另一个 stdio 进程、HTTP Bridge 或 Daemon 提交到同一数据库，也会使订阅者收到通知。通知使用订阅者实际登记的 URI，包括 transcript 和 discussions 集合；取消订阅和断开连接会清理登记。

通知表示“请重新读取”，不是每次写入的事件日志。当前会合并数据库写入，并保守地使当前会话的所有订阅失效，因此可能通知到内容未改变的资源；不承诺逐写入精确过滤、固定延迟或持久化通知重放。客户端重连后重新订阅并读取当前状态。独立数据库之间不会因此自动同步。

本地启动：

```bash
python -m roundtable.mcp --db /path/to/shared.db
python -m roundtable.mcp --http --host 127.0.0.1 --port 8200 --db /path/to/shared.db
```

SSE 默认只监听本机。需要其他监听地址时显式设置 `--host`，网络访问控制由部署环境提供。

## 从实际入口验证

安装当前源码及测试依赖后：

```bash
python -m pip install -e '.[dev,mcp]'
python scripts/check_mcp_runtime.py --source-root . --transport stdio
python scripts/check_mcp_runtime.py --source-root . --transport sse
python -m pytest tests/test_agent_runtime.py tests/mcp/test_cli_runtime.py -q
```

脚本会启动两个实际客户端，验证 initialize、工具/资源/提示词发现、订阅通知中的 URI、取消订阅、消息确认、读取端重启和结论恢复。stdio 模式启动两个独立服务器进程，共享临时数据库。SSE 模式连接同一服务器。固定发言仅是协议测试数据，没有调用模型。

CI 和 release preflight 在 wheel 安装到干净虚拟环境后，再运行同一脚本，不传 `--source-root`。服务器以 `python -I` 从临时目录启动，避免从 checkout 或 PYTHONPATH 导入源码而掩盖安装包缺失。核心包安装与 demo 检查保留，随后安装 wheel 的 mcp extra 并验证两种协议。源码依赖版本、模型运行和外部平台集成仍需各自验收。

## 加入会议与并发请求

接受邀请或召集时，状态变更和成员写入在同一事务提交；成员写入失败会回滚接受状态。召集到期检查直接发生在响应路径，不依赖此前已经轮询状态。已关闭会议拒绝新成员，已成功加入的重复请求可幂等返回。接受、拒绝和过期扫描不会相互覆盖终态。

HTTP Bridge 使用并发请求处理；MCP 在工作线程执行同步工具。一个客户端等待轮次时，另一个客户端仍能提交发言。`wait_seconds` 限定为0–30秒，`waited` 返回单调时钟计算的实际等待时间；到期后宿主可再次查询。

配置 auth_token 的 CodexBridge/GenericBridge 对 `/agent`、`/inbox`、`/status/...` 和写入端点统一验证令牌；`/health` 保留公开探测。未配置令牌的本机模式维持原行为。不存在的会议状态返回 JSON 404。

## PDF 导出

Viewer 的 pdf-worker.mjs 从安装位置加载 md-to-pdf，导出时不运行 npx 或下载依赖。每个请求使用独立临时目录和渲染进程，默认60秒超时（可通过 `ROUNDTABLE_PDF_TIMEOUT_MS` 设置，最大120秒）；请求断开或超时会终止渲染并清理文件。在 POSIX 平台同时清理渲染进程组中的浏览器子进程。

原始 HTML、脚本和远程图片作为文本处理，不在导出浏览器中执行或请求；代码块、表格和正文仍按 Markdown 排版。可用 `PUPPETEER_EXECUTABLE_PATH` 指定 Chrome/Chromium 可执行文件。受控 CI 环境需要关闭浏览器沙箱时显式设置 `ROUNDTABLE_PDF_NO_SANDBOX=1`，默认不关闭。

PDF 测试只在预检发现依赖缺失时允许跳过，运行过程中返回503视为失败。设置 `ROUNDTABLE_REQUIRE_PDF=1` 后，缺少依赖也会失败；CI 采用该模式。验证覆盖实际渲染、并发导出、超时清理、未授权导出拒绝及阻止正文中的远程资源请求。
