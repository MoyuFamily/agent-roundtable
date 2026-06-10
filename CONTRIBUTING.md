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

### Pull Request 要求

- 确保所有测试通过
- 新功能需要附带测试
- 更新相关文档
- 保持 PR 范围聚焦，一个 PR 解决一个问题

## 行为准则

请参阅 [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)。

## 许可证

提交代码即表示你同意将代码以 [Apache-2.0](LICENSE) 许可证授权。
