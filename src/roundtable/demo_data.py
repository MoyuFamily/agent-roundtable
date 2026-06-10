from __future__ import annotations

from typing import Any

DEMO_TOPIC: str = "选择后端框架：FastAPI vs Go Gin vs Node Express"
DEMO_PARTICIPANTS: list[dict[str, Any]] = [
    {
        "profile": "alice",
        "role": "全栈工程师",
        "display_name": "Alice",
        "perspective": "重视开发效率和生态",
        "avatar": "👩‍💻",
        "title": "Senior Full-Stack Engineer",
        "description": (
            "10 年全栈经验，主导过多个从零到一的产品架构。擅长 Python/TypeScript 全栈，关注开发者体验和交付效率。"
        ),
    },
    {
        "profile": "bob",
        "role": "架构师",
        "display_name": "Bob",
        "perspective": "重视性能和可维护性",
        "avatar": "🏗️",
        "title": "Principal Architect",
        "description": "分布式系统架构专家，专注于高可用和水平扩展方案。擅长 Go/Rust 技术栈，推崇简洁的系统设计哲学。",
    },
    {
        "profile": "carol",
        "role": "产品经理",
        "display_name": "Carol",
        "perspective": "重视交付速度 and 团队学习成本",
        "avatar": "📊",
        "title": "Product Director",
        "description": "5 年 B 端产品经验，关注技术选型对业务交付的影响。擅长平衡技术理想与业务现实，推动敏捷迭代。",
    },
]
DEMO_SPEECHES: dict[int, dict[str, str]] = {
    1: {
        "alice": (
            "FastAPI 的类型提示和自动生成 OpenAPI 文档太香了，开发效率至少提升 30%。而且 async 原生支持，性能也不差。"
        ),
        "bob": (
            "Go Gin 编译后是原生二进制，内存占用只有 Python 的 1/10。"
            "对于我们这种高并发场景，性能优势明显。"
            "而且 Go 的 goroutine 天然适合并发。"
        ),
        "carol": (
            "从产品角度看，团队 80% 是 Python 背景。"
            "切 Go 需要 3 个月学习周期，这段时间功能迭代会停滞。"
            "FastAPI 能让我们更快交付 MVP。"
        ),
    },
    2: {
        "alice": (
            "同意 Carol 的观点。而且 FastAPI + Pydantic 的数据校验"
            "几乎是零成本的，Go 里要写大量 struct tag 和 binding 代码。"
            "维护成本 FastAPI 更低。"
        ),
        "bob": (
            "性能不能只看 hello world。FastAPI 在 CPU 密集型任务上"
            "还是有 GIL 瓶颈。不过我承认，如果用 asyncio + uvicorn，"
            "IO 密集场景差距没那么大。可以考虑 FastAPI + 分层架构。"
        ),
        "carol": (
            "Bob 说的分层架构我支持。先用 FastAPI 快速上线，"
            "性能瓶颈模块后续可以用 Go 重写微服务。"
            "这才是务实的技术选型策略。"
        ),
    },
    3: {
        "alice": (
            "最终方案：FastAPI 作为主力框架，搭配 Celery 处理异步任务。"
            "性能关键路径预留 Go 微服务接口。这样既保证了开发效率，"
            "又不堵死性能优化的路。"
        ),
        "bob": (
            "我同意这个折中方案。但需要在架构设计阶段就定义好"
            "服务边界和 API 契约，避免后面拆分时返工。"
            "建议第一周就定好领域模型。"
        ),
        "carol": (
            "完美！这样我们两周内就能出 MVP。技术风险可控，团队也不需要额外学习成本。我会把这个方案同步给管理层。"
        ),
    },
}
DEMO_FINDINGS: dict[int, list[tuple[str, str]]] = {
    1: [
        ("consensus", "团队熟悉 Python，学习成本是关键考量因素"),
        ("disagreement", "Go 性能优势 vs FastAPI 开发效率，优先级不同"),
        ("new_point", "需要评估 IO 密集 vs CPU 密集的实际占比"),
    ],
    2: [
        ("consensus", "IO 密集场景下 FastAPI 性能差距可接受"),
        ("consensus", "分层架构是合理的折中方案"),
        ("disagreement", "是否需要在第一阶段就引入 Go 微服务"),
    ],
    3: [
        ("consensus", "采用 FastAPI 主框架 + 预留 Go 微服务扩展"),
        ("consensus", "第一周完成领域模型和 API 契约设计"),
        ("consensus", "两周内交付 MVP，性能瓶颈模块后续迭代"),
    ],
}
