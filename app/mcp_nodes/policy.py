"""Fail-closed node-side policy decisions for datapoint access."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Literal, Mapping

from mcp_nodes.auth import CallerContext
from mcp_nodes.server_types import NodeAuthConfig

DecisionCode = Literal[
    "ALLOWED",
    "ALLOWED_SUMMARY_ONLY",
    "NEEDS_APPROVAL",
    "BLOCKED_BY_POLICY",
]
ExposureMode = Literal["MD", "SUM", "RAG", "LIVE"]

_ALLOWED_BY_CEILING: dict[str, set[str]] = {
    "MD": {"MD"},
    "SUM": {"MD", "SUM"},
    "RAG": {"MD", "SUM", "RAG"},
    "LIVE": {"MD", "LIVE"},
}


@dataclass(frozen=True)
class PolicyDecision:
    code: DecisionCode
    rule_id: str
    reason: str
    mode: str


def authorize_caller(config: NodeAuthConfig, caller: CallerContext) -> PolicyDecision:
    defaults = config.defaults
    allowed_roles = set(defaults.get("roles_allowed", []))
    if not caller.roles.intersection(allowed_roles):
        return PolicyDecision("BLOCKED_BY_POLICY", "R-ROLE-01", "Caller role is not allowed", "MD")
    if caller.purpose not in defaults.get("purposes_allowed", []):
        return PolicyDecision("BLOCKED_BY_POLICY", "R-PURPOSE-01", "Purpose is not allowed", "MD")
    return PolicyDecision("ALLOWED", "R-CALLER-01", "Caller is authorized", "MD")


def evaluate_access(
    config: NodeAuthConfig,
    caller: CallerContext,
    datapoint_id: str,
    requested_mode: str,
    *,
    as_of: date | None = None,
    grant_mode: str | None = None,
) -> PolicyDecision:
    caller_decision = authorize_caller(config, caller)
    if caller_decision.code == "BLOCKED_BY_POLICY":
        return caller_decision

    datapoint = config.datapoints.get(datapoint_id)
    if datapoint is None:
        return PolicyDecision("BLOCKED_BY_POLICY", "R-DP-UNKNOWN", "Unknown datapoint", "MD")

    rule_id = str(datapoint.get("rule_id", "R-EXPOSURE-01"))

    purposes = datapoint.get("purposes_allowed")
    if purposes and caller.purpose not in purposes:
        return PolicyDecision("BLOCKED_BY_POLICY", "R-PURPOSE-01", "Purpose is not allowed for this datapoint", "MD")

    if requested_mode not in _ALLOWED_BY_CEILING:
        return PolicyDecision("BLOCKED_BY_POLICY", "R-MODE-01", "Unknown exposure mode", "MD")

    blackout_name = datapoint.get("blackout")
    if blackout_name and _blackout_active(config, as_of or date.today()):
        return PolicyDecision("BLOCKED_BY_POLICY", rule_id, "Datapoint is in a blackout window", "MD")

    if requested_mode == "MD" and datapoint.get("requires_approval"):
        return PolicyDecision("NEEDS_APPROVAL", rule_id, "Owner approval is required", "MD")

    if requested_mode == "MD":
        return PolicyDecision("ALLOWED", rule_id, "Metadata-only access", "MD")

    if datapoint.get("never_leave") or datapoint.get("ceiling") == "MD":
        return PolicyDecision("BLOCKED_BY_POLICY", rule_id, "Datapoint is metadata-only", "MD")

    upgrade_mode = datapoint.get("upgrade_with_approval")
    needs_approval = datapoint.get("requires_approval") or requested_mode == upgrade_mode
    grant_valid = grant_mode == requested_mode
    if needs_approval and not grant_valid:
        return PolicyDecision("NEEDS_APPROVAL", rule_id, "Owner approval is required", "MD")

    ceiling = datapoint.get("ceiling")
    allowed_modes = _ALLOWED_BY_CEILING.get(str(ceiling), set())
    if requested_mode not in allowed_modes and not (
        grant_valid and requested_mode == upgrade_mode
    ):
        return PolicyDecision("BLOCKED_BY_POLICY", rule_id, "Requested mode exceeds the exposure ceiling", "MD")

    code: DecisionCode = "ALLOWED_SUMMARY_ONLY" if requested_mode == "SUM" else "ALLOWED"
    return PolicyDecision(code, rule_id, "Access allowed by node policy", requested_mode)


def _blackout_active(config: NodeAuthConfig, as_of: date) -> bool:
    for window in config.calendar_windows:
        start = date.fromisoformat(window["start"])
        end = date.fromisoformat(window["end"])
        if start <= as_of <= end:
            return True
    return False