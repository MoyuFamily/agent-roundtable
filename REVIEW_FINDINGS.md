# Roundtable v2 Code Review - 发现的问题

审查日期：2026-06-07
审查范围：Agent Dispatch & Federated Meetings 升级
变更规模：20 个文件，+2700/-76 行

---

## 🔴 严重问题 (Critical Issues)

### 1. **Race Condition: 跨进程 Web 同步**
**位置**: `core.py:294-296`, `core.py:795-796`

```python
# core.py line 294-296
else:
    # Publisher not in memory (cross-process) — update discussion.json directly
    self._update_web_discussion_json(discussion_id, speech_data, disc.topic, participants)
```

**问题**:
- 当一个进程持有 `WebPublisher` 实例，另一个进程直接写 `discussion.json` 时会产生数据竞争
- `WebPublisher` 可能缓存了旧状态，跨进程写入会被覆盖
- 没有文件锁机制保护并发写入

**影响**: 数据丢失、状态不一致
**建议**: 
- 使用文件锁 (`fcntl.flock`) 或改用 SQLite 作为唯一数据源
- 将 web viewer 改为纯读模式，从数据库实时查询

---

### 2. **SQL Injection 风险：动态 SQL 构建**
**位置**: `db.py:1036`

```python
placeholders = ",".join("?" for _ in message_ids)
cur = conn.execute(
    f"UPDATE agent_inbox SET read_at = ? WHERE id IN ({placeholders}) AND read_at IS NULL",
    [now, *message_ids],
)
```

**问题**:
- 虽然使用了参数化查询，但如果 `message_ids` 是空列表，会生成无效 SQL
- 已有保护 (`if not message_ids: return 0`)，但类似模式在其他地方可能遗漏

**影响**: 潜在的运行时错误
**建议**: 添加单元测试覆盖边界情况（空列表、None 值）

---

### 3. **幂等性键冲突处理不完整**
**位置**: `db.py:1146-1149`

```python
if idempotency_key:
    existing = self.get_dispatch(conn, idempotency_key=idempotency_key)
    if existing:
        return existing
```

**问题**:
- 仅在 `create_dispatch` 返回已存在的记录，但不检查状态是否匹配
- 如果一个 dispatch 被 cancelled，幂等键会阻止重试
- `create_summon` 也有类似问题 (`INSERT OR IGNORE`)

**影响**: 无法重试失败的调度
**建议**: 
- 检查已存在 dispatch 的状态，如果是终态 (completed/cancelled) 则允许新建
- 或者添加 `allow_retry` 参数明确控制行为

---

## 🟡 中等问题 (Medium Issues)

### 4. **心跳超时硬编码**
**位置**: `db.py:967`

```python
"online": (now - row["last_seen"]) < 90,
```

**问题**:
- 90 秒超时硬编码在多处 (`get_agent`, `list_agents`)
- 与 `list_agents` 的 `timeout_seconds` 参数不一致

**影响**: 配置不灵活，不同调用点逻辑不统一
**建议**: 提取为常量 `DEFAULT_HEARTBEAT_TIMEOUT = 90`

---

### 5. **缺少数据库索引**
**位置**: `schema.py:84-89`

**问题**:
- `dispatches` 表缺少 `coordinator_agent_id` 索引
- `summons` 表缺少 `(status, expires_at)` 组合索引（用于超时扫描）
- `agent_inbox` 表缺少 `(discussion_id, read_at)` 索引

**影响**: 高负载下查询性能降低
**建议**: 添加迁移创建索引：
```sql
CREATE INDEX IF NOT EXISTS idx_dispatches_coordinator ON dispatches(coordinator_agent_id);
CREATE INDEX IF NOT EXISTS idx_summons_timeout ON summons(status, expires_at);
CREATE INDEX IF NOT EXISTS idx_inbox_discussion ON agent_inbox(discussion_id, read_at);
```

---

