# Roundtable Skill Hub 发布就绪检查清单

> 状态：发布前准备文档。本文覆盖 Hermes Skill Hub 与 OpenClaw/ClawHub 两个 skill 分发渠道；不包含任何真实 token，也不触发真实发布。

## 1. 发布目标

### 1.1 Hermes Skill Hub

- Skill 名称：`roundtable`
- Skill 路径：仓库根目录 `SKILL.md`（单文件，与 `src/skills/SKILL.md` 同源）
- 入口文件：`SKILL.md`（仓库根目录）
- 目标用户：Hermes Agent 用户，希望通过 toolset 使用多 Agent 圆桌讨论能力。
- 发布方式：SKILL.md 直接放在主仓库 `MoyuFamily/roundtable` 根目录，用户通过 URL 安装：
  ```bash
  hermes skills install https://raw.githubusercontent.com/MoyuFamily/roundtable/main/SKILL.md
  ```
- ⚠️ 不使用 `github:owner/repo` 格式安装——ClawHub 上已有同名 `roundtable` skill（作者 @robbyczgw-cla），会导致 `hermes skills install` 优先解析到 ClawHub 缓存而非 GitHub。

### 1.2 OpenClaw / ClawHub

- Skill slug：建议使用 `roundtable`
- Display name：`Roundtable`
- Version：`1.0.0`（与 `SKILL.md` frontmatter 保持一致）
- Skill 路径：`src/skills/`
- 发布方式：`clawhub publish src/skills --slug roundtable --name "Roundtable" --version 1.0.0`

> 注意：ClawHub CLI 当前命令是 `clawhub publish <path>`，不是旧文档里的 `clawhub skill publish ...`。

## 2. Skill 定位

Roundtable skill 让 Agent 团队围绕一个 topic 进行结构化、多轮圆桌讨论：参与者按轮次发言，系统记录过程、追踪共识/分歧，并输出可沉淀的结论数据。

对 Hermes/OpenClaw 用户，核心价值不是“多一个聊天 prompt”，而是把多 Agent 协作升级为可追踪、可复盘、可结束的会议协议层。

## 3. 发布前 checklist

### 3.1 SKILL.md 元数据

- [x] `SKILL.md` 以 YAML frontmatter 开头。
- [x] `name: roundtable` 存在，且符合 Hermes skill 命名约束。
- [x] `description` 存在且短于 1024 字符。
- [x] `version: 1.0.0` 存在，供 ClawHub 发布使用。
- [x] `platforms: [linux, macos, windows]` 存在。
- [x] `metadata.hermes.tags` 和 `metadata.hermes.related_skills` 存在。
- [x] `metadata.openclaw` 存在，声明无必需 env/bin 依赖。

### 3.2 内容质量

- [x] Overview 清楚说明圆桌讨论价值。
- [x] When to Use 覆盖技术评审、竞品分析、根因分析、产品需求、架构决策等场景。
- [x] Tools 表列出 `roundtable_init/read/speak/status/summarize/end/list`。
- [x] Coordinator Flow 给出创建讨论、多轮发言、收敛检查、总结、结束讨论流程。
- [x] Participant Prompt Template 可直接复用。
- [x] Pitfalls 记录参与者数量、注册发言者、Round 0、独立 DB、summarize 不调用 LLM 等注意事项。

### 3.3 打包与敏感信息

- [x] `src/skills/.clawhubignore` 已添加，排除缓存、构建产物、`.env`、数据库、本仓库内部材料等。
- [x] Skill 目录只包含文本文件：`SKILL.md` 与 `.clawhubignore`。
- [x] `SKILL.md` 不包含真实 token、密码、私有 webhook、内部聊天 ID 或个人密钥。
- [x] Skill 运行说明不依赖私有团队配置。

### 3.4 CLI 可用性

- [x] 本机存在 Hermes CLI：`hermes skills publish --help` 可用。
- [x] 本机存在 ClawHub CLI：`clawhub publish --help` 可用。
- [x] 已确认 ClawHub 发布命令形态：`clawhub publish src/skills --slug roundtable --name "Roundtable" --version 1.0.0`。
- [x] 已确认 ClawHub 登录状态：当前本机未登录，`clawhub whoami` 返回 `Error: Not logged in. Run: clawhub login`；真实发布前必须先登录目标账号。
- [ ] 尚未执行真实发布；需 Boss 明确确认目标账号/owner 后进行。

## 4. 发布命令建议

### 4.1 Hermes Skill Hub

SKILL.md 已放在主仓库根目录，无需单独发布步骤。用户直接通过 URL 安装：

```bash
hermes skills install https://raw.githubusercontent.com/MoyuFamily/roundtable/main/SKILL.md
```

> 已废弃的方案：原先维护独立仓库 `MoyuFamily/hermes-skill-roundtable`，因维护两仓库易不同步，改为单仓库 + URL 安装。

### 4.2 OpenClaw / ClawHub

```bash
clawhub whoami
clawhub publish src/skills \
  --slug roundtable \
  --name "Roundtable" \
  --version 1.0.0 \
  --tags discussion,multi-agent,collaboration,debate,roundtable \
  --changelog "Initial Roundtable skill release for structured multi-agent discussions."
```

如需要发布到组织/owner，发布前先确认当前 ClawHub 账号是否拥有对应权限；当前 CLI help 未显示 `--owner` 参数，需以登录账号权限为准。

## 5. 发布后验证 checklist

### 5.1 Hermes Skill Hub

- [x] 主仓库 `MoyuFamily/roundtable` 根目录有 `SKILL.md`。
- [x] `hermes skills install https://raw.githubusercontent.com/MoyuFamily/roundtable/main/SKILL.md` 能安装到干净 profile。
- [ ] 新会话中 `skill_view(name="roundtable")` 或技能列表可看到该 skill。
- [ ] 启用 `roundtable` toolset 后，工具列表包含 `roundtable_init/read/speak/status/summarize/end/list`。

### 5.2 ClawHub / OpenClaw

- [ ] ClawHub 搜索 `roundtable` 能看到 skill。
- [ ] `clawhub inspect roundtable` 能显示 `name/version/description/tags`。
- [ ] `openclaw skills install roundtable` 或 ClawHub 对应 install 命令能安装。
- [ ] OpenClaw 侧读取 `metadata.openclaw.requires` 正常，不提示缺失必需 env/bin。
- [ ] 安装后 `SKILL.md` 内容完整，支持文件未丢失。

## 6. 当前准备结论

- **Hermes Skill Hub**：已就绪。SKILL.md 在主仓库根目录，URL 安装验证通过。
- **ClawHub**：已发布 `agent-roundtable@1.0.0`，moderation CLEAN。
- **PyPI**：`agent-roundtable` 待上传（429 限速中），cron 自动重试。
- 已废弃独立仓库 `MoyuFamily/hermes-skill-roundtable`，改为单仓库维护。
