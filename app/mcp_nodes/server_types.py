"""Shared structural types for MCP node configuration."""
from __future__ import annotations

from typing import Any, Mapping, Protocol


class NodeAuthConfig(Protocol):
    node_id: str
    port: int
    defaults: Mapping[str, Any]
    datapoints: Mapping[str, Mapping[str, Any]]
    experts: tuple[Mapping[str, Any], ...]
    calendar_windows: tuple[Mapping[str, str], ...]