### 6. **WebPublisher 生命周期管理混乱**
**位置**: `core.py:782-790`

```python
# Disk-backed viewer keeps serving via shared PM2 server;
# release the in-memory publisher to avoid leaking.
self._publishers.pop(discussion_id, None)
logger.info("Web publisher retained for concluded discussion %s", discussion_id)
```

**问题**:
- 注释说 "retained"，但代码执行了 `pop` 移除
- `_publishers` 字典只在 concluded 时清理，active/cancelled 可能泄漏
- 跨进程场景下 `publisher` 可能为 None，但仍尝试调用方法

**影响**: 内存泄漏、空指针错误
**建议**: 
- 统一生命周期：要么全部 retain，要么全部 stop
- 添加 `__del__` 或使用 `weakref` 自动清理

---

### 7. **AgentDaemon 轮询效率低**
**位置**: `agent.py:99-101`

```python
while True:
    self.tick()
    time.sleep(self.poll_interval)
```

**问题**:
- 即使没有消息也每 2 秒轮询一次
- 无法在 inbox 为空时阻塞等待
- 多 agent 运行时会产生 N*0.5 QPS 的无效查询

**影响**: CPU 和数据库资源浪费
**建议**: 
- 使用 `SELECT ... WHERE read_at IS NULL AND created_at > ?` 只查询新消息
- 或改为事件驱动架构（webhook + SSE）

---

### 8. **错误处理不一致**
**位置**: 多处 `handle_tool_call`

**问题**:
- 有的返回 `{"error": "..."}` dict
- 有的抛出 `RoundtableError` 异常
- HTTP bridge 需要检查 `"error" not in result`，脆弱

**影响**: 调用方难以统一处理错误
**建议**: 
- 统一错误协议：所有工具返回 `{"ok": bool, "error": str | None, ...}`
- 或者在 MCP 层统一捕获异常转换为标准格式

---

## 🟢 轻微问题 (Minor Issues)

### 9. **类型注解缺失**
**位置**: `orchestrator.py`, `agent.py`

**问题**:
- 新增的 `agent.py` 和 `orchestrator.py` 缺少完整类型注解
- `ManagedOrchestrator.start_discussion` 返回类型未标注
- 多处使用 `dict[str, Any]` 而非 TypedDict

**影响**: IDE 提示不完整，运行时错误风险
**建议**: 添加类型注解并用 mypy 检查

---

### 10. **日志级别使用不当**
**位置**: `generic.py:154`, `codex.py` 等

```python
logger.debug("Webhook delivery failed: %s", e)
```

**问题**:
- webhook 失败用 `debug` 级别，生产环境默认不可见
- 但这是重要的集成失败，应该用 `warning`

**影响**: 运维可观测性差
**建议**: 调整为 `logger.warning("Webhook delivery failed: %s", e)`

---

### 11. **测试覆盖率不足**
**位置**: `tests/test_orchestrator.py`, `tests/test_agent_runtime.py`

**问题**:
- 新增 800+ 行数据库代码，只有 2 个测试文件
- 缺少 dispatch readiness 状态机测试
- 缺少超时和重试逻辑测试
- 缺少并发场景测试

**影响**: 核心功能未充分验证
**建议**: 补充测试覆盖：
- Dispatch 状态转换（pending → active → completed）
- Summon 超时和重试
- 跨进程 web 同步冲突
- Agent 心跳超时检测

---

### 12. **文档与实现不一致**
**位置**: `architecture.md:200`

```markdown
### MCP Tools (21 个)
```

**问题**:
- 文档说 21 个工具，但 `tools.py` 实际只有 15 个左右
- 新增的 `roundtable_summon_agents` 等工具未在文档详细说明

**影响**: 用户困惑
**建议**: 更新架构文档，列出所有工具及用途

---

### 13. **Magic Numbers 散布**
**位置**: 多处

