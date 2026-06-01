"""Codex-friendly entry points for Roundtable."""

from __future__ import annotations

import argparse
import logging

from roundtable.mcp.bridges.codex import CodexBridge


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Roundtable Codex bridge")
    parser.add_argument("--agent-id", default="codex-local", help="Codex agent identifier")
    parser.add_argument("--port", type=int, default=8201, help="HTTP port (default: 8201)")
    parser.add_argument("--host", default="127.0.0.1", help="HTTP host (default: 127.0.0.1)")
    parser.add_argument("--display-name", default="Codex Agent", help="Human-readable agent name")
    parser.add_argument("--db", type=str, default=None, help="SQLite database path")
    parser.add_argument("--log-level", default="INFO", help="Logging level")
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    logging.basicConfig(level=getattr(logging, args.log_level.upper(), logging.INFO))

    bridge = CodexBridge(
        agent_id=args.agent_id,
        port=args.port,
        host=args.host,
        display_name=args.display_name,
        db_path=args.db,
    )
    bridge.start()

    print(f"Roundtable Codex bridge listening on http://{args.host}:{args.port}")
    print("Use /health, /agent, /inbox, /tool, /speak, /status/<discussion_id>")
    try:
        input("Press Enter to stop...\n")
    except EOFError:
        pass
    finally:
        bridge.stop()


if __name__ == "__main__":
    main()
