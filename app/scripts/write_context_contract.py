"""Write the published contract bundle and its lock file (planning_docs/RPG_NeuralMesh_Generic_Context_Delivery_Standard_Plan.md, 2.7).

    python -m scripts.write_context_contract          # writes contracts/schemas/context_contract.json and the lock

Run it after a change to contracts/context.py or services/context_catalogue.py. The lock holds the version and the
hash: tests/test_context_contract.py fails when the bundle changes but the version does not, so every change of the
contract is a deliberate new version, and applications see it through the hash of GET /api/v1/context/contract.
"""
from __future__ import annotations

import json
from pathlib import Path

from services.context_catalogue import bundle

SCHEMAS = Path(__file__).resolve().parents[1] / "contracts" / "schemas"
BUNDLE = SCHEMAS / "context_contract.json"
LOCK = SCHEMAS / "context_contract.lock.json"


def guard(new: dict, lock: dict | None) -> str | None:
    """Why the bundle may not be written: its content changed while its version did not."""
    if lock and new["sha256"] != lock.get("sha256") and new["version"] == lock.get("version"):
        return (f"The contract changed but its version is still {new['version']}. Raise CONTRACT_VERSION in "
                "contracts/context.py (minor for an added field, tool or code, major for a removed or renamed one) and run this again.")
    return None


def main() -> None:
    b = bundle()
    lock = json.loads(LOCK.read_text(encoding="utf-8")) if LOCK.is_file() else None
    refused = guard(b, lock)
    if refused:
        raise SystemExit(refused)
    BUNDLE.write_text(json.dumps(b, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    LOCK.write_text(json.dumps({"version": b["version"], "sha256": b["sha256"]}, indent=2) + "\n", encoding="utf-8")
    print(f"contract {b['version']} sha256 {b['sha256']}")


if __name__ == "__main__":
    main()
