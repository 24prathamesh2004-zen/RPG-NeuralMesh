"""Compute the similarity layer on the current graph and write SIMILAR_TO links through the intake.

Run from app:  ../.venv/bin/python -m scripts.similarity_job
Prints how many links were written per entity type. Reads the shared graph store, so the running API and gateway
pick the links up on their next request (revision reload).
"""
from __future__ import annotations

import json

from services import similarity
from services.mesh_runtime import runtime


def main() -> None:
    rt = runtime()
    print(json.dumps(similarity.run(rt.mesh), indent=2))


if __name__ == "__main__":
    main()
