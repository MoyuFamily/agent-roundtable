# Agent Roundtable v2 设计规范

> **设计师**：像素姐 🎨 | **日期**：2026-05-27
> **范围**：v2.1 ~ v2.3 全量设计

---

## 1. 设计目标

从「开发者工具」走向「可分享的 AI 讨论平台」：
- **Landing Page** — 项目形象页，GitHub/PyPI 引流
- **讨论模板库** — 降低使用门槛，一键导入讨论模板
- **安全状态 v2** — 过期/密码页面视觉升级
- **WebViewer 细节** — 头像个性化 + 收敛度可视化

---

## 2. 设计语言（延续 + 增强）

### 色彩体系
| Token | 色值 | 用途 |
|-------|------|------|
| `--rt-bg` | `#0F172A` | 主背景 |
| `--rt-surface` | `#1E293B` | 卡片/面板 |
| `--rt-surface-hover` | `#253347` | 悬停态 |
| `--rt-brand` | `#4F46E5` | 品牌主色 |
| `--rt-brand-hover` | `#6366F1` | 品牌悬停 |
| `--rt-accent-green` | `#10B981` | 成功/活跃 |
| `--rt-accent-amber` | `#F59E0B` | 警告/提示 |
| `--rt-accent-red` | `#EF4444` | 错误/过期 |
| `--rt-text-primary` | `#F8FAFC` | 主文字 |
| `--rt-text-secondary` | `#94A3B8` | 次文字 |
| `--rt-text-tertiary` | `#64748B` | 辅助文字 |
| `--rt-border` | `rgba(255,255,255,0.08)` | 边框 |

### Agent 角色色（Tokyo Night 系）
| 角色 | 色值 | 说明 |
|------|------|------|
| Agent 1 | `#7aa2f7` | Tokyo Blue |
| Agent 2 | `#bb9af7` | Tokyo Purple |
| Agent 3 | `#7dcfff` | Tokyo Cyan |
| Agent 4 | `#9ece6a` | Tokyo Green |
| Agent 5 | `#ff9e64` | Tokyo Orange |
| Agent 6 | `#c0caf5` | Tokyo Light |

### 间距 & 圆角
- **网格基准**：8px
- **圆角**：sm 6px / md 10px / lg 16px / xl 24px
- **字体栈**：`-apple-system, 'PingFang SC', 'SF Pro Text', 'Helvetica Neue', sans-serif`
- **图标库**：Lucide Icons（统一 20px，stroke-width 1.5）

### 动效
- 缓动：`cubic-bezier(0.4, 0, 0.2, 1)`
- 时长：hover 150ms / transition 250ms / page 400ms

---

## 3. 交付物清单

| # | 文件 | 说明 | 状态 |
|---|------|------|------|
| 1 | `v2/landing-page.html` | Landing Page 设计稿 | ✅ |
| 2 | `v2/template-library.html` | 讨论模板库 UI | ✅ |
| 3 | `v2/security-v2.html` | 安全状态页 v2 | ✅ |
| 4 | `v2/webviewer-avatar.html` | WebViewer 头像+收敛度 | ✅ |
| 5 | `v2/DESIGN-v2-spec.md` | 本文件 | ✅ |
