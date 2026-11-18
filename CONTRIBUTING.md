# Contributing to Roundtable

感谢你对 Roundtable 的兴趣！文档总览见 [docs/README.md](docs/README.md)。

## 如何贡献

### 报告 Bug

1. 在 [GitHub Issues](https://github.com/MoyuFamily/agent-roundtable/issues) 搜索是否已有类似问题
2. 新建 Issue 并提供：问题描述、复现步骤、期望行为 vs 实际行为、环境信息（Python / Node / OS 版本）

### 提交功能建议

在 Issues 中创建 Feature Request，描述想要的功能、使用场景及建议实现方式。

### 提交代码

1. Fork 本仓库并创建分支：`git checkout -b feat/amazing-feature`
2. 按 [Conventional Commits](https://www.conventionalcommits.org/) 提交：`feat:`、`fix:`、`docs:`、`style:`、`refactor:`、`test:`、`chore:`
3. 运行完整本地检查后创建 Pull Request

## 开发环境

```bash
# 克隆仓库并创建虚拟环境
git clone https://github.com/MoyuFamily/agent-roundtable.git
cd agent-roundtable
python3 -m venv .venv
source .venv/bin/activate

# 安装开发、MCP 与材料提取完整测试依赖
pip install -e ".[dev,mcp,materials]"

# 运行全量测试与静态检查
pytest -q
ruff check src tests scripts/check_mcp_runtime.py
ruff format --check src tests scripts/check_mcp_runtime.py
mypy src

# 如修改了 src/skills/SKILL.md，检查同步一致性
./scripts/sync_skill.sh check
```

### Web Viewer 本地开发

Web Viewer 需要 Node.js >= 18。`create_discussion()` 默认 `web=True` 会尽力启动 Viewer；若本机缺少 Node 或依赖安装失败，核心讨论仍应成功创建，并通过 `web_status`、`web_error`、`web_help` 返回诊断。

```bash
# 安装 Node 依赖并检查语法
npm install --omit=dev
npm run check

# 运行带 Web Viewer 或关闭 Web Viewer 的 demo
python -m roundtable.demo --web
python -m roundtable.demo --no-web
```

`package-lock.json` 是发布输入的一部分，请提交并维护。首跑自动安装只允许写入项目/包可控目录，并保持 `PUPPETEER_SKIP_DOWNLOAD=true`（不自动下载 Chromium；PDF 缺浏览器时返回明确错误）。发布前请运行：

```bash
scripts/release/preflight-check.sh
```

### Web Viewer Schema 迁移 (`discussion.json`)

`discussion.json` 当前为 `schema_version: 3`：

- **v1 → v2**：移除明文 `token` 与 `revoked_tokens`，改存 SHA-256 哈希字段 `token_hash` 与 `revoked_token_hashes`
- **v2 → v3**：新增 `dispatches` 与 `dispatch_summary`，支持 `assembling` 阶段的跨进程召集状态展示

**无需手动迁移**：`server.mjs` 和 `web_publisher.py` / `web_sync.py` 会自动兼容读取旧格式，并在下次写入时完成升级。

## 维护与测试标准

维护者对当前实现及后续修改负责，历史实现不能成为保留已知缺陷的理由。修复时追到根因，清理同一流程中失效的分支、重复逻辑和过时说明；避免为掩盖问题叠加回退、重试或兼容开关。兼容代码必须对应仍需支持的接口或数据，并说明用途与移除条件。涉及用户数据的迁移保留明确的恢复路径。

测试服务于实际行为和重要风险，不以数量或覆盖率作为完成指标：

- 优先验证数据一致性、权限、并发、失败恢复和实际入口；测试应能说明它阻止哪种用户可见的回归。
- 同一场景共用准备和执行过程，合并重复启动服务、浏览器或渲染的测试。仅检查文件存在、字段存在或复制实现分支，不能代替行为验证。
- 测试应允许不改变行为的重构。不要绑定内部函数调用顺序、无关文案或私有实现细节。
- 文案、样式及低风险可逆调整使用适当的静态检查或直接验收，不机械新增测试。
- 回归暴露后先核实行为约定，修复根因；不能通过扩大 skip、放宽关键断言或随意增加 sleep 掩盖失败。
- 修改相关模块时同步审视旧测试，删除或合并无独立保护价值的用例。测试数量下降本身不代表质量下降。

### Pull Request 要求

- 说明问题、最终行为和必要的验证结果，明确尚未验证的边界
- 完成与改动相称的检查，CI 失败仍视为未收尾
- 更新受影响的文档，移除因本次改动失效的说明与测试
- 保持 PR 范围聚焦；必要重构与根因修复一起完成，不堆积临时补丁

## 行为准则与许可证

- 行为准则：[CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)
- 许可证：提交代码即表示同意以 [Apache-2.0](LICENSE) 许可证授权。
