"""Skill installer — auto-detect platform and write MCP config."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

CONFIGS_DIR = Path(__file__).parent / "configs"

PLATFORM_PATHS: dict[str, list[Path]] = {
    "claude-code": [
        Path.home() / ".claude" / "mcp.json",
        Path.home() / ".claude.json",
    ],
    "cursor": [
        Path.cwd() / ".cursor" / "mcp.json",
        Path.home() / ".cursor" / "mcp.json",
    ],
    "windsurf": [
        Path.home() / ".codeium" / "windsurf" / "mcp_config.json",
    ],
}


def detect_platforms() -> list[str]:
    """Detect which platforms are installed on this machine."""
    found = []
    if shutil.which("claude"):
        found.append("claude-code")
    if (Path.home() / ".cursor").exists():
        found.append("cursor")
    if (Path.home() / ".codeium" / "windsurf").exists():
        found.append("windsurf")
    return found


def install_for_platform(platform: str) -> str:
    """Install MCP config for a specific platform. Returns the path written."""
    config_file = CONFIGS_DIR / f"{platform}.json"
    if not config_file.exists():
        raise ValueError(f"No config template for platform: {platform}")

    new_config = json.loads(config_file.read_text())
    roundtable_server = new_config.get("mcpServers", {}).get("roundtable")
    if isinstance(roundtable_server, dict):
        roundtable_server["command"] = sys.executable
    paths = PLATFORM_PATHS.get(platform, [])
    if not paths:
        raise ValueError(f"Unknown platform path for: {platform}")

    target = paths[0]
    target.parent.mkdir(parents=True, exist_ok=True)

    if target.exists():
        existing = json.loads(target.read_text())
        servers = existing.get("mcpServers", {})
        servers.update(new_config.get("mcpServers", {}))
        existing["mcpServers"] = servers
        target.write_text(json.dumps(existing, indent=2, ensure_ascii=False))
    else:
        target.write_text(json.dumps(new_config, indent=2, ensure_ascii=False))

    return str(target)


def main() -> None:
    parser = argparse.ArgumentParser(description="Install Roundtable MCP skill for your platform")
    parser.add_argument("--platform", choices=["auto", "claude-code", "cursor", "windsurf"], default="auto")
    args = parser.parse_args()

    if args.platform == "auto":
        platforms = detect_platforms()
        if not platforms:
            print("No supported platforms detected. Install manually from configs/")
            sys.exit(1)
    else:
        platforms = [args.platform]

    for platform in platforms:
        try:
            path = install_for_platform(platform)
            print(f"[ok] {platform}: wrote MCP config to {path}")
        except Exception as e:
            print(f"[error] {platform}: {e}")


if __name__ == "__main__":
    main()
