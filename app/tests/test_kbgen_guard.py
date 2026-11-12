"""The generator kbgen.py deletes and rewrites the whole data folder. It must stop before it deletes a file that holds
real data (the real data plan, step 1). These tests use a temporary folder only and never run the generation."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1]


def _kbgen():
    spec = importlib.util.spec_from_file_location("kbgen_under_test", APP / "neuralmesh_kb_pack" / "kbgen.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write(path: Path, value) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value if isinstance(value, str) else json.dumps(value), encoding="utf-8")
    return path


def test_only_files_marked_invented_may_be_deleted(tmp_path):
    kbgen = _kbgen()
    _write(tmp_path / "ceat" / "packs" / "engineering" / "pack.json", {"pack": {"pack_id": "ceat.engineering", "synthetic": True}})
    _write(tmp_path / "ceat" / "contributions" / "E-03-U001.json", {"status": "accepted", "synthetic": True})
    assert kbgen.real_records(tmp_path) == []
    unmarked = _write(tmp_path / "ceat" / "contributions" / "E-03-U002.json", {"status": "accepted"})
    real = _write(tmp_path / "kec" / "contributions" / "L-02-U001.json", {"status": "accepted", "synthetic": False})
    item = _write(tmp_path / "kec" / "added_items" / "L-09.json", {"code": "L-09"})
    pack = _write(tmp_path / "kec" / "packs" / "lessons" / "pack.json", {"pack": {"pack_id": "kec.lessons"}})
    broken = _write(tmp_path / "others" / "contributions" / "G-01-U001.json", "{not json")
    leftover = _write(tmp_path / "others" / "contributions" / "G-01-U002.json.tmp", {"status": "accepted", "synthetic": True})
    nested = _write(tmp_path / "kec" / "contributions" / "old" / "L-02-U009.json", {"status": "accepted"})
    _write(tmp_path / "kec" / "added_items" / "L-08.json", {"code": "L-08", "synthetic": True})
    assert set(kbgen.real_records(tmp_path)) == {unmarked, real, item, pack, broken, leftover, nested}


def test_the_generator_stops_and_deletes_nothing_when_a_file_is_real(tmp_path, monkeypatch):
    kbgen = _kbgen()
    note = _write(tmp_path / "ceat" / "contributions" / "E-03-U001.json", {"status": "accepted"})
    monkeypatch.setattr(kbgen, "OUT", tmp_path)
    assert kbgen.OUT == tmp_path  # main() below reads this folder only
    with pytest.raises(SystemExit) as stopped:
        kbgen.main()
    assert "E-03-U001.json" in str(stopped.value) and "synthetic" in str(stopped.value)
    assert note.exists() and json.loads(note.read_text()) == {"status": "accepted"}
