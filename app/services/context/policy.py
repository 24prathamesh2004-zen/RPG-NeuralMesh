"""Model policy: which model and tier each step may use, strict mode and token budgets (plan v2, 3.8.6)."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

POLICY_PATH = Path(__file__).resolve().parents[2] / "config" / "model_policy.json"
TIERS = ("gateway", "local", "cloud")


class PolicyViolation(RuntimeError):
    pass


@dataclass(frozen=True)
class ModelChoice:
    step: str
    model: str
    tier: str
    base_url: str
    api_key_env: str
    max_input_tokens: int
    max_output_tokens: int
    provider: str = "openai-compatible"  # or "anthropic"


@lru_cache(maxsize=4)
def _load(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def policy() -> dict:
    return _load(os.getenv("NEURALMESH_MODEL_POLICY", str(POLICY_PATH)))


def strict_mode(app_env: str) -> bool:
    return app_env != "development"


def choice_for(step: str) -> ModelChoice:
    data = policy()
    name = data["steps"][step]["model"]
    model = data["models"][name]
    # a model inside the group network is named at deployment: "id_env" and "base_url_env" give the environment variables
    # that hold its id and its address, so neither is written into the repository
    model = {**model, "id": os.getenv(model.get("id_env", ""), "") or model["id"], "base_url": os.getenv(model.get("base_url_env", ""), "") or model.get("base_url", "")}
    return ModelChoice(step, model["id"], model["tier"], model.get("base_url", ""), model.get("api_key_env", ""),
                       data["steps"][step]["max_input_tokens"], data["steps"][step]["max_output_tokens"],
                       model.get("provider", "openai-compatible"))


def check_startup(app_env: str) -> list[str]:
    """In strict mode the service refuses to start with a cloud model or a model outside the policy file."""
    problems = []
    data = policy()
    for step, conf in data["steps"].items():
        model = data["models"].get(conf["model"])
        if model is None:
            problems.append(f"step {step} names model {conf['model']}, which is not in the policy file")
        elif model["tier"] not in TIERS:
            problems.append(f"model {conf['model']} has unknown tier {model['tier']}")
        elif strict_mode(app_env) and model["tier"] == "cloud":
            problems.append(f"step {step} uses the cloud model {model['id']} outside development")
    if problems and strict_mode(app_env):
        raise PolicyViolation("; ".join(problems))
    return problems


def allowed(choice: ModelChoice, app_env: str, sensitivities: set[str], all_synthetic: bool) -> tuple[bool, str]:
    """Whether the model of a step may read this content. A gateway or local model may read anything. A cloud model is
    for development only, and there it reads invented data. It reads real data only when the policy file says
    "development_cloud_for_real": true, which is a switch for testing on a developer's own machine: outside development
    a cloud model is refused whatever the file says."""
    if choice.tier == "cloud":
        if app_env != "development":
            return False, "cloud tier is allowed in development only"
        real_allowed = bool(policy().get("development_cloud_for_real", False))
        if not all_synthetic and not real_allowed:
            return False, "cloud tier needs every pack in the bundle to be synthetic"
        confidential_allowed = real_allowed if not all_synthetic else bool(policy().get("development_cloud_for_synthetic_confidential", False))
        if sensitivities & {"Confidential", "Restricted"} and not confidential_allowed:
            return False, "bundle holds Confidential or Restricted records"
    return True, "allowed"


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)
