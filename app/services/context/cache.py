"""Answer cache keyed by the evidence bundle. Partial results, failed checks and model errors are never stored."""
from __future__ import annotations

import hashlib
import json
import threading
from collections import OrderedDict

from contracts.evidence import EvidenceRecord

_MAX = 500


def bundle_key(question: str, purpose: str, company: str, roles: list[str], as_of: str | None,
               records: list[EvidenceRecord], relationship_ids: list[str], model: str, prompt_version: str) -> str:
    parts = {
        "q": " ".join(question.lower().split()), "purpose": purpose, "company": company, "roles": sorted(roles),
        "as_of": as_of, "evidence": sorted(f"{r.evidence_id}|{r.version}|{r.mode}" for r in records),
        "rels": sorted(relationship_ids), "model": model, "prompt": prompt_version,
    }
    return hashlib.sha256(json.dumps(parts, sort_keys=True).encode()).hexdigest()


class AnswerCache:
    def __init__(self) -> None:
        self._data: OrderedDict[str, dict] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: str) -> dict | None:
        with self._lock:
            value = self._data.get(key)
            if value is not None:
                self._data.move_to_end(key)
            return value

    def put(self, key: str, value: dict) -> None:
        with self._lock:
            self._data[key] = value
            self._data.move_to_end(key)
            while len(self._data) > _MAX:
                self._data.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._data.clear()


def rerank_key(question: str, selected: dict[str, list[EvidenceRecord]], model: str) -> str:
    parts = {"q": " ".join(question.lower().split()), "model": model,
             "docs": sorted(f"{doc}|{recs[0].version}|{recs[0].mode}" for doc, recs in selected.items())}
    return hashlib.sha256(json.dumps(parts, sort_keys=True).encode()).hexdigest()


ANSWER_CACHE = AnswerCache()
RERANK_CACHE = AnswerCache()
