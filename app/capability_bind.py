"""Copy each tool's Capabilities line onto the input schema.

The Tool Registry reads x-datumbridge-capabilities from tools/list. A server-wide
catalog list is not used when this key is present.
"""

from __future__ import annotations


def capabilities_from_description(description: str) -> list[str]:
    for line in (description or "").splitlines():
        line = line.strip()
        if line.lower().startswith("capabilities:"):
            rest = line.split(":", 1)[1]
            return [part.strip() for part in rest.split(",") if part.strip()]
    return []


def bind_declared_capabilities(mcp) -> None:
    manager = getattr(mcp, "_tool_manager", None)
    tools = getattr(manager, "_tools", None) or {}
    for tool in tools.values():
        name = getattr(tool, "name", "") or "tool"
        caps = capabilities_from_description(getattr(tool, "description", "") or "")
        if not caps:
            caps = [name]
        params = dict(getattr(tool, "parameters", None) or {})
        params["x-datumbridge-capabilities"] = caps
        tool.parameters = params
