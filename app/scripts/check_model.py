"""One call to the answer model named in the model policy, to prove the key and the wiring before a restart.

Run from app:  ../.venv/bin/python -m scripts.check_model
Uses config/model_policy.json unless NEURALMESH_MODEL_POLICY names another file. Prints the model, the
tokens and the first line of the answer. Nothing is written to the audit.
"""
from __future__ import annotations

import sys

from services.context import policy as model_policy
from services.context.llm import ModelBackend, has_api_key

SYSTEM = "Answer from the evidence only, in one sentence, and cite the document ID in brackets."
USER = ("EVIDENCE\n[ceat:E-03-01] Lots are trended per supplier at receipt, and a lot outside its band is held.\n"
        "QUESTION\nWhat does CEAT do with a lot outside its band?")


def main() -> int:
    choice = model_policy.choice_for("answer")
    print(f"policy model: {choice.model} (provider {choice.provider}, tier {choice.tier}, key from {choice.api_key_env or 'none'})")
    if not has_api_key(choice):
        print(f"no key: set {choice.api_key_env} in app/.env or the environment")
        return 1
    text, tokens_in, tokens_out = ModelBackend().complete(choice, SYSTEM, USER)
    print(f"tokens in {tokens_in}, out {tokens_out}")
    print("answer:", text.strip().splitlines()[0] if text.strip() else "(empty)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
