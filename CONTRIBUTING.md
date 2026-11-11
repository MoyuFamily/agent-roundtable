# Contributing to Roundtable

感谢你对 Roundtable 的兴趣！我们欢迎各种形式的贡献。

## 如何贡献

### 报告 Bug

1. 在 [GitHub Issues](https://github.com/MoyuFamily/agent-roundtable/issues) 中搜索是否已有类似问题
2. 如果没有，创建一个新的 Issue，包含：
   - 问题描述
   - 复现步骤
   - 期望行为 vs 实际行为
   - 环境信息（Python 版本、OS 等）

### 提交功能建议

在 Issues 中创建 Feature Request，描述：
- 你想要的功能
- 使用场景
- 建议的实现方式（可选）

### 提交代码

1. Fork 本仓库
2. 创建你的特性分支：`git checkout -b feat/amazing-feature`
3. 提交你的改动：`git commit -m 'feat: add amazing feature'`
4. 推送到分支：`git push origin feat/amazing-feature`
5. 创建 Pull Request

### Commit 规范

使用 [Conventional Commits](https://www.conventionalcommits.org/) 格式：

- `feat:` 新功能
- `fix:` Bug 修复
- `docs:` 文档更新
- `style:` 代码格式（不影响逻辑）
- `refactor:` 重构
- `test:` 测试相关
- `chore:` 构建/工具链

### 开发环境

```bash
# 克隆仓库
git clone https://github.com/MoyuFamily/agent-roundtable.git
cd agent-roundtable

# 创建虚拟环境
python -m venv .venv
source .venv/bin/activate

# 安装依赖
pip install -e ".[dev]"

# 运行测试
pytest

# 运行单个测试文件 / 特定测试
pytest tests/test_core.py
pytest tests/test_core.py::TestCreateDiscussion -v

# 运行 lint
ruff check src tests
ruff format --check src tests

# 类型检查
mypy src
```

### Web Viewer 本地开发

Web Viewer 需要 Node.js >= 18。`create_discussion()` 默认会以 `web=True` 尽力启动 Viewer；如果 Node 不存在或依赖安装失败，核心讨论仍应创建成功，并通过 `web_status`、`web_error`、`web_help` 返回诊断。

```bash
# 安装 Node 依赖
npm install

# 检查 Web Viewer 语法
npm run check

# 运行带 web viewer 的 demo
python -m roundtable.demo --web

# 或显式关闭 web viewer
python -m roundtable.demo --no-web
```

`package-lock.json` 是发布输入的一部分，请提交并维护。首跑自动安装只允许写入项目/包可控目录；不要在代码里无提示安装全局 npm 包。自动安装会设置 `PUPPETEER_SKIP_DOWNLOAD=true`，避免首跑下载 Chromium；PDF 导出缺浏览器时应返回明确错误。

可选 Python 依赖（web 功能）：`nanoid`，通过 `pip install -e ".[web]"` 安装。Node 依赖（server.mjs）：`bcryptjs`、`md-to-pdf`，已在 `package.json` 中声明；普通运行可用 `npm install --omit=dev`。

发布前请运行：

```bash
scripts/release/preflight-check.sh
```

### Web Viewer Schema 迁移

`discussion.json` 从 schema_version 1 升级到 2 时有以下变更：

- `token` 字段已移除，改为存储 `token_hash`（SHA-256 哈希）
- `revoked_tokens` 字段已移除，改为 `revoked_token_hashes`

**无需手动迁移**：server.mjs 和 web_publisher.py 会自动检测旧格式并在下次写入时升级。旧的 discussion.json 文件在被访问时会自动转换为新格式。

### 维护与测试标准

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

## 行为准则

请参阅 [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)。

## 许可证

提交代码即表示你同意将代码以 [Apache-2.0](LICENSE) 许可证授权。
