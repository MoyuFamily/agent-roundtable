# agent-roundtable PyPI 发布就绪检查清单

> 状态：发布前准备文档。本文只记录定位、卖点和操作清单，不包含任何真实 PyPI/TestPyPI token，也不触发真实发布。

## 1. 发布目标

### 1.1 对外包名

- PyPI 包名：`agent-roundtable`
- 安装命令：`pip install agent-roundtable`
- 导入模块：`roundtable`
- 版本目标：首个公开版本从 `0.1.0` 起步，强调 MVP 可用、API 轻量、可嵌入现有 Agent 工作流。

### 1.2 一句话定位

`agent-roundtable` 是一个框架无关的多 Agent 圆桌讨论引擎：开发者只需要定义话题、参与者和轮次，它负责顺序发言、过程记录、共识/分歧追踪和结构化总结。

从产品角度来说，用户要的不是“多几个 Agent 说话”的钻头，而是“复杂问题能被多角色讨论清楚，并留下可追溯结论”的洞。PyPI 页面和 README 首屏要优先讲清楚这个洞。

### 1.3 发布目标

1. 让 PyPI/GitHub 首屏 10 秒内讲清楚“这是多 Agent 讨论协议层，不是聊天机器人，也不是某个封闭 Agent 平台”。
2. 让开发者能复制 `pip install agent-roundtable` 和 README Quick Start 快速完成本地验证。
3. 让 Hermes Agent 用户理解它可以作为 toolset/adapter 接入，同时让非 Hermes 用户也能把它当普通 Python 库使用。
4. 为明天正式发布预留清晰的人工作业步骤：账号、token/Trusted Publishing、构建、上传、验证。

## 2. 用户画像与核心场景

### 2.1 目标用户

| 用户类型 | 典型问题 | `agent-roundtable` 提供的价值 |
|---|---|---|
| AI Agent 框架开发者 | 多个 Agent 能发言，但缺少可复用的讨论流程和记录结构 | 提供 topic、participants、rounds、summary 的轻量协议层 |
| 自动化工作流构建者 | 需要让产品、设计、开发、安全等角色围绕任务收敛 | 固化顺序发言、共识/分歧追踪和最终结论沉淀 |
| 技术团队/开源维护者 | 评审过程分散在聊天记录里，难以复盘 | 用 SQLite 持久化讨论记录，输出结构化决策摘要 |
| Hermes Agent 用户 | 需要把多 Agent 协作从一次性对话升级为可追踪会议 | 通过 adapter/toolset 接入 Hermes，沉淀为可查询讨论 |

### 2.2 核心使用场景

- 多 Agent 圆桌讨论：为一组专家角色创建同一议题下的多轮讨论。
- 顺序发言管理：明确参与者、当前轮次和发言顺序，减少上下文混乱。
- 会议记录沉淀：记录每次发言、状态变化、收敛度和最终结论。
- 团队协作决策：产品、设计、开发、增长、安全等角色围绕 MVP、架构或 Review 形成可追踪决策。

## 3. PyPI 页面卖点清单

### 3.1 首屏必须出现的信息

- 包名和安装：`pip install agent-roundtable`
- 一句话价值：让多个 AI Agent 像开圆桌会一样按轮次讨论、记录观点、追踪共识分歧并生成结论。
- 最小示例：创建讨论、发言、查看收敛度、生成总结、结束讨论。
- 关键差异：框架无关、核心零外部依赖、SQLite 持久化、可接 Hermes Agent。

### 3.2 建议卖点表达

1. Structured multi-agent discussion — 不是简单广播消息，而是有参与者、轮次、状态和结论的会议模型。
2. Consensus/disagreement tracking — 讨论不是越长越好，产品上要能判断是否收敛。
3. Durable meeting memory — 每次发言和总结可持久化，适合 PRD、架构评审、代码 Review、决策记录。
4. Framework agnostic — 可以独立作为 Python 库，也可以通过 adapter 接入 Hermes Agent 或其他 Agent 框架。
5. Zero-dependency core — 核心库只依赖 Python 标准库，降低引入门槛和部署风险。

### 3.3 README/PyPI 文案一致性要求

- 安装命令统一写作：`pip install agent-roundtable`。
- 避免暗示 `roundtable` 是 PyPI 包名；`roundtable` 只作为 import module 出现。
- 如提到 `roundtable` / `roundtable-ai`，必须说明它们不是本项目包名。
- 对外定位保持“多 Agent 圆桌讨论引擎”，不要泛化成“聊天框架”或“Agent 编排平台”。

## 4. 发布前 checklist

### 4.1 产品与文档

- [x] README 首屏已说明 Roundtable 的多 Agent 圆桌讨论价值。
- [x] README 安装区展示 `pip install agent-roundtable`。
- [x] README 说明 PyPI 上 `roundtable` / `roundtable-ai` 不是本项目。
- [x] README Quick Start 覆盖创建讨论、顺序发言、查看状态、总结、结束讨论。
- [x] 本文档记录目标用户、卖点、发布前/发布当天/发布后 checklist。
- [x] 设计侧确认 PyPI/GitHub Markdown 展示层级和可读性。
- [ ] 工程侧确认 PyPI 元数据是否需要补充 authors、keywords、classifiers、project.urls。

