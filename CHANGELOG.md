# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

## [2.0.0] - 2026-05-27

### Added

- **平台通知集成** — 框架无关的通知分发器 (Notifier)，支持多频道、多事件类型 (round_start / speech / round_end / concluded)
- **讨论链接安全增强** — 链接过期时间 (expires_at) + 访问密码保护 (bcryptjs)
- **Schema Version** — discussion.json 新增 schema_version 字段，区分新旧数据格式
- **Open Graph 预览卡片** — Web Viewer 分享链接自动生成 og:title / og:description，社交平台可预览讨论内容
- **Agent 人格可视化** — 基于角色类型的 CSS 变量着色 (role-based avatar colors)
- **收敛度可视化** — convergence-bar 组件，带百分比进度展示
- **适配器框架** — 支持接入不同 Agent 框架 (Hermes / Generic / Simple)
- **Landing Page** — 静态介绍页，部署至 roundtable.izmw.me
- **讨论回放** — token_stream.jsonl 流式回放支持
- **发布自动化** — PyPI + ClawHub + Hermes Skill Hub + GitHub Release 一键发布

### Changed

- 版本号从 1.2.4 升级至 2.0.0 正式版
- cross-process 同步改用 float 时间戳防止 stale 数据覆盖
- 讨论状态文件写入采用原子操作 + advisory file lock
- 最终 summary 支持 verdict 变更后更新

### Fixed

- 并发写入 discussion.json 时 round summaries 覆盖问题
- cross-process replay 中 token_stream.jsonl fallback 写入
- 通知消息内容截断逻辑

## [0.1.0] - 2026-05-25

### Added

- 圆桌讨论核心功能 — 多角色 AI Agent 协作讨论框架
- 多角色 Agent 协作 — 支持自定义角色组合与讨论策略
- WebViewer 实时查看 — 浏览器实时查看讨论过程与结果
- 飞书通知集成 — 讨论完成自动推送飞书消息
- Hermes Skill Hub 分发 — 作为 Hermes Skill 安装使用
