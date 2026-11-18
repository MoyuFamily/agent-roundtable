<p align="center">
  <img src="https://raw.githubusercontent.com/MoyuFamily/agent-roundtable/main/docs/design/assets/svg/roundtable-logo.svg" alt="Roundtable" width="128" height="128">
</p>

<h1 align="center">Roundtable</h1>

<p align="center">
  <strong>把杂乱材料变成有依据、能取舍、可更新的决策建议与 Code Review 结论。</strong>
</p>

<p align="center">
  <a href="docs/TECHNICAL_RELIABILITY.md"><img src="https://img.shields.io/badge/tests-passing-brightgreen.svg" alt="Tests"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-Apache--2.0-blue.svg" alt="License: Apache-2.0"></a>
  <a href="https://www.python.org/downloads/"><img src="https://img.shields.io/badge/python-3.10+-blue.svg" alt="Python 3.10+"></a>
  <a href="#快速开始"><img src="https://img.shields.io/badge/core-zero_dependencies-brightgreen.svg" alt="Zero Dependencies"></a>
</p>

<p align="center">
  <strong><a href="README.md">中文</a> · <a href="README_EN.md">English</a></strong>
</p>

<p align="center">
  <img src="https://raw.githubusercontent.com/MoyuFamily/agent-roundtable/main/docs/design/assets/demo.gif" alt="Roundtable Demo" width="600">
</p>

---

## 这是什么

Roundtable 是一个轻量的多角色决策与评审协议层（PyPI 包名 `agent-roundtable`，Python 导入名 `roundtable`）。它围绕**输入处理**（提炼决策相关事实、保留来源与未知、分段读取原文）和**输出质量**（交付清晰、有取舍、可追溯、可随新信息更新的建议）来组织评审流程。

| 分层 | 职责边界 |
|------|----------|
| **角色与用户** | 角色定义专业视角与检查重点；用户设定目标、偏好并作出最终决定 |
| **宿主与 Agent** | 宿主运行 Agent、选择模型、提炼和核实材料并综合结论；Roundtable 不自动调用模型或自动组队 |
| **Roundtable 引擎** | 使用零外部依赖的 Python 标准库与 SQLite 持久化会议轮次、版本化简报/证据/材料、校验引用、渲染统一报告并提供实时 Web Viewer |

> 多角色、多 Agent 与多模型是补足盲区的手段，而非默认前提；简单查询或低风险选择可直接由单个助手完成。详细产品定位与实测记录见 [产品方向](docs/product/DIRECTION.md)。

## 快速开始

### 1. 安装

```bash
pip install agent-roundtable
```

验证当前源码分支时可从源码安装：

```bash
git clone https://github.com/MoyuFamily/agent-roundtable.git
cd agent-roundtable
pip install -e .
```

| 可选扩展 | 安装命令 | 用途 |
|----------|----------|------|
| `mcp` | `pip install "agent-roundtable[mcp]"` | MCP Server（stdio / HTTP-SSE）及客户端自动安装 |
| `materials` | `pip install "agent-roundtable[materials]"` | 本地 PDF 逐页文本提取（`pypdf`，无 OCR） |
| `web` | `pip install "agent-roundtable[web]"` | 使用 `nanoid` 生成 Web Viewer 访问令牌（默认自动回退标准库） |
| `dev` | `pip install -e ".[dev,mcp,materials]"` | 本地开发测试、Ruff 检查与 Mypy 类型检查 |

> 注意：本项目的 PyPI 包名是 **`agent-roundtable`**。`roundtable` / `roundtable-ai` 并非本项目，请勿误装。

### 2. 跨平台 Agent 接入

- **MCP 客户端（Claude Code / Cursor / Windsurf）**：
  ```bash
  pip install -e ".[mcp]" "mcp>=1,<2"
  python3 -m roundtable.skills.mcp-roundtable.install --platform=auto
  ```
- **HTTP Bridge（Codex / WorkBuddy 等 HTTP 宿主）**：
  ```bash
  python3 -m roundtable.codex  # 默认监听 http://127.0.0.1:8201
  ```
- **Hermes Agent**：在配置中启用 `toolsets: [roundtable]`。

运行态 AI 调用规范见 [SKILL.md](SKILL.md) 与 [MCP Skill](src/roundtable/skills/mcp-roundtable/SKILL.md)。

### 3. Python 最小示例

以下示例演示如何用 `RoundtableCore` 记录一次评审（实际评审由宿主运行各角色 Agent 并提交发言）：