```python
timeout_seconds: int = 60    # dispatch 超时
timeout_seconds: int = 90    # agent 超时
poll_interval: float = 2.0   # 轮询间隔
retry_timeout_seconds: int = 60  # 重试超时
```

**问题**:
- 各种超时值散布在代码中
- 没有统一配置入口
- 难以根据部署环境调优

**影响**: 配置不灵活
**建议**: 提取到配置类或环境变量

---

### 14. **HTTP Bridge 安全性**
**位置**: `codex.py:233-244`, `generic.py:288-299`

**问题**:
- 认证 token 可选 (`auth_token: str | None = None`)
- 默认监听 `127.0.0.1`，但允许改为 `0.0.0.0`
- 没有速率限制，容易被滥用

**影响**: 生产环境暴露风险
**建议**: 
- 强制要求 auth_token（或生成随机 token）
- 添加 rate limiting (例如每分钟 60 次)
- 记录所有 POST 请求审计日志

---

### 15. **JSON 反序列化异常处理不统一**
**位置**: `db.py:664-672`, 多处

```python
@staticmethod
def _loads_json(raw: Any, default: Any = None) -> Any:
    if raw is None or raw == "":
        return default
    if isinstance(raw, (dict, list)):
        return raw
    try:
        return json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return default
```

**问题**:
- 静默吞掉所有解析错误
- 不记录日志，调试困难
- `default=None` 可能掩盖数据损坏

**影响**: 数据损坏时难以发现
**建议**: 至少 log warning，或在开发模式抛出异常

---

## ✅ 做得好的地方 (Good Practices)

1. **幂等性设计**: Dispatch 和 Summon 都支持 idempotency_key
2. **事件审计**: `summon_events` 表记录所有状态变更
3. **Schema 迁移**: 使用 `PRAGMA user_version` 管理迁移
4. **外键约束**: 启用 `PRAGMA foreign_keys=ON`，保证引用完整性
5. **WAL 模式**: 使用 WAL journal mode 提升并发性能
6. **分层架构**: Core/DB/Schema 分离清晰
7. **测试友好**: 支持 `db_path` 参数，方便单元测试

---

## 📋 优先级建议

### 立即修复 (P0)
1. ⚠️ 跨进程 Web 同步竞争 (#1)
2. ⚠️ 幂等性键冲突处理 (#3)

### 下个版本修复 (P1)
3. WebPublisher 生命周期 (#6)
4. 错误处理统一 (#8)
5. 补充测试覆盖 (#11)

### 技术债务 (P2)
6. 数据库索引优化 (#5)
7. AgentDaemon 轮询优化 (#7)
8. 类型注解补全 (#9)
9. HTTP Bridge 安全加固 (#14)

### 代码质量改进 (P3)
10. 心跳超时常量化 (#4)
11. 日志级别调整 (#10)
12. 文档更新 (#12)
13. 配置集中化 (#13)
14. JSON 反序列化日志 (#15)

---

## 🎯 总体评价

**代码质量**: ⭐⭐⭐⭐ (4/5)
- 架构设计清晰，模块职责分明
- 数据库设计合理，支持复杂查询
- 代码风格统一，可读性良好

**测试覆盖**: ⭐⭐⭐ (3/5)
- 核心流程有测试，但覆盖不全面
- 缺少边界情况和并发场景测试
- 建议补充至少 10+ 个测试用例

**生产就绪度**: ⭐⭐⭐ (3/5)
- 功能完整，但存在竞争条件风险
- 需要修复 P0 问题后才能上线
- 建议在 staging 环境压测

**推荐行动**:
1. ✅ 修复跨进程同步问题（使用文件锁或移除 WebPublisher 状态缓存）
2. ✅ 补充测试覆盖（dispatch readiness, timeout, retry）
3. ✅ 添加数据库索引
4. ⏳ 在 staging 环境运行 3-5 天，监控日志
5. ⏳ 完成后再合并到 main 分支

**估计修复时间**: 2-3 天
