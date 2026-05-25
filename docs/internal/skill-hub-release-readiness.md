# Roundtable Skill Hub 发布就绪检查清单

> 状态：发布准备文档。本文覆盖 Hermes Skill Hub 与 OpenClaw/ClawHub 两个 skill 分发渠道。
> **最新更新**：统一重命名为 `agent-roundtable`，避免 ClawHub 同名冲突。

## 1. 发布目标

### 1.1 Hermes Skill Hub

- Skill 名称：`agent-roundtable`
- Skill 路径：仓库根目录 `SKILL.md`（单文件）
- 入口文件：`SKILL.md`（仓库根目录）
- 目标用户：Hermes Agent 用户，希望通过 toolset 使用多 Agent 圆桌讨论能力。
- 发布方式：SKILL.md 直接放在主仓库 `MoyuFamily/roundtable` 根目录，用户通过 URL 安装：
  ```bash
  hermes skills install https://raw.githubusercontent.com/MoyuFamily/roundtable/main/SKILL.md
  ```
- ⚠️ 不使用 `github:owner/repo` 格式安装——ClawHub 上已有同名 `roundtable` skill（作者 @robbyczgw-cla），会导致 `hermes skills install` 优先解析到 ClawHub 缓存而非 GitHub。
- 已废弃独立仓库 `MoyuFamily/hermes-skill-roundtable`（已归档），改为单仓库维护。

### 1.2 OpenClaw / ClawHub

- Skill slug：`agent-roundtable`（避免与 ClawHub 上已有的 `roundtable` 冲突）
- Display name：`Agent Roundtable`
- Version：`1.1.0`（与 `SKILL.md` frontmatter 保持一致）
- 发布方式：`hermes skills publish /tmp/roundtable-skill --to clawhub`
  - ⚠️ CLI 目前不支持直接发布到 ClawHub（提示 "ClawHub publishing is not yet supported"）
  - 需要手动在 https://clawhub.ai/submit 提交
  - 已发布 v1.0.0，moderation CLEAN

## 2. Skill 定位

Roundtable skill 让 Agent 团队围绕一个 topic 进行结构化、多轮圆桌讨论：参与者按轮次发言，系统记录过程、追踪共识/分歧，并输出可沉淀的结论数据。

对 Hermes/OpenClaw 用户，核心价值不是"多一个聊天 prompt"，而是把多 Agent 协作升级为可追踪、可复盘、可结束的会议协议层。

## 3. 发布前 checklist

### 3.1 SKILL.md 元数据

- [x] `SKILL.md` 以 YAML frontmatter 开头。
- [x] `name: agent-roundtable` 存在，且符合 Hermes skill 命名约束。
- [x] `description` 存在且短于 1024 字符。
- [x] `version: 1.1.0` 存在，供 ClawHub 发布使用。
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

- [x] `SKILL.md` 不包含真实 token、密码、私有 webhook、内部聊天 ID 或个人密钥。
- [x] Skill 运行说明不依赖私有团队配置。

### 3.4 CLI 可用性

- [x] 本机存在 Hermes CLI：`hermes skills publish --help` 可用。
- [x] 已确认 URL 安装方式可用。

## 4. 发布命令建议

### 4.1 Hermes Skill Hub

SKILL.md 已放在主仓库根目录，无需单独发布步骤。用户直接通过 URL 安装：

```bash
hermes skills install https://raw.githubusercontent.com/MoyuFamily/roundtable/main/SKILL.md
```

### 4.2 OpenClaw / ClawHub

已发布 v1.0.0（moderation CLEAN）。更新到 v1.1.0 需要：
1. 准备最小发布目录（只含 SKILL.md，避免安全扫描误判）
2. 通过 ClawHub 网站手动提交（CLI 不支持直接发布）

```bash
# 准备最小发布目录
mkdir -p /tmp/roundtable-skill
cp /path/to/SKILL.md /tmp/roundtable-skill/
# 扫描验证
hermes skills publish /tmp/roundtable-skill --to clawhub
# 如果提示手动提交，访问 https://clawhub.ai/submit
```

## 5. 发布后验证 checklist

### 5.1 Hermes Skill Hub

- [x] 主仓库 `MoyuFamily/roundtable` 根目录有 `SKILL.md`。
- [x] URL 安装验证通过。
- [ ] 新会话中 `skill_view(name="agent-roundtable")` 或技能列表可看到该 skill。
- [ ] 启用 `agent-roundtable` toolset 后，工具列表包含 `roundtable_init/read/speak/status/summarize/end/list`。

### 5.2 ClawHub / OpenClaw

- [x] ClawHub 已发布 `agent-roundtable@1.0.0`，moderation CLEAN。
- [ ] ClawHub 搜索 `agent-roundtable` 能看到 skill。
- [ ] `hermes skills install agent-roundtable` 能从 ClawHub 安装。
- [ ] 安装后 `SKILL.md` 内容完整，支持文件未丢失。

## 6. 当前准备结论

- **Hermes Skill Hub**：已就绪。SKILL.md 在主仓库根目录，URL 安装验证通过。
- **ClawHub**：已发布 `agent-roundtable@1.0.0`，moderation CLEAN。v1.1.0 待手动提交。
- **PyPI**：`agent-roundtable` 待上传（429 限速中），cron 自动重试。
- 已废弃独立仓库 `MoyuFamily/hermes-skill-roundtable`（已归档），改为单仓库维护。
- 统一使用 `agent-roundtable` 名称，避免 ClawHub 同名冲突。
