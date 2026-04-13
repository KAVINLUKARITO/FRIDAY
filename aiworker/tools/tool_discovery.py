"""Tool discovery helpers that learn new tools from observed commands."""

from __future__ import annotations

from typing import Iterable

from aiworker.tools.tool_registry import tool_registry


class ToolDiscovery:
    """Learns tool metadata from command observations."""

    def discover(self, commands: Iterable[str]) -> tuple[dict[str, object], ...]:
        discovered = []
        for command in commands:
            name = command.strip().split()[0] if command.strip() else ""
            if not name:
                continue
            capabilities = ("shell",)
            if any(token in command for token in ("test", "pytest", "unittest")):
                capabilities += ("testing",)
            if any(token in command for token in ("rg", "grep", "find")):
                capabilities += ("search",)
            discovered.append(tool_registry.register_tool(name, capabilities=capabilities))
        return tuple(discovered)


tool_discovery = ToolDiscovery()