### 4.2 工程与构建

- [x] `pyproject.toml` 中 `[project].name` 使用 `agent-roundtable`。
- [ ] `python -m build` 能生成 sdist 和 wheel。
- [ ] `twine check dist/*` 通过。
- [ ] 临时 venv 能从本地 wheel 安装，并验证 `import roundtable`。
- [ ] 发布 workflow 或手动发布命令已准备好，但不会自动发布。
- [ ] 未创建 release tag，未上传 PyPI/TestPyPI。

### 4.3 风险检查

- [x] 文档中没有真实 token、密码、账号密钥或私有 webhook。
- [x] README 没有引导用户安装错误包名 `roundtable`。
- [ ] dist 产物不包含无关内部文件、缓存、`.env` 或测试临时数据。
- [ ] 发布版本号、CHANGELOG、LICENSE、SECURITY 信息已与首发版本一致。

## 5. 发布当天 Boss 需要完成的账号/token 步骤

> 只列步骤，不记录真实 token。token 应只放在本机安全凭据、环境变量或 GitHub Actions Secrets 中。

### 5.1 PyPI 账号准备

1. 注册或登录 PyPI 账号：https://pypi.org/
2. 开启两步验证（2FA），优先使用认证器 App 或安全密钥。
3. 确认账号邮箱已验证。
4. 如项目未来需要多人维护，发布后再在 PyPI 项目页面添加 maintainer。

### 5.2 API Token 准备

1. 在 PyPI Account settings 中创建 API token。
2. 首次发布前如果无法选择 project-scoped token，可临时创建 account-scoped token；首发成功后建议改为 project-scoped token。
3. token 只复制一次，不要写入仓库、文档、聊天记录或 issue。
4. 本地发布时，使用环境变量或 `~/.pypirc` 的安全配置；CI 发布时，写入 GitHub Actions Secrets。

### 5.3 本地发布命令建议

发布当天由技术负责人在确认构建产物后执行，示例只展示命令形态：

```bash
python -m build
python -m twine check dist/*
python -m twine upload dist/*
```

注意：以上命令今天不执行上传；只有 Boss 确认账号/token 后再执行真实发布。

## 6. 发布后验证 checklist

### 6.1 PyPI 页面验证

- [ ] PyPI 项目 URL 可访问，项目名为 `agent-roundtable`。
- [ ] 页面首屏能看懂：这是多 Agent 圆桌讨论引擎。
- [ ] README 渲染正常，表格、代码块、图片链接无明显异常。
- [ ] 安装命令显示为 `pip install agent-roundtable`。
- [ ] 页面没有出现真实 token、内部账号、临时路径等敏感信息。

### 6.2 安装验证

建议在干净虚拟环境中验证：

```bash
python -m venv /tmp/roundtable-pypi-verify
source /tmp/roundtable-pypi-verify/bin/activate
pip install agent-roundtable
python - <<'SMOKE'
from roundtable import RoundtableCore
core = RoundtableCore()
print(core.create_discussion(topic='smoke test', participants=[{'profile': 'a', 'role': 'A'}]))
SMOKE
```

验收点：

- [ ] `pip install agent-roundtable` 成功。
- [ ] `from roundtable import RoundtableCore` 成功。
- [ ] 最小讨论创建成功并返回 discussion_id。
- [ ] README 示例代码与实际包行为一致。

### 6.3 发布运营动作

- [ ] GitHub README 与 PyPI 页面叙事一致。
- [ ] 如创建 GitHub Release，release note 与 PyPI 版本号一致。
- [ ] 在项目主页、团队群或社媒发布时统一使用包名 `agent-roundtable`。
- [ ] 收集首批用户反馈：安装是否顺畅、定位是否清楚、Quick Start 是否可复现。

## 7. 风险与应对

| 风险 | 影响 | 应对 |
|---|---|---|
| 用户误装 `roundtable` | 安装到其他项目，首体验失败 | README 和 PyPI 首屏明确官方包名 `agent-roundtable` |
| 包名与 import 名不同 | 新用户困惑 | 安装文档说明“包名 agent-roundtable，import 名 roundtable” |
| 长描述渲染异常 | PyPI 页面可信度下降 | 发布前执行 twine check |
| 首发后才发现元数据错误 | 需要补丁版本 | 发布前复核 pyproject、README 和构建产物 |
| token 泄露 | 安全事故 | token 不入库，只使用安全凭据或 Secrets |

## 8. 当前准备结论

当前产品定位已经可以支撑 PyPI 首发：agent-roundtable 不是泛泛的“讨论工具”，而是面向 AI Agent 系统的圆桌会议协议层。首发叙事建议聚焦三个关键词：多 Agent 圆桌讨论、顺序发言与会议记录、结构化结论沉淀。

剩余人工步骤主要是 Boss 明天完成 PyPI 账号、2FA 与 API token，然后由技术负责人执行构建、检查和上传。
