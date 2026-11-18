# SKILL.md 同步与打包说明

## 仓库中的三个 Skill 文件

| 文件路径 | 定位与职责 | 是否手动编辑 |
|---|---|---|
| `src/skills/SKILL.md` | `agent-roundtable` 技能**唯一真源**（用于 Hermes / OpenClaw / ClawHub） | **是（直接编辑此文件）** |
| `SKILL.md`（仓库根目录） | `src/skills/SKILL.md` 的单向同步副本，供根目录安装与 `clawhub publish .` 读取（`references/` 自动替换为 `src/skills/references/`） | **否（自动生成）** |
| `src/roundtable/skills/mcp-roundtable/SKILL.md` | 随 Python wheel 包分发的 MCP 专用技能（`mcp-roundtable`） | **是（修改 MCP 独立内容时同步更新）** |

> 请勿在 `src/skills/SKILL.md` 正文无关位置写入 `references/` 字样，因为同步脚本会将所有 `references/` 替换为 `src/skills/references/`；也勿在两个 `SKILL.md` 的代码块中出现 `RoundtableCore` 或 `_get_core`（`tests/test_docs_hygiene.py` 会拦截）。

---

## 单向同步工作流 (`scripts/sync_skill.sh`)

本仓库已废弃反向同步（`root2src` 会直接报错退出 `exit 1`），统一采用 **`src/skills/SKILL.md` → 根目录 `SKILL.md`** 的单向同步：

```bash
# 1. 从 src/skills/SKILL.md 同步到根目录 SKILL.md（默认方向，自动替换 references/ 路径）
./scripts/sync_skill.sh src2root

# 2. 查看路径替换后的差异
./scripts/sync_skill.sh diff

# 3. 检查一致性（CI 与发布校验使用）
./scripts/sync_skill.sh check
```

### 配套检查机制

- **本地 Git Hook（`.git/hooks/pre-commit`）**：暂存 `src/skills/SKILL.md` 时自动执行 `./scripts/sync_skill.sh src2root` 并暂存根目录 `SKILL.md`。注意：请勿只编辑并暂存根目录 `SKILL.md`（否则 hook 会尝试已废弃的反向同步）。
- **GitHub Actions CI（`.github/workflows/check-skill-md.yml`）**：在 `push` 和 `pull_request` 时校验 `sed 's|references/|src/skills/references/|g' src/skills/SKILL.md` 与根目录 `SKILL.md` 完全一致。
- **发布版本检查（`scripts/release/preflight-check.sh`）**：校验 `package.json`、`src/roundtable/web/package.json`、`pyproject.toml`、`roundtable.__version__`、`SKILL.md` 和 `src/skills/SKILL.md` 的版本号一致。