```python
from roundtable import RoundtableCore

core = RoundtableCore()

# 1. 创建讨论（默认 web=True，尽力启动本地 Web Viewer，失败不阻断讨论）
result = core.create_discussion(
    topic="选择数据库：PostgreSQL vs MySQL vs TiDB",
    participants=[
        {"profile": "backend_architect", "role": "后端架构师"},
        {"profile": "ops_engineer", "role": "运维工程师"},
        {"profile": "product_manager", "role": "产品经理"},
    ],
    max_rounds=3,
)
disc_id = result["discussion_id"]

# 2. 协调者开场（round 0 保留给 coordinator）并记录参与者发言
core.speak(disc_id, "coordinator", "开场：请结合业务建模复杂度与运维成本比较三套方案。")
core.speak(disc_id, "backend_architect", "PostgreSQL 的 JSON 与事务能力更适合复杂业务建模。")
core.speak(disc_id, "ops_engineer", "团队对 MySQL 工具链更熟，迁移成本需要实测。")
core.speak(disc_id, "product_manager", "优先保证半年内的功能迭代扩展空间。")

# 3. 获取格式化摘要并记录建议（区分“建议”与“用户已确认决定”）
summary = core.summarize(disc_id, compact=True)
core.end_discussion(
    disc_id,
    conclusion="建议采用 PostgreSQL；待核实迁移与运维成本，等待用户确认。",
)
```

- **Web Viewer**：需 Node.js 18+，返回值含 `web_status`（`ready` / `failed` / `disabled`）、`web_url`、`web_error`、`web_help`。Markdown 导出始终可用；PDF 导出可通过 `PUPPETEER_EXECUTABLE_PATH` 指定已有 Chrome/Chromium。
- **错误安全模式**：生产宿主可使用 `from roundtable.adapters.generic import Roundtable`，所有方法均返回 `dict`（错误为 `{"error": "..."}`，不抛异常）。

## 适用场景

以下七类场景共用同一套简报、证据、独立分析与交叉回应流程（按问题增减角色与轮次，详见 [场景清单](docs/product/DIRECTION.md#场景清单)）：

- **项目去留与方向**：继续维护、调整或停止，明确投入边界与复审条件
- **产品范围与优先级**：目标用户、MVP 边界、优先级依据与暂缓项
- **技术路线**：自研或采购、架构选型、迁移与长期维护取舍
- **发布与实施**：上线条件、阻塞项、实施步骤与回滚方案
- **资源与商业模式**：预算人力分配，免费、订阅或按量计费对比
- **工作流程与工具选择**：对照现有基线，权衡工具收益与迁移培训成本
- **Code Review**：围绕具体代码改动检查正确性、架构、安全与可靠性，输出带定位和证据的合并建议

## 文档导航

| 文档 | 内容说明 |
|------|----------|
| [docs/README.md](docs/README.md) | 全部文档总览与阅读入口 |
| [docs/DECISION_WORKFLOW.md](docs/DECISION_WORKFLOW.md) | 决策与 Code Review 指南：六步流程、本地材料导入、内置模板、结构化证据与报告 |
| [docs/INTEGRATION_AND_API.md](docs/INTEGRATION_AND_API.md) | 接入方式与参考：`RoundtableCore`、Generic Facade、Hermes、MCP、HTTP Bridge、自定义 Adapter 与环境变量 |
| [docs/architecture.md](docs/architecture.md) | 系统架构：模块分层、状态机、27 个 MCP 工具、Schema v7 与部署形态 |
| [docs/TECHNICAL_RELIABILITY.md](docs/TECHNICAL_RELIABILITY.md) | 可靠性工程：消息确认协议、MCP 跨进程订阅、文件锁与隔离 PDF 导出 |
| [docs/product/DIRECTION.md](docs/product/DIRECTION.md) | 产品方向、能力边界与 [Code Review 验收记录](docs/product/CODE_REVIEW_ACCEPTANCE.md) |

> 注：以上文档反映当前源码状态；使用已发布的 PyPI 包时请核对对应版本的能力说明。

## 贡献与团队

欢迎通过 Issue 与 Pull Request 参与贡献，环境配置、测试命令与代码规范见 [CONTRIBUTING.md](CONTRIBUTING.md)。

| 成员 | 角色 | 说明 |
|------|------|------|
| <img src="https://avatars.githubusercontent.com/u/286716759?v=4" width="24" height="24" style="border-radius:50%"> 饼哥 | 产品总监 | 把模糊需求变成可落地的方案，关注真实用户问题 |
| <img src="https://avatars.githubusercontent.com/u/286719582?v=4" width="24" height="24" style="border-radius:50%"> 像素姐 | 设计总监 | 品牌视觉、信息架构与交互细节设计 |
| <img src="https://avatars.githubusercontent.com/u/286715358?v=4" width="24" height="24" style="border-radius:50%"> 码飞 | 技术总监 | 系统架构、工程可靠性与跨平台集成落地 |
| <img src="https://avatars.githubusercontent.com/u/286714101?v=4" width="24" height="24" style="border-radius:50%"> 小赫 | 协调者 | 团队协作统筹与多角色评审流程推进 |

[Apache-2.0](LICENSE)
