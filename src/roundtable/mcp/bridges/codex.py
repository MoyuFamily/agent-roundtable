"""Codex defaults for the shared host-managed HTTP bridge."""

from __future__ import annotations

from roundtable.mcp.bridges.generic import GenericBridge


class CodexBridge(GenericBridge):
    """Use the common bridge with Codex's platform name and default endpoint.

    The host starts model execution; this bridge does not spawn a CLI or model.
    """

    _summon_source = "codex_bridge"

    def __init__(
        self,
        agent_id: str = "codex-local",
        port: int = 8201,
        host: str = "127.0.0.1",
        display_name: str = "Codex Agent",
        db_path: str | None = None,
        skills: list[str] | None = None,
        availability: str = "idle",
        accept_policy: str = "auto",
        auth_token: str | None = None,
    ):
        super().__init__(
            agent_id=agent_id,
            platform="codex",
            port=port,
            host=host,
            display_name=display_name,
            db_path=db_path,
            skills=skills,
            availability=availability,
            accept_policy=accept_policy,
            auth_token=auth_token,
        )
